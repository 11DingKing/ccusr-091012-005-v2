import threading
import time
from decimal import Decimal

from django.db import IntegrityError, OperationalError, connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from apps.core.exceptions import BusinessException
from .models import (
    Approval, Category, Goods, StockIn, StockOut, Unit, Variety, Warning,
    QuarantineCase, QuarantineDecision, QuarantineMovement,
)

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


class QuarantineFixture(TestCase):
    """隔离处置测试基类：货物 12 件，存放于 A-01"""

    def setUp(self):
        self.user = User.objects.create_user("quarantine-user", "testpass123", role="admin")
        self.approver = User.objects.create_user("quarantine-approver", "testpass123", role="admin")
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
            location="A-01",
        )

    def _create_case(self, quantity="10", **overrides):
        payload = {
            "goods": self.goods.id,
            "quantity": quantity,
            "reason": "package_damaged",
            "reason_detail": "入库检查发现外包装破损",
        }
        payload.update(overrides)
        return self.client.post("/api/quarantine-cases/", payload, format="json")

    def _propose_and_review(self, case_id, decision_type, quantity, approve=True, opinion="同意"):
        proposed = self.client.post(
            f"/api/quarantine-cases/{case_id}/decisions/",
            {"decision_type": decision_type, "quantity": quantity, "reason": "复检后处置"},
            format="json",
        )
        self.assertEqual(proposed.status_code, 200, proposed.json())
        decision_id = proposed.json()["data"]["id"]
        reviewed = self.client.post(
            f"/api/quarantine-decisions/{decision_id}/review/",
            {"approve": approve, "opinion": opinion},
            format="json",
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.json())
        return reviewed.json()["data"]


