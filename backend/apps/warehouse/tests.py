from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from .models import (
    Approval, Category, Goods, StockIn, StockOut, Unit, Variety, Warning,
    QuarantineCase, QuarantineUnit, QuarantineApproval, StockMovement,
)
from . import services


class WarehouseFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("warehouse-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        self.unit = Unit.objects.create(name="件", created_by=self.user)
        self.category = Category.objects.create(name="受控器材", unit=self.unit, created_by=self.user)
        self.variety = Variety.objects.create(name="记录终端", category=self.category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=self.variety,
            name="执法记录终端",
            code="DEV-001",
            quantity=Decimal("12"),
            warning_threshold=Decimal("5"),
        )


class WarehouseModelTest(WarehouseFixture):
    def test_relationship_flags(self):
        self.assertTrue(self.unit.is_linked)
        self.assertTrue(self.category.is_linked)
        self.assertTrue(self.variety.is_in_stock)
        self.assertFalse(self.goods.is_warning)

    def test_unique_unit_name(self):
        with self.assertRaises(IntegrityError):
            Unit.objects.create(name="件", created_by=self.user)

    def test_stock_records_and_approval(self):
        inbound = StockIn.objects.create(goods=self.goods, operator=self.user, quantity=Decimal("3"))
        outbound = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="保管员", quantity=Decimal("2")
        )
        approval = Approval.objects.create(stock_out=outbound, approver=self.user)
        self.assertEqual(inbound.goods_id, self.goods.id)
        self.assertEqual(approval.status, "pending")

    def test_warning_record(self):
        warning = Warning.objects.create(goods=self.goods, type="low_stock", message="库存不足")
        self.assertFalse(warning.is_read)
        self.assertIn("执法记录终端", str(warning))


