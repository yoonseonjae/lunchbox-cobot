"""
test_mock_repository.py
MockOrderRepository 단위 테스트.
"""
import time
import threading
import pytest
from unittest.mock import MagicMock

from cobot1.repositories.mock_order_repository import MockOrderRepository
from cobot1.repositories.order_repository import Order


# ── 픽스처 ──────────────────────────────────────────────────────────────────
@pytest.fixture
def repo() -> MockOrderRepository:
    return MockOrderRepository()


def _make_order(key: str = "test-001") -> Order:
    return Order(
        key="test-001" if key == "test-001" else key,
        sub_dishes=["피클", "단무지"],
        main_dish="돈까스",
    )


# ── inject_order 테스트 ──────────────────────────────────────────────────────
class TestInjectOrder:
    def test_inject_default_order(self, repo):
        """order=None 일 때 기본 주문이 생성되어야 함."""
        repo.inject_order()
        assert not repo._order_q.empty()

    def test_inject_custom_order(self, repo):
        order = _make_order("order-XYZ")
        repo.inject_order(order)
        queued = repo._order_q.get(timeout=1.0)
        assert queued.key == "order-XYZ"

    def test_listen_orders_triggers_callback(self, repo):
        received = []
        repo.listen_orders(lambda o: received.append(o))
        order = _make_order()
        repo.inject_order(order)
        time.sleep(0.3)  # 디스패치 스레드 대기
        assert len(received) == 1
        assert received[0].key == order.key

    def test_multiple_orders_dispatched_in_order(self, repo):
        received = []
        repo.listen_orders(lambda o: received.append(o.key))
        for i in range(3):
            repo.inject_order(_make_order(f"order-{i}"))
        time.sleep(0.5)
        assert received == ["order-0", "order-1", "order-2"]


# ── inject_command 테스트 ────────────────────────────────────────────────────
class TestInjectCommand:
    def test_inject_command_queued(self, repo):
        repo.inject_command("emergency_stop")
        assert not repo._cmd_q.empty()

    def test_listen_commands_triggers_callback(self, repo):
        received = []
        repo.listen_commands(lambda c: received.append(c))
        repo.inject_command("resume")
        time.sleep(0.3)
        assert received == ["resume"]


# ── mark_* 상태 변경 테스트 ──────────────────────────────────────────────────
class TestMarkStatus:
    def test_mark_processing_no_exception(self, repo):
        repo.mark_processing("order-001")  # 예외 없음

    def test_mark_completed_no_exception(self, repo):
        repo.mark_completed("order-001")

    def test_mark_error_no_exception(self, repo):
        repo.mark_error("order-001")


# ── upload_robot_status 테스트 ───────────────────────────────────────────────
class TestUploadRobotStatus:
    def test_status_stored_in_list(self, repo):
        payload = {"state": "idle", "current_task": "대기 중"}
        repo.upload_robot_status(payload)
        assert len(repo._statuses) == 1
        assert repo._statuses[0] == payload

    def test_multiple_statuses_accumulated(self, repo):
        for i in range(5):
            repo.upload_robot_status({"state": f"state-{i}"})
        assert len(repo._statuses) == 5

    def test_thread_safe_status_upload(self, repo):
        errors = []
        def uploader():
            try:
                repo.upload_robot_status({"state": "idle"})
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=uploader) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(repo._statuses) == 20

    def test_available_property_is_true(self, repo):
        assert repo.available is True