class QuarantineCaseFlowTest(QuarantineFixture):
    def test_create_case_freezes_quantity_and_records_movement(self):
        stock_in = StockIn.objects.create(
            goods=self.goods, operator=self.user, quantity=Decimal("12"), batch_no="B20261001"
        )
        response = self._create_case("10", stock_in=stock_in.id)
        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()["data"]
        self.assertTrue(data["case_no"].startswith("QZ"))
        self.assertEqual(data["status"], "open")
        self.assertEqual(Decimal(data["remaining_quantity"]), Decimal("10"))

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quarantined_quantity, Decimal("10"))
        self.assertEqual(self.goods.available_quantity, Decimal("2"))
        self.assertTrue(self.goods.has_active_quarantine)

        movement = QuarantineMovement.objects.get(case_id=data["id"])
        self.assertEqual(movement.movement_type, "quarantine")
        self.assertEqual(movement.from_location, "A-01")
        self.assertEqual(movement.to_location, "隔离区")

    def test_create_case_validates_quantity_reason_and_stock_in(self):
        over = self._create_case("13")
        self.assertEqual(over.status_code, 400)
        self.assertIn("可用", over.json()["message"])

        bad_reason = self._create_case("5", reason="unknown")
        self.assertEqual(bad_reason.status_code, 400)

        other_goods = Goods.objects.create(
            variety=self.variety, name="另一终端", code="DEV-002", quantity=Decimal("3")
        )
        foreign_in = StockIn.objects.create(
            goods=other_goods, operator=self.user, quantity=Decimal("3")
        )
        foreign = self._create_case("5", stock_in=foreign_in.id)
        self.assertEqual(foreign.status_code, 400)

    def test_inspection_records_are_linked_to_case(self):
        case_id = self._create_case("10").json()["data"]["id"]
        response = self.client.post(
            f"/api/quarantine-cases/{case_id}/inspections/",
            {"result": "partial", "conclusion": "4件包装完好，6件受潮"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.json())

        detail = self.client.get(f"/api/quarantine-cases/{case_id}/").json()["data"]
        self.assertEqual(len(detail["inspections"]), 1)
        self.assertEqual(detail["inspections"][0]["result"], "partial")
        self.assertEqual(detail["inspections"][0]["conclusion"], "4件包装完好，6件受潮")

    def test_partial_release_keeps_remaining_quarantined(self):
        case_id = self._create_case("10").json()["data"]["id"]
        self._propose_and_review(case_id, "release", "4")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))
        self.assertEqual(self.goods.quarantined_quantity, Decimal("6"))
        self.assertEqual(self.goods.available_quantity, Decimal("6"))

        detail = self.client.get(f"/api/quarantine-cases/{case_id}/").json()["data"]
        self.assertEqual(detail["status"], "open")
        self.assertEqual(Decimal(detail["remaining_quantity"]), Decimal("6"))
        breakdown = detail["quantity_breakdown"]
        self.assertEqual(Decimal(breakdown["released"]), Decimal("4"))
        self.assertEqual(Decimal(breakdown["quarantined"]), Decimal("6"))

    def test_return_decision_reduces_stock_and_closes_case(self):
        case_id = self._create_case("10").json()["data"]["id"]
        self._propose_and_review(case_id, "return", "10")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("2"))
        self.assertEqual(self.goods.quarantined_quantity, Decimal("0"))

        detail = self.client.get(f"/api/quarantine-cases/{case_id}/").json()["data"]
        self.assertEqual(detail["status"], "closed")
        breakdown = detail["quantity_breakdown"]
        self.assertEqual(Decimal(breakdown["returned"]), Decimal("10"))
        self.assertEqual(Decimal(breakdown["quarantined"]), Decimal("0"))

        # 结案后不能再复检或提出新决定
        inspection = self.client.post(
            f"/api/quarantine-cases/{case_id}/inspections/",
            {"result": "pass", "conclusion": "结案后复检"},
            format="json",
        )
        self.assertEqual(inspection.status_code, 400)
        decision = self.client.post(
            f"/api/quarantine-cases/{case_id}/decisions/",
            {"decision_type": "release", "quantity": "1"},
            format="json",
        )
        self.assertEqual(decision.status_code, 400)

    def test_rejected_decision_keeps_stock_and_opinion(self):
        case_id = self._create_case("10").json()["data"]["id"]
        decision = self._propose_and_review(
            case_id, "destroy", "5", approve=False, opinion="需补充检测报告"
        )
        self.assertEqual(decision["status"], "rejected")
        self.assertEqual(decision["approval_opinion"], "需补充检测报告")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))
        self.assertEqual(self.goods.quarantined_quantity, Decimal("10"))

    def test_approve_beyond_remaining_is_rejected(self):
        case_id = self._create_case("10").json()["data"]["id"]
        self.client.post(
            f"/api/quarantine-cases/{case_id}/decisions/",
            {"decision_type": "release", "quantity": "6"}, format="json",
        )
        second = self.client.post(
            f"/api/quarantine-cases/{case_id}/decisions/",
            {"decision_type": "release", "quantity": "5"}, format="json",
        )
        first_id = QuarantineDecision.objects.get(quantity=Decimal("6")).id
        second_id = second.json()["data"]["id"]

        ok = self.client.post(
            f"/api/quarantine-decisions/{first_id}/review/",
            {"approve": True, "opinion": "同意"}, format="json",
        )
        self.assertEqual(ok.status_code, 200)
        over = self.client.post(
            f"/api/quarantine-decisions/{second_id}/review/",
            {"approve": True, "opinion": "同意"}, format="json",
        )
        self.assertEqual(over.status_code, 400)
        self.assertIn("剩余隔离数量不足", over.json()["message"])

    def test_revoke_release_generates_reversal_not_delete(self):
        case_id = self._create_case("10").json()["data"]["id"]
        decision = self._propose_and_review(case_id, "release", "4")

        revoked = self.client.post(
            f"/api/quarantine-decisions/{decision['id']}/revoke/",
            {"reason": "放行单填写错误"}, format="json",
        )
        self.assertEqual(revoked.status_code, 200, revoked.json())
        self.assertEqual(revoked.json()["data"]["status"], "revoked")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quarantined_quantity, Decimal("10"))
        self.assertEqual(self.goods.available_quantity, Decimal("2"))

        detail = self.client.get(f"/api/quarantine-cases/{case_id}/").json()["data"]
        self.assertEqual(detail["status"], "open")
        # 历史保留：隔离 + 放行 + 撤销放行 三条流水
        movement_types = [m["movement_type"] for m in detail["movements"]]
        self.assertEqual(movement_types, ["quarantine", "release", "revoke_release"])
        reversal = detail["movements"][2]
        original = detail["movements"][1]
        self.assertEqual(reversal["reverses"], original["id"])
        # 决定本身也保留，状态为已撤销
        self.assertEqual(detail["decisions"][0]["status"], "revoked")
        self.assertEqual(detail["decisions"][0]["revoke_reason"], "放行单填写错误")
        # 数量去向：放行净额归零，全部仍处隔离
        breakdown = detail["quantity_breakdown"]
        self.assertEqual(Decimal(breakdown["released"]), Decimal("0"))
        self.assertEqual(Decimal(breakdown["quarantined"]), Decimal("10"))

    def test_revoke_return_restores_stock_and_reopens_case(self):
        case_id = self._create_case("10").json()["data"]["id"]
        decision = self._propose_and_review(case_id, "return", "10")
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("2"))

        revoked = self.client.post(
            f"/api/quarantine-decisions/{decision['id']}/revoke/",
            {"reason": "供应商拒收"}, format="json",
        )
        self.assertEqual(revoked.status_code, 200)

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))
        self.assertEqual(self.goods.quarantined_quantity, Decimal("10"))

        detail = self.client.get(f"/api/quarantine-cases/{case_id}/").json()["data"]
        self.assertEqual(detail["status"], "open")
        movement_types = [m["movement_type"] for m in detail["movements"]]
        self.assertEqual(movement_types, ["quarantine", "return", "revoke_return"])

    def test_revoke_requires_approved_decision(self):
        case_id = self._create_case("10").json()["data"]["id"]
        proposed = self.client.post(
            f"/api/quarantine-cases/{case_id}/decisions/",
            {"decision_type": "release", "quantity": "4"}, format="json",
        )
        decision_id = proposed.json()["data"]["id"]
        # 待审批不能撤销
        pending = self.client.post(f"/api/quarantine-decisions/{decision_id}/revoke/", {}, format="json")
        self.assertEqual(pending.status_code, 400)
        # 已拒绝不能撤销
        self.client.post(
            f"/api/quarantine-decisions/{decision_id}/review/",
            {"approve": False, "opinion": "不同意"}, format="json",
        )
        rejected = self.client.post(f"/api/quarantine-decisions/{decision_id}/revoke/", {}, format="json")
        self.assertEqual(rejected.status_code, 400)

    def test_revoke_release_blocked_when_stock_already_out(self):
        case_id = self._create_case("10").json()["data"]["id"]
        decision = self._propose_and_review(case_id, "release", "4")
        # 放行后的 4 件被领用出库，可用库存不足以回冻
        out = self.client.post(
            "/api/stock-out/",
            {"goods": self.goods.id, "quantity": "6", "receiver": "张三"}, format="json",
        )
        self.assertEqual(out.status_code, 200)
        revoked = self.client.post(
            f"/api/quarantine-decisions/{decision['id']}/revoke/", {}, format="json",
        )
        self.assertEqual(revoked.status_code, 400)
        self.assertIn("无法撤销", revoked.json()["message"])

    def test_case_detail_accounts_for_every_unit(self):
        case_id = self._create_case("10").json()["data"]["id"]
        self._propose_and_review(case_id, "release", "2")
        self._propose_and_review(case_id, "concession", "2")
        self._propose_and_review(case_id, "return", "3")
        self._propose_and_review(case_id, "destroy", "1")

        detail = self.client.get(f"/api/quarantine-cases/{case_id}/").json()["data"]
        breakdown = detail["quantity_breakdown"]
        total = sum(Decimal(breakdown[k]) for k in ("released", "returned", "destroyed", "quarantined"))
        self.assertEqual(total, Decimal("10"))
        self.assertEqual(Decimal(breakdown["released"]), Decimal("4"))
        self.assertEqual(Decimal(breakdown["returned"]), Decimal("3"))
        self.assertEqual(Decimal(breakdown["destroyed"]), Decimal("1"))
        self.assertEqual(Decimal(breakdown["quarantined"]), Decimal("2"))
        self.assertEqual(detail["status"], "open")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("8"))
        self.assertEqual(self.goods.quarantined_quantity, Decimal("2"))


