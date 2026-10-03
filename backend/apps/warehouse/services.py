"""
隔离处置与库存变动的业务逻辑

库存数量的守卫条件（如“可用数量充足”“剩余隔离数量充足”）全部通过
带条件的 UPDATE 语句在数据库层原子完成（filter(...).update(...) 的
影响行数为 0 即判定冲突），不依赖先读后写，因此并发领用、转移与
处置在 SQLite/PostgreSQL/MySQL 上都不会击穿隔离冻结。
"""
import logging
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.exceptions import BusinessException
from .models import (
    Goods, StockIn, StockOut,
    QuarantineCase, QuarantineInspection, QuarantineDecision, QuarantineMovement,
)

logger = logging.getLogger('apps')

# 处置方式 -> 对应流水类型
DECISION_MOVEMENT_TYPE = {
    'release': 'release',
    'concession': 'concession',
    'return': 'return',
    'destroy': 'destroy',
}

# 处置方式 -> 撤销时生成的反向流水类型
REVOKE_MOVEMENT_TYPE = {
    'release': 'revoke_release',
    'concession': 'revoke_concession',
    'return': 'revoke_return',
    'destroy': 'revoke_destroy',
}

# 处置后货物离开仓库（库存总量减少）的方式
OUTBOUND_DECISION_TYPES = ('return', 'destroy')


def _get_goods(goods_id):
    try:
        return Goods.objects.get(pk=goods_id)
    except Goods.DoesNotExist:
        raise BusinessException('货物不存在', code=404)


def _get_case(case_id):
    try:
        return QuarantineCase.objects.get(pk=case_id)
    except QuarantineCase.DoesNotExist:
        raise BusinessException('隔离案件不存在', code=404)


def _validate_positive_quantity(quantity, label='数量'):
    if quantity is None:
        raise BusinessException(f'请填写{label}')
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise BusinessException(f'{label}必须大于0')
    return quantity


def _generate_case_no(case):
    """依据主键生成可追溯的案件编号"""
    return f"QZ{timezone.localtime(case.created_at):%Y%m%d}-{case.pk:04d}"


@transaction.atomic
def create_quarantine_case(*, goods_id, quantity, reason, user, reason_detail='',
                           stock_in_id=None, quarantine_location='隔离区', remark=''):
    """
    建立隔离处置案件：冻结受影响数量并记录首条“隔离入库”流水。
    """
    quantity = _validate_positive_quantity(quantity, '影响数量')

    if reason not in dict(QuarantineCase.REASON_CHOICES):
        raise BusinessException('发现原因无效')

    # 原子冻结（事务首个写操作，避免读写锁升级死锁）：
    # 仅当可用数量（库存 - 已隔离）足够时才增加隔离数量
    frozen = Goods.objects.filter(
        pk=goods_id,
        quantity__gte=F('quarantined_quantity') + quantity,
    ).update(
        quarantined_quantity=F('quarantined_quantity') + quantity,
        updated_at=timezone.now(),
    )
    if not frozen:
        goods = _get_goods(goods_id)
        raise BusinessException(
            f'影响数量超出可用库存，当前可用 {goods.available_quantity}'
        )

    goods = _get_goods(goods_id)

    stock_in = None
    if stock_in_id:
        try:
            stock_in = StockIn.objects.get(pk=stock_in_id, goods_id=goods.pk)
        except StockIn.DoesNotExist:
            raise BusinessException('来源入库记录不存在或不属于该货物')

    case = QuarantineCase.objects.create(
        case_no=f'PENDING-{uuid4().hex}',
        goods=goods,
        stock_in=stock_in,
        reason=reason,
        reason_detail=reason_detail,
        quantity=quantity,
        remaining_quantity=quantity,
        quarantine_location=quarantine_location or '隔离区',
        found_by=user,
        remark=remark,
    )
    case.case_no = _generate_case_no(case)
    case.save(update_fields=['case_no'])

    QuarantineMovement.objects.create(
        case=case,
        movement_type='quarantine',
        quantity=quantity,
        from_location=goods.location,
        to_location=case.quarantine_location,
        operator=user,
        note=f'隔离原因：{case.get_reason_display()}',
    )

    logger.info(
        f"User {user.username} created quarantine case {case.case_no} "
        f"for goods {goods.code}, quantity {quantity}"
    )
    return case