class WarehouseAPITest(WarehouseFixture):
    def test_list_units(self):
        response = self.client.get("/api/units/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 1)

    def test_create_unit_and_reject_duplicate(self):
        created = self.client.post("/api/units/", {"name": "箱"}, format="json")
        duplicate = self.client.post("/api/units/", {"name": "箱"}, format="json")
        self.assertEqual(created.status_code, 200)
        self.assertEqual(duplicate.status_code, 400)

    def test_update_linked_unit(self):
        response = self.client.put(f"/api/units/{self.unit.id}/", {"name": "台"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.name, "台")

    def test_refuse_delete_linked_unit(self):
        response = self.client.delete(f"/api/units/{self.unit.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Unit.objects.filter(pk=self.unit.id).exists())

    def test_create_category_validates_unit(self):
        ok = self.client.post("/api/categories/", {"name": "封存介质", "unit": self.unit.id}, format="json")
        bad = self.client.post("/api/categories/", {"name": "无效分类", "unit": 99999}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(bad.status_code, 400)

    def test_create_variety_and_duplicate_boundary(self):
        ok = self.client.post("/api/varieties/", {"name": "封存硬盘", "category": self.category.id}, format="json")
        duplicate = self.client.post("/api/varieties/", {"name": "封存硬盘", "category": self.category.id}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(duplicate.status_code, 400)

    def test_requires_authentication(self):
        anonymous = APIClient().get("/api/units/")
        self.assertEqual(anonymous.status_code, 401)


class QuarantineFixture(WarehouseFixture):
    def setUp(self):
        super().setUp()
        # 原库位 + 充足库存
        self.goods.location = "A区货架"
        self.goods.quantity = Decimal("10")
        self.goods.save()

    def open_case(self, affected=Decimal("4"), reason="package_damaged"):
        return services.open_case(
            operator=self.user, goods=self.goods,
            affected_quantity=affected, discovery_reason=reason,
            reason_detail="外箱挤压破损",
        )

    def reinspect(self, case, qualified=Decimal("4"),
                  concession=Decimal("0"), unqualified=Decimal("0"),
                  result="qualified"):
        return services.add_reinspection(
            case=case, inspector=self.user, result=result,
            qualified_quantity=qualified,
            concession_quantity=concession,
            unqualified_quantity=unqualified,
            finding="开箱复检",
        )


class QuarantineCaseModelTest(QuarantineFixture):
    def test_open_case_creates_units_and_quarantine_movement(self):
        case = self.open_case(affected=Decimal("4"))
        self.assertEqual(case.units.count(), 4)
        self.assertTrue(case.code.startswith("QC"))
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.location, "隔离区")
        # 隔离不动账面总量
        self.assertEqual(self.goods.quantity, Decimal("10"))
        self.assertEqual(self.goods.quarantined_quantity, Decimal("4"))
        self.assertEqual(self.goods.available_quantity, Decimal("6"))

        move = case.movements.get(move_type="quarantine_in")
        self.assertEqual(move.from_location, "A区货架")
        self.assertEqual(move.to_location, "隔离区")
        self.assertTrue(move.is_effective)

    def test_case_quantity_cannot_exceed_stock_or_overlap(self):
        self.open_case(affected=Decimal("8"))
        with self.assertRaises(Exception):
            self.open_case(affected=Decimal("3"))
        with self.assertRaises(Exception):
            self.open_case(affected=Decimal("11"))


class QuarantineWorkflowTest(QuarantineFixture):
    def test_partial_release_keeps_remainder_held(self):
        case = self.open_case(affected=Decimal("4"))
        self.reinspect(case)
        approval = services.decide(
            case=case, approver=self.user, decision="release",
            quantity=Decimal("1"), target_location="A区货架",
            opinion="1件复检合格放行",
        )
        case.refresh_from_db()
        self.assertEqual(case.held_quantity, Decimal("3"))
        self.assertEqual(case.released_quantity, Decimal("1"))
        self.assertEqual(case.status, "released")  # 部分放行
        self.assertIsNone(case.closed_at)

        # 每单位状态：1 已放行，其余 3 个仍隔离中
        statuses = list(case.units.order_by("seq").values_list("status", flat=True))
        self.assertEqual(
            statuses, ["released", "held", "held", "held"]
        )
        first = case.units.get(seq=1)
        self.assertFalse(first.hold_active)
        self.assertEqual(first.hold_quantity, Decimal("0"))
        for seq in (2, 3, 4):
            unit = case.units.get(seq=seq)
            self.assertTrue(unit.hold_active)
            self.assertEqual(unit.hold_quantity, Decimal("1"))

        # 处置落账与移动串联到审批
        disposition = approval.dispositions.get()
        self.assertEqual(disposition.kind, "release")
        self.assertEqual(disposition.movement.move_type, "quarantine_out")
        self.assertEqual(disposition.movement.to_location, "A区货架")

    def test_concession_and_return_close_case(self):
        case = self.open_case(affected=Decimal("4"))
        self.reinspect(case, qualified=Decimal("2"), concession=Decimal("1"),
                       unqualified=Decimal("1"), result="concession")
        services.decide(case=case, approver=self.user, decision="concession",
                        quantity=Decimal("1"), opinion="让步接收1件")
        services.decide(case=case, approver=self.user, decision="return",
                        quantity=Decimal("1"), opinion="退回1件")
        services.decide(case=case, approver=self.user, decision="release",
                        quantity=Decimal("2"))
        case.refresh_from_db()
        self.assertEqual(case.held_quantity, Decimal("0"))
        self.assertEqual(case.concession_quantity, Decimal("1"))
        self.assertEqual(case.returned_quantity, Decimal("1"))
        self.assertEqual(case.released_quantity, Decimal("2"))
        self.assertIsNotNone(case.closed_at)
        # 退回扣减账面库存
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("9"))

    def test_decision_requires_reinspection(self):
        case = self.open_case(affected=Decimal("2"))
        with self.assertRaises(Exception):
            services.decide(case=case, approver=self.user,
                            decision="release", quantity=Decimal("1"))

    def test_reinspection_quantity_capped_by_held(self):
        case = self.open_case(affected=Decimal("2"))
        with self.assertRaises(Exception):
            self.reinspect(case, qualified=Decimal("3"))


class QuarantineRevocationTest(QuarantineFixture):
    def test_revoke_release_creates_reversal_not_delete(self):
        case = self.open_case(affected=Decimal("3"))
        self.reinspect(case, qualified=Decimal("3"))
        approval = services.decide(
            case=case, approver=self.user, decision="release",
            quantity=Decimal("3"), target_location="A区货架",
        )
        original_move = approval.dispositions.first().movement

        services.revoke_decision(approval=approval, operator=self.user,
                                 reason="放行依据有误")

        # 历史全部保留，且出现反向动作
        self.assertTrue(QuarantineApproval.objects.filter(pk=approval.pk).exists())
        self.assertTrue(QuarantineUnit.objects.filter(case=case).exists())
        original_move.refresh_from_db()
        self.assertTrue(original_move.is_reversed)
        reversal = original_move.reversed_by.get()
        self.assertEqual(reversal.move_type, "reversal")
        self.assertEqual(reversal.from_location, original_move.to_location)
        self.assertEqual(reversal.to_location, original_move.from_location)

        # 数量退回有效隔离
        case.refresh_from_db()
        self.assertEqual(case.held_quantity, Decimal("3"))
        self.assertEqual(case.released_quantity, Decimal("0"))
        self.assertEqual(case.status, "reinspected")
        for unit in case.units.all():
            self.assertTrue(unit.hold_active)

    def test_revoke_return_restores_stock(self):
        case = self.open_case(affected=Decimal("2"))
        self.reinspect(case, qualified=Decimal("0"), unqualified=Decimal("2"),
                       result="unqualified")
        approval = services.decide(
            case=case, approver=self.user, decision="return",
            quantity=Decimal("2"),
        )
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("8"))

        services.revoke_decision(approval=approval, operator=self.user)
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("10"))  # 反向补回
        return_move = approval.dispositions.first().movement
        self.assertTrue(return_move.is_reversed)

    def test_cannot_revoke_twice(self):
        case = self.open_case(affected=Decimal("1"))
        self.reinspect(case, qualified=Decimal("1"))
        approval = services.decide(case=case, approver=self.user,
                                   decision="release", quantity=Decimal("1"))
        services.revoke_decision(approval=approval, operator=self.user)
        with self.assertRaises(Exception):
            services.revoke_decision(approval=approval, operator=self.user)

    def test_revoke_blocked_when_released_stock_consumed(self):
        case = self.open_case(affected=Decimal("4"))
        self.reinspect(case)
        approval = services.decide(
            case=case, approver=self.user, decision="release",
            quantity=Decimal("4"), target_location="A区货架",
        )
        # 放行后，可用库存被领走 7（仅剩 3 < 待收回 4），撤销必须被阻断
        services.create_requisition(
            operator=self.user, goods=self.goods, quantity=Decimal("7"),
            receiver="外勤组",
        )
        stock_out = StockOut.objects.get(goods=self.goods)
        stock_out.status = "approved"
        stock_out.save()
        services.complete_requisition(stock_out=stock_out, operator=self.user)
        with self.assertRaises(Exception):
            services.revoke_decision(approval=approval, operator=self.user)

    def test_revoke_empty_case(self):
        case = self.open_case(affected=Decimal("2"))
        services.revoke_case(case=case, operator=self.user, reason="误立案")
        case.refresh_from_db()
        self.assertEqual(case.status, "revoked")
        quarantine_in = case.movements.get(move_type="quarantine_in")
        self.assertTrue(quarantine_in.is_reversed)
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.location, "A区货架")
        self.assertEqual(self.goods.quarantined_quantity, Decimal("0"))

    def test_cannot_revoke_case_with_decisions(self):
        case = self.open_case(affected=Decimal("1"))
        self.reinspect(case, qualified=Decimal("1"))
        services.decide(case=case, approver=self.user,
                        decision="release", quantity=Decimal("1"))
        with self.assertRaises(Exception):
            services.revoke_case(case=case, operator=self.user)