class QuarantineBlockingTest(QuarantineFixture):
    """有效隔离对领用与转移的阻断"""

    def test_stock_out_blocked_by_active_quarantine(self):
        self._create_case("10")
        response = self.client.post(
            "/api/stock-out/",
            {"goods": self.goods.id, "quantity": "3", "receiver": "张三"}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("隔离", response.json()["message"])
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))

    def test_stock_out_allowed_within_available(self):
        self._create_case("10")
        response = self.client.post(
            "/api/stock-out/",
            {"goods": self.goods.id, "quantity": "2", "receiver": "张三"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("10"))
        self.assertEqual(self.goods.quarantined_quantity, Decimal("10"))
        self.assertEqual(self.goods.available_quantity, Decimal("0"))

    def test_stock_out_without_quarantine_limited_by_stock(self):
        response = self.client.post(
            "/api/stock-out/",
            {"goods": self.goods.id, "quantity": "13", "receiver": "张三"}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("库存不足", response.json()["message"])

    def test_transfer_blocked_by_active_quarantine(self):
        self._create_case("10")
        response = self.client.post(
            f"/api/goods/{self.goods.id}/transfer/",
            {"location": "B-02"}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("隔离", response.json()["message"])
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.location, "A-01")

    def test_transfer_allowed_after_case_closed(self):
        case_id = self._create_case("10").json()["data"]["id"]
        self._propose_and_review(case_id, "return", "10")
        response = self.client.post(
            f"/api/goods/{self.goods.id}/transfer/",
            {"location": "B-02"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.location, "B-02")

    def test_goods_list_exposes_quarantine_fields(self):
        self._create_case("10")
        response = self.client.get("/api/goods/")
        self.assertEqual(response.status_code, 200)
        item = response.json()["data"]["list"][0]
        self.assertEqual(Decimal(item["quarantined_quantity"]), Decimal("10"))
        self.assertEqual(Decimal(item["available_quantity"]), Decimal("2"))
        self.assertTrue(item["has_active_quarantine"])


class QuarantineConcurrencyTest(TransactionTestCase):
    """并发场景：隔离冻结不能被并发领用击穿"""

    def setUp(self):
        self.user = User.objects.create_user("concurrent-user", "testpass123", role="admin")
        self.unit = Unit.objects.create(name="件", created_by=self.user)
        self.category = Category.objects.create(name="受控器材", unit=self.unit, created_by=self.user)
        self.variety = Variety.objects.create(name="记录终端", category=self.category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=self.variety, name="执法记录终端", code="DEV-001",
            quantity=Decimal("12"), location="A-01",
        )

    @staticmethod
    def _run_with_lock_retry(fn, attempts=100):
        """
        共享缓存的内存 SQLite 不支持写锁等待，会直接抛出
        “database table is locked”；这里重试以模拟文件库/生产库上
        busy_timeout 的等待行为，守卫条件本身由条件 UPDATE 保证。
        """
        for _ in range(attempts):
            try:
                return fn()
            except OperationalError as exc:
                if 'locked' not in str(exc):
                    raise
                time.sleep(0.02)
        raise AssertionError('锁等待重试次数耗尽')

    def test_concurrent_stock_out_never_touches_quarantined_stock(self):
        from apps.warehouse import services

        services.create_quarantine_case(
            goods_id=self.goods.id, quantity=Decimal("10"),
            reason="package_damaged", user=self.user,
        )
        # 可用仅 2 件，两个并发领用各要 2 件，只能成功一个
        barrier = threading.Barrier(2)
        outcomes = []

        def worker(name):
            try:
                barrier.wait(timeout=10)
                self._run_with_lock_retry(lambda: services.register_stock_out(
                    goods_id=self.goods.id, quantity=Decimal("2"),
                    receiver=name, user=self.user,
                ))
                outcomes.append("ok")
            except BusinessException:
                outcomes.append("blocked")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(f"领用人{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(sorted(outcomes), ["blocked", "ok"])
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("10"))
        self.assertEqual(self.goods.quarantined_quantity, Decimal("10"))
        self.assertEqual(StockOut.objects.filter(goods=self.goods).count(), 1)

    def test_concurrent_case_creation_never_overfreezes(self):
        from apps.warehouse import services

        barrier = threading.Barrier(2)
        outcomes = []

        def worker():
            try:
                barrier.wait(timeout=10)
                self._run_with_lock_retry(lambda: services.create_quarantine_case(
                    goods_id=self.goods.id, quantity=Decimal("10"),
                    reason="package_damaged", user=self.user,
                ))
                outcomes.append("ok")
            except BusinessException:
                outcomes.append("blocked")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(sorted(outcomes), ["blocked", "ok"])
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quarantined_quantity, Decimal("10"))
        self.assertEqual(QuarantineCase.objects.filter(goods=self.goods).count(), 1)