def _touch_open_case(case_id):
    """原子确认案件处于隔离中并刷新时间，同时取得行级写锁"""
    touched = QuarantineCase.objects.filter(
        pk=case_id, status='open'
    ).update(updated_at=timezone.now())
    if not touched:
        if not QuarantineCase.objects.filter(pk=case_id).exists():
            raise BusinessException('隔离案件不存在', code=404)
        raise BusinessException('案件已结案，无法操作')


@transaction.atomic
def add_inspection(*, case_id, result, conclusion, user):
    """登记复检记录"""
    if result not in dict(QuarantineInspection.RESULT_CHOICES):
        raise BusinessException('复检结果无效')
    if not conclusion:
        raise BusinessException('请填写复检结论')
    _touch_open_case(case_id)

    inspection = QuarantineInspection.objects.create(
        case_id=case_id,
        inspector=user,
        result=result,
        conclusion=conclusion,
    )
    logger.info(
        f"User {user.username} added inspection to case {case_id}: {result}"
    )
    return inspection


@transaction.atomic
def propose_decision(*, case_id, decision_type, quantity, user, reason=''):
    """提出处置决定（待审批）"""
    if decision_type not in dict(QuarantineDecision.TYPE_CHOICES):
        raise BusinessException('处置方式无效')
    quantity = _validate_positive_quantity(quantity, '处置数量')
    _touch_open_case(case_id)

    case = _get_case(case_id)
    if quantity > case.remaining_quantity:
        raise BusinessException(
            f'处置数量超出剩余隔离数量，当前剩余 {case.remaining_quantity}'
        )

    decision = QuarantineDecision.objects.create(
        case=case,
        decision_type=decision_type,
        quantity=quantity,
        reason=reason,
        proposed_by=user,
    )
    logger.info(
        f"User {user.username} proposed {decision_type} decision "
        f"for case {case.case_no}, quantity {quantity}"
    )
    return decision


@transaction.atomic
def review_decision(*, decision_id, approve, opinion, user):
    """
    审批处置决定。通过时在同一事务内执行库存移动并记录流水；
    拒绝时仅保留审批意见，不动库存。
    """
    now = timezone.now()
    # 原子认领：只有待审批的决定能被处理，防止并发重复审批
    claimed = QuarantineDecision.objects.filter(
        pk=decision_id, status='pending'
    ).update(
        status='approved' if approve else 'rejected',
        approver=user,
        approval_opinion=opinion,
        approved_at=now,
        updated_at=now,
    )
    if not claimed:
        if not QuarantineDecision.objects.filter(pk=decision_id).exists():
            raise BusinessException('处置决定不存在', code=404)
        raise BusinessException('该决定已审批，无法重复操作')

    decision = QuarantineDecision.objects.get(pk=decision_id)
    if not approve:
        logger.info(
            f"User {user.username} rejected decision {decision.pk} "
            f"of case {decision.case.case_no}"
        )
        return decision

    case = decision.case
    goods = case.goods

    # 原子扣减剩余隔离数量；不足时整个审批回滚
    deducted = QuarantineCase.objects.filter(
        pk=case.pk, remaining_quantity__gte=decision.quantity
    ).update(
        remaining_quantity=F('remaining_quantity') - decision.quantity,
        updated_at=now,
    )
    if not deducted:
        case.refresh_from_db()
        raise BusinessException(
            f'剩余隔离数量不足，当前剩余 {case.remaining_quantity}，'
            f'无法执行该决定'
        )

    # 原子解冻/出库：隔离数量必须足够覆盖本次处置
    if decision.decision_type in OUTBOUND_DECISION_TYPES:
        moved = Goods.objects.filter(
            pk=goods.pk, quarantined_quantity__gte=decision.quantity
        ).update(
            quantity=F('quantity') - decision.quantity,
            quarantined_quantity=F('quarantined_quantity') - decision.quantity,
            updated_at=now,
        )
    else:
        moved = Goods.objects.filter(
            pk=goods.pk, quarantined_quantity__gte=decision.quantity
        ).update(
            quarantined_quantity=F('quarantined_quantity') - decision.quantity,
            updated_at=now,
        )
    if not moved:
        raise BusinessException('货物隔离数量异常，无法执行该决定')

    case.refresh_from_db()
    if case.remaining_quantity == 0:
        QuarantineCase.objects.filter(pk=case.pk).update(status='closed')
        case.status = 'closed'

    goods.refresh_from_db()
    if decision.decision_type in OUTBOUND_DECISION_TYPES:
        to_location = '供应商' if decision.decision_type == 'return' else '销毁点'
    else:
        to_location = goods.location
    QuarantineMovement.objects.create(
        case=case,
        decision=decision,
        movement_type=DECISION_MOVEMENT_TYPE[decision.decision_type],
        quantity=decision.quantity,
        from_location=case.quarantine_location,
        to_location=to_location,
        operator=user,
        note=f'审批意见：{opinion}' if opinion else '',
    )

    logger.info(
        f"User {user.username} approved {decision.decision_type} decision "
        f"{decision.pk} of case {case.case_no}, quantity {decision.quantity}"
    )
    return decision


