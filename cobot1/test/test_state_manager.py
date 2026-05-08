"""
test_state_manager.py
RobotStateManager 단위 테스트.
- 상태 업데이트 스레드 안전성
- 비상정지 이벤트
- 중복 주문 방지
- 로그 최대 개수 유지
- 직렬화 dict 구조
"""
import threading
import time
import pytest

from cobot1.state_manager import (
    RobotStateManager,
    RobotState,
    GripperWidth,
    StepLog,
)


# ── 픽스처 ──────────────────────────────────────────────────────────────────
@pytest.fixture
def sm() -> RobotStateManager:
    return RobotStateManager()


# ── 초기 상태 테스트 ─────────────────────────────────────────────────────────
class TestInitialState:
    def test_initial_state_is_idle(self, sm):
        assert sm.status.state == RobotState.IDLE

    def test_initial_emergency_stop_clear(self, sm):
        assert not sm.is_stopped()

    def test_initial_progress_zero(self, sm):
        assert sm.status.progress == 0

    def test_initial_step_log_empty(self, sm):
        assert sm.status.step_log == []


# ── update_status 테스트 ────────────────────────────────────────────────────
class TestUpdateStatus:
    def test_update_single_field(self, sm):
        sm.update_status(state=RobotState.MOVING)
        assert sm.status.state == RobotState.MOVING

    def test_update_multiple_fields(self, sm):
        sm.update_status(state=RobotState.PROCESSING, current_task="테스트 중", progress=50)
        assert sm.status.state == RobotState.PROCESSING
        assert sm.status.current_task == "테스트 중"
        assert sm.status.progress == 50

    def test_unknown_field_is_ignored(self, sm):
        """존재하지 않는 필드는 조용히 무시해야 함."""
        sm.update_status(nonexistent_field="값")  # AttributeError 없음

    def test_last_update_is_refreshed(self, sm):
        before = sm.status.last_update
        time.sleep(0.01)
        sm.update_status(state=RobotState.IDLE)
        assert sm.status.last_update > before

    def test_thread_safe_concurrent_updates(self, sm):
        """다수 스레드가 동시에 update_status 해도 충돌 없음."""
        errors = []

        def updater(i):
            try:
                sm.update_status(progress=i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"스레드 충돌 발생: {errors}"


# ── add_step_log 테스트 ─────────────────────────────────────────────────────
class TestAddStepLog:
    def test_log_added(self, sm):
        sm.add_step_log("1단계 완료", completed=True)
        assert len(sm.status.step_log) == 1

    def test_completed_prefix(self, sm):
        sm.add_step_log("완료됨", completed=True)
        assert sm.status.step_log[0].message.startswith("✅")

    def test_in_progress_prefix(self, sm):
        sm.add_step_log("진행 중", completed=False)
        assert sm.status.step_log[0].message.startswith("🔄")

    def test_max_log_enforced(self, sm):
        for i in range(sm.MAX_LOG + 5):
            sm.add_step_log(f"step {i}")
        assert len(sm.status.step_log) == sm.MAX_LOG

    def test_oldest_log_dropped_on_overflow(self, sm):
        for i in range(sm.MAX_LOG + 1):
            sm.add_step_log(f"step {i}")
        # 가장 오래된 "step 0" 이 사라지고 "step 1" 이 첫 번째여야 함
        assert "step 0" not in sm.status.step_log[0].message
        assert "step 1" in sm.status.step_log[0].message


# ── reset_progress 테스트 ───────────────────────────────────────────────────
class TestResetProgress:
    def test_resets_all_fields(self, sm):
        sm.update_status(progress=80, current_step="7단계")
        sm.add_step_log("임시 로그")
        sm.reset_progress(total=10)
        assert sm.status.progress == 0
        assert sm.status.step_index == 0
        assert sm.status.total_steps == 10
        assert sm.status.current_step == ""
        assert sm.status.step_log == []


# ── tick 테스트 ─────────────────────────────────────────────────────────────
class TestTick:
    def test_tick_increases_step_index(self, sm):
        sm.reset_progress(total=10)
        sm.tick("1단계")
        assert sm.status.step_index == 1

    def test_tick_calculates_progress_pct(self, sm):
        sm.reset_progress(total=10)
        for _ in range(5):
            sm.tick()
        assert sm.status.progress == 50

    def test_tick_caps_at_99(self, sm):
        """완료 전 최대 99%까지만 증가."""
        sm.reset_progress(total=10)
        for _ in range(10):
            sm.tick()
        assert sm.status.progress == 99

    def test_tick_does_not_exceed_total(self, sm):
        """step_index 가 total_steps 를 초과하지 않아야 함."""
        sm.reset_progress(total=3)
        for _ in range(10):  # 총 스텝보다 많이 tick
            sm.tick()
        assert sm.status.step_index == 3


# ── 비상정지 테스트 ─────────────────────────────────────────────────────────
class TestEmergencyStop:
    def test_trigger_sets_event(self, sm):
        sm.trigger_emergency_stop()
        assert sm.is_stopped()

    def test_trigger_changes_state_to_emergency(self, sm):
        sm.trigger_emergency_stop()
        assert sm.status.state == RobotState.EMERGENCY_STOP

    def test_clear_unsets_event(self, sm):
        sm.trigger_emergency_stop()
        sm.clear_emergency_stop()
        assert not sm.is_stopped()

    def test_clear_changes_state_to_idle(self, sm):
        sm.trigger_emergency_stop()
        sm.clear_emergency_stop()
        assert sm.status.state == RobotState.IDLE

    def test_is_stopped_false_initially(self, sm):
        assert sm.is_stopped() is False


# ── 중복 주문 방지 테스트 ───────────────────────────────────────────────────
class TestOrderDeduplication:
    def test_mark_and_check_processed(self, sm):
        sm.mark_order_processed("order-001")
        assert sm.is_order_processed("order-001")

    def test_unknown_order_not_processed(self, sm):
        assert not sm.is_order_processed("unknown-key")

    def test_multiple_orders(self, sm):
        sm.mark_order_processed("a")
        sm.mark_order_processed("b")
        assert sm.is_order_processed("a")
        assert sm.is_order_processed("b")
        assert not sm.is_order_processed("c")

    def test_thread_safe_deduplication(self, sm):
        """여러 스레드에서 동시 mark 해도 충돌 없음."""
        errors = []
        def marker(key):
            try:
                sm.mark_order_processed(key)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=marker, args=(f"order-{i}",)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ── get_status_dict 직렬화 테스트 ───────────────────────────────────────────
class TestGetStatusDict:
    def test_returns_dict(self, sm):
        d = sm.get_status_dict()
        assert isinstance(d, dict)

    def test_required_keys_present(self, sm):
        keys = {"state", "current_task", "gripper", "joint_pos",
                "progress", "step_index", "total_steps",
                "current_step", "step_log", "last_update", "collision"}
        d = sm.get_status_dict()
        assert keys.issubset(d.keys())

    def test_state_is_string(self, sm):
        d = sm.get_status_dict()
        assert isinstance(d["state"], str)

    def test_step_log_is_list_of_strings(self, sm):
        sm.add_step_log("테스트")
        d = sm.get_status_dict()
        assert isinstance(d["step_log"], list)
        assert isinstance(d["step_log"][0], str)

    def test_joint_pos_is_list(self, sm):
        d = sm.get_status_dict()
        assert isinstance(d["joint_pos"], list)
