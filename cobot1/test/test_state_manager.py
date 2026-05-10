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

    def test_collision_reflects_true_when_set(self, sm):
        sm.update_status(collision_detected=True)
        d = sm.get_status_dict()
        assert d["collision"] is True

    def test_gripper_value_is_string(self, sm):
        d = sm.get_status_dict()
        assert isinstance(d["gripper"], str)

    def test_last_update_is_float(self, sm):
        d = sm.get_status_dict()
        assert isinstance(d["last_update"], float)

    def test_step_log_empty_initially(self, sm):
        d = sm.get_status_dict()
        assert d["step_log"] == []


# ── 일시정지(pause/resume) 테스트 ─────────────────────────────────────────────
class TestPauseResume:
    def test_initial_not_paused(self, sm):
        """초기 상태에서 is_paused() == False."""
        assert not sm.is_paused()

    def test_set_pause_makes_is_paused_true(self, sm):
        sm.set_pause()
        assert sm.is_paused()

    def test_clear_pause_makes_is_paused_false(self, sm):
        sm.set_pause()
        sm.clear_pause()
        assert not sm.is_paused()

    def test_clear_pause_without_set_is_safe(self, sm):
        """set 없이 clear 해도 예외 없음."""
        sm.clear_pause()
        assert not sm.is_paused()

    def test_wait_if_paused_does_not_block_when_not_paused(self, sm):
        """일시정지 아닐 때 wait_if_paused() 는 즉시 반환."""
        import time
        t0 = time.monotonic()
        sm.wait_if_paused()
        elapsed = time.monotonic() - t0
        assert elapsed < 0.5  # 즉시 반환 확인

    def test_wait_if_paused_unblocks_after_clear(self, sm):
        """일시정지 중인 스레드가 clear_pause 후 재개되는지 확인."""
        import time
        sm.set_pause()
        results = []

        def waiter():
            sm.wait_if_paused()
            results.append("unblocked")

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        time.sleep(0.1)
        assert results == []  # 아직 블로킹 상태
        sm.clear_pause()
        t.join(timeout=2.0)
        assert results == ["unblocked"]

    def test_pause_resume_cycle(self, sm):
        """pause → clear → pause → clear 반복 정상 동작."""
        for _ in range(3):
            sm.set_pause()
            assert sm.is_paused()
            sm.clear_pause()
            assert not sm.is_paused()


# ── 열거형(Enum) 검증 테스트 ──────────────────────────────────────────────────
class TestEnumValues:
    def test_robot_state_idle_value(self):
        assert RobotState.IDLE.value == "idle"

    def test_robot_state_moving_value(self):
        assert RobotState.MOVING.value == "moving"

    def test_robot_state_processing_value(self):
        assert RobotState.PROCESSING.value == "processing"

    def test_robot_state_error_value(self):
        assert RobotState.ERROR.value == "error"

    def test_robot_state_emergency_stop_value(self):
        assert RobotState.EMERGENCY_STOP.value == "emergency_stop"

    def test_robot_state_has_5_members(self):
        assert len(RobotState) == 5

    def test_gripper_width_mm5_value(self):
        assert GripperWidth.MM5.value == "5mm"

    def test_gripper_width_mm100_value(self):
        assert GripperWidth.MM100.value == "100mm"

    def test_gripper_width_has_5_members(self):
        assert len(GripperWidth) == 5


# ── RobotStatus 기본값 테스트 ───────────────────────────────────────────────
class TestRobotStatusDefaults:
    def test_default_gripper_is_mm100(self, sm):
        """초기 그리퍼는 완전 열린 상태 (100mm)."""
        assert sm.status.gripper == GripperWidth.MM100

    def test_default_joint_pos_is_6_zeros(self, sm):
        assert sm.status.joint_pos == [0.0] * 6

    def test_default_current_task(self, sm):
        assert sm.status.current_task == "대기 중"

    def test_default_collision_false(self, sm):
        assert sm.status.collision_detected is False

    def test_update_gripper_via_update_status(self, sm):
        sm.update_status(gripper=GripperWidth.MM5)
        assert sm.status.gripper == GripperWidth.MM5

    def test_update_joint_pos(self, sm):
        new_pos = [10.0, 20.0, 30.0, 0.0, 90.0, 0.0]
        sm.update_status(joint_pos=new_pos)
        assert sm.status.joint_pos == new_pos


# ── StepLog 데이터클래스 테스트 ─────────────────────────────────────────────
class TestStepLogDataclass:
    def test_step_log_has_timestamp(self, sm):
        sm.add_step_log("단계 테스트", completed=True)
        log = sm.status.step_log[0]
        assert isinstance(log.timestamp, float)
        assert log.timestamp > 0

    def test_step_log_completed_field(self, sm):
        sm.add_step_log("완료 단계", completed=True)
        log = sm.status.step_log[0]
        assert log.completed is True

    def test_step_log_in_progress_field(self, sm):
        sm.add_step_log("진행 중 단계", completed=False)
        log = sm.status.step_log[0]
        assert log.completed is False

    def test_step_log_thread_safe_add(self, sm):
        """여러 스레드에서 동시에 add_step_log 해도 충돌 없음."""
        errors = []

        def adder(i):
            try:
                sm.add_step_log(f"step {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=adder, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(sm.status.step_log) <= sm.MAX_LOG