@transaction.atomic
def revoke_decision(*, decision_id, reason, user):
    """
    撤销已执行的决定：生成反向流水恢复库存，而不是删除历史。
    """
    now = timezone.now()
    # 原子认领：只有已执行的决定能被撤销
    claimed = QuarantineDecision.objects.filter(
        pk=decision_id, status='approved'
    ).update(
        status='revoked',
        revoked_by=user,
        revoke_reason=reason,
        revoked_at=now,
        updated_at=now,
    )
    if not claimed:
        if not QuarantineDecision.objects.filter(pk=decision_id).exists():
            raise BusinessException('处置决定不存在', code=404)
        raise BusinessException('只有已执行的决定才能撤销')

    decision = QuarantineDecision.objects.get(pk=decision_id)
    case = decision.case
    goods = case.goods

    if decision.decision_type in OUTBOUND_DECISION_TYPES:
        # 退回/销毁的撤销：物资重新入库并回到隔离状态
        Goods.objects.filter(pk=goods.pk).update(
            quantity=F('quantity') + decision.quantity,
            quarantined_quantity=F('quarantined_quantity') + decision.quantity,
            updated_at=now,
        )
        from_location = '供应商' if decision.decision_type == 'return' else '销毁点'
    else:
        # 放行/让步接收的撤销：数量重新冻结，要求这部分库存仍在库
        refrozen = Goods.objects.filter(
            pk=goods.pk,
            quantity__gte=F('quarantined_quantity') + decision.quantity,
        ).update(
            quarantined_quantity=F('quarantined_quantity') + decision.quantity,
            updated_at=now,
        )
        if not refrozen:
            goods.refresh_from_db()
            raise BusinessException(
                f'可用库存不足（当前可用 {goods.available_quantity}），'
                f'已放行物资可能已出库，无法撤销'
            )
        from_location = goods.location

    # 案件回到隔离中
    QuarantineCase.objects.filter(pk=case.pk).update(
        remaining_quantity=F('remaining_quantity') + decision.quantity,
        status='open',
        updated_at=now,
    )
    case.refresh_from_db()

    original_movement = decision.movements.filter(
        movement_type=DECISION_MOVEMENT_TYPE[decision.decision_type]
    ).first()
    QuarantineMovement.objects.create(
        case=case,
        decision=decision,
        movement_type=REVOKE_MOVEMENT_TYPE[decision.decision_type],
        quantity=decision.quantity,
        from_location=from_location,
        to_location=case.quarantine_location,
        reverses=original_movement,
        operator=user,
        note=f'撤销原因：{reason}' if reason else '撤销决定',
    )

    logger.info(
        f"User {user.username} revoked decision {decision.pk} "
        f"of case {case.case_no}"
    )
    return decision