class QuarantineBlockingTest(QuarantineFixture):
    def test_requisition_blocked_by_active_quarantine(self):
        self.open_case(affected=Decimal("4"))
        # 可用 6：领用 6 可以，7 被阻断
        ok = services.create_requisition(
            operator=self.user, goods=self.goods, quantity=Decimal("6"),
            receiver="内勤",
        )
        self.assertEqual(ok.quantity, Decimal("6"))
        with self.assertRaises(Exception):
            services.create_requisition(
                operator=self.user, goods=self.goods, quantity=Decimal("7"),
                receiver="内勤",
            )

    def test_transfer_blocked_by_active_quarantine(self):
        self.open_case(affected=Decimal("4"))
        with self.assertRaises(Exception):
            services.transfer_goods(
                operator=self.user, goods=self.goods,
                quantity=Decimal("7"), to_location="B区货架",
            )
        movement = services.transfer_goods(
            operator=self.user, goods=self.goods,
            quantity=Decimal("6"), to_location="B区货架",
        )
        self.assertEqual(movement.move_type, "transfer")
        self.goods.refresh_from_db()
        # 仍有有效隔离时，主库位保留隔离指示（被转移的是可用部分）
        self.assertEqual(self.goods.location, "隔离区")
        # 隔离不随转移解除
        self.assertEqual(self.goods.quarantined_quantity, Decimal("4"))

    def test_partial_release_then_requisition_moves_with_available(self):
        case = self.open_case(affected=Decimal("4"))
        self.reinspect(case)
        services.decide(case=case, approver=self.user, decision="release",
                        quantity=Decimal("2"), target_location="A区货架")
        # 隔离 2 -> 可用 8
        self.assertEqual(self.goods.quarantined_quantity, Decimal("2"))
        services.create_requisition(
            operator=self.user, goods=self.goods, quantity=Decimal("8"),
            receiver="外勤",
        )
        # 有效隔离仍在：超过可用数量（8）的领用必须被阻断
        with self.assertRaises(Exception):
            services.create_requisition(
                operator=self.user, goods=self.goods, quantity=Decimal("9"),
                receiver="外勤",
            )

    def test_quarantine_imposed_after_approval_blocks_outbound(self):
        """领用已审批通过后才被立案隔离：出库执行瞬间仍被阻断"""
        services.create_requisition(
            operator=self.user, goods=self.goods, quantity=Decimal("9"),
            receiver="外勤",
        )
        stock_out = StockOut.objects.get(goods=self.goods)
        stock_out.status = "approved"
        stock_out.save()
        # 立案隔离 4 -> 可用 6，已审批的 9 件出库不得放行
        self.open_case(affected=Decimal("4"))
        with self.assertRaises(Exception):
            services.complete_requisition(stock_out=stock_out, operator=self.user)
        stock_out.refresh_from_db()
        self.assertNotEqual(stock_out.status, "completed")
        self.assertEqual(Goods.objects.get(pk=self.goods.pk).quantity, Decimal("10"))


