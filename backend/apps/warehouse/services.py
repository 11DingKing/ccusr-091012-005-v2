"""
隔离处置案件工作流服务

把 发现原因 → 影响数量（拆分处置单元）→ 复检记录 → 审批意见 → 库存移动
串成一条可追溯链路。所有写操作均在行级锁事务内完成，保证并发领用/转移
与隔离处置互不穿透；撤销只生成反向动作，不删除任何历史记录。
"""
import threading
from contextlib import contextmanager
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.exceptions import BusinessException
from .models import (
    Goods, StockOut,
    QuarantineCase, QuarantineUnit, QuarantineReinspection,
    QuarantineApproval, QuarantineDisposition, QuarantineRevocation,
    StockMovement,
)

UNIT_QUANTITY = Decimal('1.00')
ZERO = Decimal('0')

# 库存关键段串行化：Postgres/MySQL 上由 select_for_update 兜底；
# SQLite 不支持行级锁，进程内锁保证单进程（gunicorn 线程模式）并发安全。
_STOCK_LOCK = threading.RLock()


@contextmanager
def _stock_lock():
    with _STOCK_LOCK:
        yield


# ==================== 立案 ====================

def open_case(*, operator, goods, affected_quantity, discovery_reason,
              reason_detail='', batch_no='', stock_in=None,
              quarantine_location='隔离区'):
    """登记隔离处置案件：锁定货物、按数量单位拆分处置单元、登记移入隔离区。"""
    affected_quantity = Decimal(str(affected_quantity))
    if affected_quantity <= 0:
        raise BusinessException('影响数量必须大于0')
    if affected_quantity % UNIT_QUANTITY != 0:
        raise BusinessException('影响数量需为整数个数量单位，以便逐单位追踪处置状态')

    with _stock_lock(), transaction.atomic():
        locked_goods = Goods.objects.select_for_update().get(pk=goods.pk)
        if affected_quantity > locked_goods.quantity:
            raise BusinessException(
                f'影响数量 {affected_quantity} 超过货物库存 {locked_goods.quantity}'
            )
        # 与该货物其他有效隔离案件不可重叠超量。
        # 注意：不因待出库占用而拒绝立案——发现异常必须能隔离，已审批但未出库的
        # 领用会在出库执行瞬间被阻断（complete_requisition 重新校验隔离状态）。
        held = locked_goods.quarantined_quantity
        if held + affected_quantity > locked_goods.quantity:
            raise BusinessException(
                f'该货物已有有效隔离 {held}，本次隔离 {affected_quantity} 将超过库存总量'
            )

        case = QuarantineCase.objects.create(
            goods=locked_goods,
            stock_in=stock_in,
            batch_no=batch_no or (stock_in.batch_no if stock_in else ''),
            discoverer=operator,
            discovery_reason=discovery_reason,
            reason_detail=reason_detail,
            affected_quantity=affected_quantity,
            quarantine_location=quarantine_location,
            origin_location=locked_goods.location,
            status=QuarantineCase.Disposition.PENDING,
        )

        units = []
        for seq in range(1, int(affected_quantity) + 1):
            units.append(QuarantineUnit(case=case, seq=seq))
        QuarantineUnit.objects.bulk_create(units)

        # 实物移入隔离区（不改变库存账面总量）
        StockMovement.record(
            case=case,
            move_type=StockMovement.MoveType.QUARANTINE_IN,
            quantity=affected_quantity,
            operator=operator,
            from_location=locked_goods.location,
            to_location=quarantine_location,
            remark=f'{case.get_discovery_reason_display()}，立案隔离',
        )
        locked_goods.location = quarantine_location
        locked_goods.save(update_fields=['location', 'updated_at'])
        return case


# ==================== 复检 ====================

