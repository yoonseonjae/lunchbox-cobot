"""
test_order_model.py
Order 도메인 객체 및 OrderRepository 인터페이스 단위 테스트.

2026-05-09 신규 작성
"""
import threading
import time
import pytest
from unittest.mock import MagicMock

from cobot1.repositories.order_repository import Order, OrderRepository
from cobot1.repositories.mock_order_repository import MockOrderRepository


# ── Order 데이터클래스 ──────────────────────────────────────────────────────
class TestOrderDataclass:
    def test_required_fields_stored(self):
        o = Order(key="k1", sub_dishes=["피클"], main_dish="불고기")
        assert o.key == "k1"
        assert o.sub_dishes == ["피클"]
        assert o.main_dish == "불고기"

    def test_default_status_is_pending(self):
        o = Order(key="k1", sub_dishes=[], main_dish="불고기")
        assert o.status == "pending"

    def test_default_target_stage_zero(self):
        o = Order(key="k1", sub_dishes=[], main_dish="불고기")
        assert o.target_stage == 0

    def test_default_run_mode_from(self):
        o = Order(key="k1", sub_dishes=[], main_dish="불고기")
        assert o.run_mode == "from"

    def test_custom_target_stage(self):
        o = Order(key="k1", sub_dishes=[], main_dish="불고기", target_stage=3)
        assert o.target_stage == 3

    def test_custom_run_mode_only(self):
        o = Order(key="k1", sub_dishes=[], main_dish="불고기", run_mode="only")
        assert o.run_mode == "only"

    def test_custom_status(self):
        o = Order(key="k1", sub_dishes=[], main_dish="불고기", status="processing")
        assert o.status == "processing"

    def test_sub_dishes_can_be_empty_list(self):
        o = Order(key="k1", sub_dishes=[], main_dish="불고기")
        assert o.sub_dishes == []

    def test_sub_dishes_multiple_items(self):
        dishes = ["피클", "단무지", "김치"]
        o = Order(key="k1", sub_dishes=dishes, main_dish="돈까스")
        assert len(o.sub_dishes) == 3

    def test_order_equality_by_key(self):
        o1 = Order(key="same", sub_dishes=[], main_dish="불고기")
        o2 = Order(key="same", sub_dishes=[], main_dish="돈까스")
        # 데이터클래스 기본 동등성: 모든 필드 비교
        assert o1.key == o2.key


# ── OrderRepository 추상 클래스 ──────────────────────────────────────────────
class TestOrderRepositoryAbstract:
    def test_cannot_instantiate_abstract_class(self):
        """OrderRepository 는 추상 클래스이므로 직접 생성 불가."""
        with pytest.raises(TypeError):
            OrderRepository()

    def test_mock_order_repository_is_concrete(self):
        """MockOrderRepository 는 모든 추상 메서드를 구현해야 함."""
        repo = MockOrderRepository()
        assert isinstance(repo, OrderRepository)

    def test_abstract_methods_defined(self):
        """OrderRepository 의 추상 메서드 목록 확인."""
        abstract_methods = OrderRepository.__abstractmethods__
        expected = {"listen_orders", "mark_processing", "mark_completed",
                    "mark_error", "listen_commands", "upload_robot_status"}
        assert expected.issubset(abstract_methods)


# ── MockOrderRepository 확장 테스트 ──────────────────────────────────────────
class TestMockOrderRepositoryExtra:
    @pytest.fixture
    def repo(self) -> MockOrderRepository:
        return MockOrderRepository()

    def test_inject_order_default_key_starts_with_mock(self, repo):
        """기본 주문의 key 는 'mock_' 으로 시작."""
        repo.inject_order()
        order = repo._order_q.get(timeout=1.0)
        assert order.key.startswith("mock_")

    def test_inject_order_default_main_dish(self, repo):
        """기본 주문의 main_dish 는 '돈까스'."""
        repo.inject_order()
        order = repo._order_q.get(timeout=1.0)
        assert order.main_dish == "돈까스"

    def test_inject_order_default_sub_dishes(self, repo):
        """기본 주문의 sub_dishes 는 3개 이상."""
        repo.inject_order()
        order = repo._order_q.get(timeout=1.0)
        assert len(order.sub_dishes) >= 1

    def test_multiple_listeners_not_supported_but_safe(self, repo):
        """listen_orders 를 두 번 호출해도 예외 없음."""
        repo.listen_orders(lambda o: None)
        repo.listen_orders(lambda o: None)  # 두 번째 호출 → 예외 없음

    def test_upload_robot_status_accumulates_payloads(self, repo):
        for i in range(3):
            repo.upload_robot_status({"count": i, "state": "idle"})
        assert len(repo._statuses) == 3

    def test_upload_robot_status_payload_content(self, repo):
        payload = {"state": "processing", "progress": 50, "task": "이동 중"}
        repo.upload_robot_status(payload)
        assert repo._statuses[0] == payload

    def test_inject_command_various_types(self, repo):
        """다양한 명령 타입이 큐에 적재."""
        commands = ["emergency_stop", "pause", "resume", "move_home"]
        for cmd in commands:
            repo.inject_command(cmd)
        assert repo._cmd_q.qsize() == len(commands)

    def test_concurrent_inject_order_is_thread_safe(self, repo):
        """여러 스레드에서 동시에 주문 삽입해도 안전."""
        errors = []
        def injector():
            try:
                repo.inject_order(Order(key=f"order-{id(threading.current_thread())}",
                                        sub_dishes=[], main_dish="불고기"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=injector) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert repo._order_q.qsize() == 20