@transaction.atomic
def register_stock_in(*, goods_id, quantity, user, batch_no='', supplier='', remark=''):
    """入库登记：增加库存总量"""
    quantity = _validate_positive_quantity(quantity, '入库数量')

    updated = Goods.objects.filter(pk=goods_id).update(
        quantity=F('quantity') + quantity,
        updated_at=timezone.now(),
    )
    if not updated:
        raise BusinessException('货物不存在', code=404)
    goods = _get_goods(goods_id)

    stock_in = StockIn.objects.create(
        goods=goods,
        operator=user,
        quantity=quantity,
        batch_no=batch_no,
        supplier=supplier,
        remark=remark,
    )

    logger.info(
        f"User {user.username} registered stock-in for goods {goods.code}, "
        f"quantity {quantity}"
    )
    return stock_in


@transaction.atomic
def register_stock_out(*, goods_id, quantity, receiver, user, receiver_dept='', remark=''):
    """
    领用登记：扣减可用库存。存在有效隔离时，隔离数量不可领用；
    扣减条件在数据库层原子判断，并发领用不会击穿冻结。
    """
    quantity = _validate_positive_quantity(quantity, '领用数量')
    if not receiver:
        raise BusinessException('请填写领用人')

    # 原子扣减：仅当 库存 - 隔离 >= 本次领用 时才扣减
    deducted = Goods.objects.filter(
        pk=goods_id,
        quantity__gte=F('quarantined_quantity') + quantity,
    ).update(
        quantity=F('quantity') - quantity,
        updated_at=timezone.now(),
    )
    if not deducted:
        goods = _get_goods(goods_id)
        if goods.quarantined_quantity > 0:
            raise BusinessException(
                f'该货物存在有效隔离（隔离 {goods.quarantined_quantity}，'
                f'可用 {goods.available_quantity}），领用被阻断'
            )
        raise BusinessException(f'库存不足，当前可用 {goods.available_quantity}')

    goods = _get_goods(goods_id)
    stock_out = StockOut.objects.create(
        goods=goods,
        operator=user,
        receiver=receiver,
        receiver_dept=receiver_dept,
        quantity=quantity,
        status='completed',
        stock_out_time=timezone.now(),
        remark=remark,
    )

    logger.info(
        f"User {user.username} registered stock-out for goods {goods.code}, "
        f"quantity {quantity}"
    )
    return stock_out


@transaction.atomic
def transfer_goods(*, goods_id, location, user, remark=''):
    """
    转移库位。存在有效隔离（隔离数量未处置完）时禁止转移，
    避免冻结中的物资脱离隔离位置。
    """
    if not location:
        raise BusinessException('请填写目标位置')

    # 原子守卫：仅当不存在有效隔离数量时才允许换库位
    moved = Goods.objects.filter(
        pk=goods_id, quarantined_quantity=0
    ).update(
        location=location,
        updated_at=timezone.now(),
    )
    if not moved:
        goods = _get_goods(goods_id)
        raise BusinessException(
            f'该货物存在有效隔离（隔离 {goods.quarantined_quantity}），转移被阻断'
        )

    goods = _get_goods(goods_id)
    logger.info(
        f"User {user.username} transferred goods {goods.code} to {location}"
    )
    return goods


def case_quantity_breakdown(case):
    """
    按当前处置状态汇总案件影响数量的去向，
    使每一数量单位都能对账：放行 / 退回 / 销毁 / 仍隔离。
    """
    totals = {
        'released': Decimal('0'),
        'returned': Decimal('0'),
        'destroyed': Decimal('0'),
    }
    release_types = ('release', 'concession')
    for movement in case.movements.all():
        sign = Decimal('-1') if movement.movement_type.startswith('revoke_') else Decimal('1')
        base_type = movement.movement_type.removeprefix('revoke_')
        if base_type in release_types:
            totals['released'] += sign * movement.quantity
        elif base_type == 'return':
            totals['returned'] += sign * movement.quantity
        elif base_type == 'destroy':
            totals['destroyed'] += sign * movement.quantity

    return {
        'total': case.quantity,
        'released': totals['released'],
        'returned': totals['returned'],
        'destroyed': totals['destroyed'],
        'quarantined': case.remaining_quantity,
    }