def add_reinspection(*, case, inspector, result, finding='',
                     qualified_quantity=ZERO, concession_quantity=ZERO,
                     unqualified_quantity=ZERO):
    """登记复检记录并推进案件到"已复检待审批"。"""
    qualified_quantity = Decimal(str(qualified_quantity or 0))
    concession_quantity = Decimal(str(concession_quantity or 0))
    unqualified_quantity = Decimal(str(unqualified_quantity or 0))

    with _stock_lock(), transaction.atomic():
        case = QuarantineCase.objects.select_for_update().get(pk=case.pk)
        if case.status == QuarantineCase.Disposition.REVOKED:
            raise BusinessException('案件已撤销，不能追加复检')
        if case.held_quantity <= 0:
            raise BusinessException('案件已无有效隔离数量，无需复检')

        total = qualified_quantity + concession_quantity + unqualified_quantity
        if result == QuarantineReinspection.Result.PENDING:
            raise BusinessException('请给出明确的复检结果')
        if total <= 0:
            raise BusinessException('请填写各复检结论对应的数量')
        if total > case.held_quantity:
            raise BusinessException(
                f'复检数量合计 {total} 超过当前有效隔离数量 {case.held_quantity}'
            )

        record = QuarantineReinspection.objects.create(
            case=case, inspector=inspector, result=result, finding=finding,
            qualified_quantity=qualified_quantity,
            concession_quantity=concession_quantity,
            unqualified_quantity=unqualified_quantity,
        )
        if case.status == QuarantineCase.Disposition.PENDING:
            case.status = QuarantineCase.Disposition.REINSPECTED
            case.save(update_fields=['status', 'updated_at'])
        return record


# ==================== 审批决定与库存移动 ====================

_DECISION_TO_KIND = {
    QuarantineApproval.Decision.RELEASE: QuarantineDisposition.Kind.RELEASE,
    QuarantineApproval.Decision.CONCESSION: QuarantineDisposition.Kind.CONCESSION,
    QuarantineApproval.Decision.RETURN: QuarantineDisposition.Kind.RETURN,
}


def _refresh_case_status(case):
    """依据各处置单元的落账情况重算案件状态与结案时间。"""
    case.refresh_from_db()
    if case.status == QuarantineCase.Disposition.REVOKED:
        return case
    held = case.held_quantity
    if held >= case.affected_quantity:
        # 无任何生效处置（含全部决定已被撤销的情形）
        case.status = (
            QuarantineCase.Disposition.REINSPECTED
            if case.reinspections.exists()
            else QuarantineCase.Disposition.PENDING
        )
        case.closed_at = None
    elif held > 0:
        # 部分放行/让步后仍有剩余数量保持隔离
        case.status = QuarantineCase.Disposition.RELEASED
        case.closed_at = None
    else:
        if case.returned_quantity == case.affected_quantity:
            case.status = QuarantineCase.Disposition.RETURNED
        elif (case.concession_quantity == case.affected_quantity):
            case.status = QuarantineCase.Disposition.CONCESSION
        else:
            case.status = QuarantineCase.Disposition.RELEASED
        case.closed_at = case.closed_at or timezone.now()
    case.save(update_fields=['status', 'closed_at', 'updated_at'])
    return case