class QuarantineConcurrencyTest(TransactionTestCase):
    """并发行：领用/转移与隔离处置交叉执行时，隔离数量绝不被穿透。"""

    def setUp(self):
        self.user = User.objects.create_user("cc-user", "testpass123", role="admin")
        unit = Unit.objects.create(name="件", created_by=self.user)
        category = Category.objects.create(name="受控器材", unit=unit, created_by=self.user)
        variety = Variety.objects.create(name="记录终端", category=category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=variety, name="执法记录终端", code="DEV-CONC",
            quantity=Decimal("10"), warning_threshold=Decimal("5"),
            location="A区货架",
        )

    def _run_threads(self, target, count):
        import threading
        errors, results = [], []

        def worker(idx):
            try:
                results.append(target(idx))
            except Exception as exc:  # 业务阻断以异常返回
                errors.append(exc)
            finally:
                from django.db import connection
                connection.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results, errors

    def test_concurrent_requisitions_cannot_overshoot_available(self):
        # 库存 10：10 个线程各领 3，成功占用之和绝不超过 10
        def attempt(_):
            return services.create_requisition(
                operator=self.user, goods=self.goods,
                quantity=Decimal("3"), receiver="并发领用",
            )
        results, errors = self._run_threads(attempt, 10)
        reserved = sum(
            StockOut.objects.filter(status__in=["pending", "approved"])
            .values_list("quantity", flat=True),
            Decimal("0"),
        )
        self.assertLessEqual(reserved, Decimal("10"))
        self.assertEqual(len(results) + len(errors), 10)
        self.assertGreater(len(errors), 0)

    def test_concurrent_requisition_against_quarantine_open(self):
        # 立案隔离（4）与领用（6）并发。隔离可优先于已申请领用立案，
        # 但超量领用必须在出库执行瞬间被阻断，隔离数量绝不被消耗。
        from apps.core.exceptions import BusinessException

        def attempt(idx):
            if idx % 2 == 0:
                return services.open_case(
                    operator=self.user, goods=self.goods,
                    affected_quantity=Decimal("4"),
                    discovery_reason="package_damaged",
                )
            return services.create_requisition(
                operator=self.user, goods=self.goods,
                quantity=Decimal("6"), receiver="并发领用",
            )

        results, errors = self._run_threads(attempt, 4)
        self.assertEqual(len(results) + len(errors), 4)

        # 审批通过后尝试执行所有领用：触碰有效隔离的必须在出库瞬间被阻断
        blocked = 0
        StockOut.objects.filter(status="pending").update(status="approved")
        for stock_out in StockOut.objects.filter(status="approved"):
            try:
                services.complete_requisition(
                    stock_out=stock_out, operator=self.user
                )
            except BusinessException:
                blocked += 1

        goods = Goods.objects.get(pk=self.goods.pk)
        outbound = sum(
            StockOut.objects.filter(status="completed").values_list("quantity", flat=True),
            Decimal("0"),
        )
        # 库存守恒：现存库存 + 已出库 = 初始 10（本场景无退回）
        self.assertEqual(goods.quantity + outbound, Decimal("10"))
        # 有效隔离数量始终有实物库存对应
        self.assertLessEqual(goods.quarantined_quantity, goods.quantity)
        # 至少有一个并发领用被阻断（否则说明隔离被穿透）
        self.assertGreaterEqual(
            blocked + len(errors), 1,
            "并发领用与隔离交叉时必须出现阻断",
        )

    def test_concurrent_transfer_blocked_by_quarantine(self):
        # 先立案隔离 4，两个线程同时转移 7：必须全部被阻断
        services.open_case(
            operator=self.user, goods=self.goods,
            affected_quantity=Decimal("4"),
            discovery_reason="package_damaged",
        )

        def attempt(_):
            return services.transfer_goods(
                operator=self.user, goods=self.goods,
                quantity=Decimal("7"), to_location="B区",
            )

        results, errors = self._run_threads(attempt, 2)
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 2)
        self.assertEqual(Goods.objects.get(pk=self.goods.pk).location, "隔离区")