def decide(*, case, approver, decision, quantity, target_location='',
           opinion='', reinspection=None):
    """落审批意见：在处置单元上分配数量，并生成对应的库存移动。"""
    quantity = Decimal(str(quantity))
    kind = _DECISION_TO_KIND[QuarantineApproval.Decision(decision)]

    with _stock_lock(), transaction.atomic():
        case = QuarantineCase.objects.select_for_update().get(pk=case.pk)
        goods = Goods.objects.select_for_update().get(pk=case.goods_id)

        if case.status == QuarantineCase.Disposition.REVOKED:
            raise BusinessException('案件已撤销，不能作出处置决定')
        if quantity <= 0:
            raise BusinessException('处置数量必须大于0')
        if quantity > case.held_quantity:
            raise BusinessException(
                f'处置数量 {quantity} 超过案件当前有效隔离数量 {case.held_quantity}'
            )
        if not case.reinspections.exists():
            raise BusinessException('请先完成复检并登记复检记录，再提交审批决定')

        if reinspection is None:
            reinspection = case.reinspections.first()
        elif reinspection.case_id != case.id:
            raise BusinessException('复检记录不属于该案件')

        target_location = target_location or case.origin_location
        approval = QuarantineApproval.objects.create(
            case=case, reinspection=reinspection, approver=approver,
            decision=decision, quantity=quantity,
            target_location=target_location if kind != QuarantineDisposition.Kind.RETURN else '',
            opinion=opinion,
        )

        # 按单元序号依次分配处置数量
        remaining = quantity
        units = list(
            QuarantineUnit.objects.select_for_update()
            .filter(case=case, hold_active=True)
            .order_by('seq')
        )
        for unit in units:
            if remaining <= 0:
                break
            slice_qty = min(unit.hold_quantity, remaining)
            remaining -= slice_qty

            if kind == QuarantineDisposition.Kind.RETURN:
                move_type = StockMovement.MoveType.RETURN_OUT
                to_location = ''
            else:
                move_type = StockMovement.MoveType.QUARANTINE_OUT
                to_location = target_location

            _, movement = StockMovement.record(
                case=case, approval=approval, move_type=move_type,
                quantity=slice_qty, operator=approver,
                from_location=case.quarantine_location,
                to_location=to_location,
                remark=approval.get_decision_display(),
            )
            unit.apply_disposition(kind, slice_qty)
            QuarantineDisposition.objects.create(
                approval=approval, unit=unit, movement=movement,
                kind=kind, quantity=slice_qty,
            )

        if remaining > 0:
            # 理论上不可达（前置已校验 held 数量），兜底保护
            raise BusinessException('有效隔离数量不足，处置未能全部落账')

        # 该货物已无任何有效隔离时，主库位恢复为放行/让步入库位置
        if goods.quarantined_quantity == 0 and kind != QuarantineDisposition.Kind.RETURN:
            goods.location = target_location
            goods.save(update_fields=['location', 'updated_at'])

        _refresh_case_status(case)
        return approval


# ==================== 撤销（生成反向动作） ====================

def revoke_decision(*, approval, operator, reason=''):
    """撤销一次处置审批：逐条反向冲销库存移动，数量退回有效隔离。"""
    with _stock_lock(), transaction.atomic():
        approval = QuarantineApproval.objects.select_for_update().get(pk=approval.pk)
        if hasattr(approval, 'revocation'):
            raise BusinessException('该审批决定已被撤销')

        case = QuarantineCase.objects.select_for_update().get(pk=approval.case_id)
        if case.status == QuarantineCase.Disposition.REVOKED:
            raise BusinessException('案件已撤销')

        goods = Goods.objects.select_for_update().get(pk=case.goods_id)
        dispositions = list(
            approval.dispositions.select_for_update().filter(reversed_at__isnull=True)
        )
        if not dispositions:
            raise BusinessException('该审批决定没有可撤销的处置落账')

        # 放行/让步已被后续领用消耗时不能收回隔离
        outbound_qty = sum(
            (d.quantity for d in dispositions
             if d.kind != QuarantineDisposition.Kind.RETURN),
            ZERO,
        )
        if outbound_qty > 0:
            free_stock = goods.quantity - goods.quarantined_quantity
            if outbound_qty > free_stock:
                raise BusinessException(
                    f'已放行/让步的 {outbound_qty} 中有数量已被领用或转移，'
                    f'当前可收回库存仅 {free_stock}，无法撤销'
                )

        for disposition in dispositions:
            unit = QuarantineUnit.objects.select_for_update().get(pk=disposition.unit_id)
            disposition.movement.reverse(
                operator=operator,
                remark=f'撤销审批 {approval.id}：{reason}' if reason else f'撤销审批 {approval.id}',
            )
            unit.revert_disposition(disposition.kind, disposition.quantity)
            disposition.reversed_at = timezone.now()
            disposition.save(update_fields=['reversed_at'])

        QuarantineRevocation.objects.create(
            approval=approval, operator=operator, reason=reason
        )
        # 数量回到隔离区，货物主库位回落为隔离位置
        if goods.quarantined_quantity > 0:
            goods.location = case.quarantine_location
            goods.save(update_fields=['location', 'updated_at'])

        _refresh_case_status(case)
        return approval


def revoke_case(*, case, operator, reason=''):
    """撤销尚未作出处置决定的案件（如误立案）：反向冲销移入隔离区动作。"""
    with _stock_lock(), transaction.atomic():
        case = QuarantineCase.objects.select_for_update().get(pk=case.pk)
        if case.status == QuarantineCase.Disposition.REVOKED:
            raise BusinessException('案件已撤销')
        goods = Goods.objects.select_for_update().get(pk=case.goods_id)
        effective_approvals = [
            a for a in case.approvals.all() if not hasattr(a, 'revocation')
        ]
        if effective_approvals:
            raise BusinessException('案件已存在处置决定，请逐条撤销决定后再撤销案件')

        quarantine_in = case.movements.filter(
            move_type=StockMovement.MoveType.QUARANTINE_IN, is_reversed=False
        ).first()
        if quarantine_in is not None:
            quarantine_in.reverse(operator=operator, remark=f'撤销案件：{reason}')

        QuarantineUnit.objects.filter(case=case).update(hold_active=False)
        # 物理位置恢复为立案前库位
        if case.origin_location:
            goods.location = case.origin_location
            goods.save(update_fields=['location', 'updated_at'])
        case.status = QuarantineCase.Disposition.REVOKED
        case.closed_at = timezone.now()
        case.save(update_fields=['status', 'closed_at', 'updated_at'])
        return case


# ==================== 领用 / 转移阻断 ====================

def _outbound_reserved(goods):
    """待出库占用：待审批 + 已审批但未完成的领用数量总和。"""
    total = StockOut.objects.filter(
        goods=goods, status__in=['pending', 'approved']
    ).aggregate(total=Sum('quantity'))['total']
    return total or ZERO


def create_requisition(*, operator, goods, quantity, receiver,
                       receiver_dept='', remark=''):
    """发起领用。遇到有效隔离（或待出库占用）导致可用数量不足时阻断。"""
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise BusinessException('领用数量必须大于0')
    with _stock_lock(), transaction.atomic():
        locked_goods = Goods.objects.select_for_update().get(pk=goods.pk)
        locked_goods.assert_movable(quantity)
        reserved = _outbound_reserved(locked_goods)
        free = locked_goods.available_quantity - reserved
        if quantity > free:
            raise BusinessException(
                f'可用数量 {locked_goods.available_quantity}，'
                f'待出库已占用 {reserved}，本次申请 {quantity} 已被有效隔离阻断',
                code=409
            )
        return StockOut.objects.create(
            goods=locked_goods, operator=operator,
            receiver=receiver, receiver_dept=receiver_dept,
            quantity=quantity, status='pending',
            remark=remark,
        )


def complete_requisition(*, stock_out, operator):
    """领用出库完成：出库瞬间再次校验隔离状态并扣减库存。"""
    with _stock_lock(), transaction.atomic():
        stock_out = StockOut.objects.select_for_update().get(pk=stock_out.pk)
        if stock_out.status != 'approved':
            raise BusinessException(
                f'当前状态（{stock_out.get_status_display()}）不能出库，需先审批通过'
            )
        goods = Goods.objects.select_for_update().get(pk=stock_out.goods_id)
        goods.assert_movable(stock_out.quantity)
        if stock_out.quantity > goods.quantity:
            raise BusinessException('库存数量不足')
        goods.quantity -= stock_out.quantity
        goods.save(update_fields=['quantity', 'updated_at'])
        stock_out.status = 'completed'
        stock_out.stock_out_time = timezone.now()
        stock_out.save(update_fields=['status', 'stock_out_time'])
        return stock_out


def transfer_goods(*, operator, goods, quantity, to_location, remark=''):
    """库位转移。有效隔离数量不得被转移。"""
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise BusinessException('转移数量必须大于0')
    if not to_location:
        raise BusinessException('请填写目标库位')
    with _stock_lock(), transaction.atomic():
        locked_goods = Goods.objects.select_for_update().get(pk=goods.pk)
        locked_goods.assert_movable(quantity)
        movement = StockMovement.objects.create(
            case=None, move_type=StockMovement.MoveType.TRANSFER,
            goods=locked_goods, quantity=quantity,
            from_location=locked_goods.location, to_location=to_location,
            operator=operator, remark=remark,
        )
        # 仍有有效隔离时，隔离实物还在隔离区，主库位保留隔离指示不被覆盖
        if locked_goods.quarantined_quantity == 0:
            locked_goods.location = to_location
            locked_goods.save(update_fields=['location', 'updated_at'])
        return movement