class QuarantineAPITest(QuarantineFixture):
    def test_full_case_flow_via_api(self):
        # 立案
        resp = self.client.post("/api/quarantine-cases/", {
            "goods": self.goods.id,
            "discovery_reason": "package_damaged",
            "reason_detail": "包装破损",
            "affected_quantity": "3.00",
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        case_id = resp.json()["data"]["id"]

        # 案件详情含每单位状态
        detail = self.client.get(f"/api/quarantine-cases/{case_id}/")
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()["data"]
        self.assertEqual(len(payload["units"]), 3)
        self.assertEqual(payload["units"][0]["status"], "held")
        self.assertEqual(payload["movements"][0]["move_type"], "quarantine_in")

        # 复检
        resp = self.client.post(
            f"/api/quarantine-cases/{case_id}/reinspection/",
            {"result": "qualified", "qualified_quantity": "3.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        # 部分放行 1 件
        resp = self.client.post(
            f"/api/quarantine-cases/{case_id}/decision/",
            {"decision": "release", "quantity": "1.00",
             "target_location": "A区货架", "opinion": "放行1件"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        approval_id = resp.json()["data"]["id"]

        detail = self.client.get(f"/api/quarantine-cases/{case_id}/").json()["data"]
        self.assertEqual(
            [u["status"] for u in detail["units"]],
            ["released", "held", "held"],
        )

        # 领用被隔离数量阻断
        blocked = self.client.post("/api/stock-out/", {
            "goods": self.goods.id, "quantity": "10.00",
            "receiver": "外勤组",
        }, format="json")
        self.assertEqual(blocked.json()["code"], 409)

        # 撤销决定
        resp = self.client.post(
            f"/api/quarantine-approvals/{approval_id}/revoke/",
            {"reason": "依据有误"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        detail = self.client.get(f"/api/quarantine-cases/{case_id}/").json()["data"]
        self.assertTrue(all(u["hold_active"] for u in detail["units"]))
        self.assertTrue(
            any(m["move_type"] == "reversal" for m in detail["movements"])
        )

    def test_open_case_rejects_over_stock(self):
        resp = self.client.post("/api/quarantine-cases/", {
            "goods": self.goods.id,
            "discovery_reason": "other",
            "affected_quantity": "999.00",
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_transfer_api_blocked(self):
        case = self.open_case(affected=Decimal("5"))
        resp = self.client.post("/api/stock-movements/transfer/", {
            "goods": self.goods.id,
            "quantity": "6.00",
            "to_location": "B区",
        }, format="json")
        self.assertEqual(resp.json()["code"], 409)
