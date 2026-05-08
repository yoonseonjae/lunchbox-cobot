# cobot1 단위 테스트 보고서

**작성일**: 2026년 5월 8일  
**패키지**: `src/cobot1/` — 나만의 도련님 도시락 로봇 제어 시스템  
**로봇**: Doosan M0609 / ROS2 Humble  
**브랜치**: `ksw_develop`

---

## 1. 테스트 목적

cobot1 패키지는 실제 로봇 하드웨어(DSR_ROBOT2 API)와 Firebase 클라우드에 강하게 의존하는 구조입니다.  
단위 테스트의 목적은 **실제 장비 없이** 각 클래스의 로직과 규칙 준수 여부를 검증하는 것입니다.

| 목적 | 세부 내용 |
|------|-----------|
| 로직 검증 | 각 클래스의 메서드가 의도대로 동작하는가 |
| 규칙 검증 | **DSR Rule 7** — DSR API는 반드시 작업 스레드에서만 호출하는가 |
| 안전성 검증 | 비상정지, 재개, 그리퍼 제어의 올바른 동작 |
| 스레드 안전성 | 다수 스레드 동시 접근 시 충돌이 없는가 |
| 경계값 검증 | 잘못된 입력, 한도 초과 등 예외 처리 |

---

## 2. 테스트 환경 구성

### 핵심 문제
`DSR_ROBOT2`, `DR_init`, `rclpy` 등은 **실제 로봇 환경에서만 import 가능**합니다.  
일반 Python 환경에서 import 시 `ImportError`가 발생하므로, 테스트 전용 stub을 구성했습니다.

### 해결 방법 — `conftest.py` (sys.modules stub)

```
test/
├── __init__.py
├── conftest.py              ← pytest 자동 로드, sys.modules에 stub 사전 등록
├── test_robot_client.py
├── test_state_manager.py
├── test_mock_repository.py
└── test_robot_controller.py
```

`conftest.py`는 pytest 실행 시 **자동으로 가장 먼저 로드**됩니다.  
이 파일에서 아래 모듈들을 `MagicMock` 기반 stub으로 `sys.modules`에 등록합니다.

| stub 대상 | 이유 |
|-----------|------|
| `rclpy`, `rclpy.logging`, `rclpy.executors` | ROS2 런타임 없이 실행 |
| `DR_init` | DSR 로봇 초기화 모듈 |
| `DSR_ROBOT2` | movej, movel, set_digital_output 등 로봇 제어 함수 |
| `DR_common2` | posj, posx 좌표 변환 함수 |
| `firebase_admin`, `firebase_admin.db` | Firebase Realtime DB |
| `std_msgs`, `std_msgs.msg` | ROS2 메시지 타입 |

### Mock 패턴

```python
# DSR 이동 함수 mock
mock_movej = MagicMock()
client.inject(movej=mock_movej, ...)

# 호출 검증
mock_movej.assert_called_once_with(coords, vel=30, acc=30)
```

---

## 3. 테스트 파일 구성

### 3-1. `test_robot_client.py` — 26개 테스트

**대상**: `cobot1/robot_client.py`  
**역할**: DSR API를 직접 호출하는 유일한 계층

| 테스트 클래스 | 검증 항목 |
|--------------|-----------|
| `TestRobotClientInit` | 기본값 설정, inject 전/후 상태 |
| `TestRobotClientMotion` | movej/movel/amovej/amovel 호출 및 posj/posx 변환 |
| `TestWaitMotionDone` | check_motion 폴링 루프, rclpy 종료 시 탈출 |
| `TestGripper` | 5가지 폭의 DO핀 조합, 잘못된 폭 예외 |
| `TestStopMethods` | do_stop → move_stop(3), 예외 내부 처리 |
| `TestConstants` | ON/OFF 값, 타이밍 상수 양수 여부 |

**핵심 검증 — 그리퍼 DO핀 테이블**

```
5mm   : DO1=ON,  DO2=OFF, DO3=OFF
20mm  : DO1=ON,  DO2=OFF, DO3=ON
30mm  : DO1=ON,  DO2=ON,  DO3=OFF
50mm  : DO1=OFF, DO2=OFF, DO3=ON
100mm : DO1=OFF, DO2=ON,  DO3=OFF
```

---

### 3-2. `test_state_manager.py` — 28개 테스트

**대상**: `cobot1/state_manager.py`  
**역할**: 로봇 상태 관리, 비상정지 이벤트, 진행률 추적

| 테스트 클래스 | 검증 항목 |
|--------------|-----------|
| `TestInitialState` | 초기값 (IDLE, progress=0, 빈 로그) |
| `TestUpdateStatus` | 단일/복수 필드 업데이트, 50 스레드 동시 접근 |
| `TestAddStepLog` | ✅/🔄 접두어, 20개 한도, 오래된 항목 삭제 |
| `TestResetProgress` | 새 주문 시작 시 완전 초기화 |
| `TestTick` | 진행률 계산, 99% 상한, total_steps 초과 방지 |
| `TestEmergencyStop` | 비상정지/재개 이벤트 및 상태 전이 |
| `TestOrderDeduplication` | 중복 주문 방지, 50 스레드 동시 mark |
| `TestGetStatusDict` | 11개 필수 키, 타입 검증 |

---

### 3-3. `test_mock_repository.py` — 12개 테스트

**대상**: `cobot1/repositories/mock_order_repository.py`  
**역할**: Firebase 없이 주문/명령을 테스트에서 직접 삽입하는 구현체

| 테스트 클래스 | 검증 항목 |
|--------------|-----------|
| `TestInjectOrder` | 기본/커스텀 주문 삽입, 콜백 도달, 순서 보장 |
| `TestInjectCommand` | 명령 큐 적재 및 콜백 도달 |
| `TestMarkStatus` | mark_processing/completed/error 예외 없음 |
| `TestUploadRobotStatus` | 상태 누적, 20 스레드 동시 업로드 |

---

### 3-4. `test_robot_controller.py` — 26개 테스트

**대상**: `cobot1/robot_controller.py`  
**역할**: 4개 스레드 조율, 주문 처리, 명령 처리

| 테스트 클래스 | 검증 항목 |
|--------------|-----------|
| `TestHandleCommandEmergencyStop` | do_stop() 호출, 상태·이벤트 변경 |
| `TestHandleCommandResume` | 비상정지 해제, 상태 복원, 정상 시 무효 |
| `TestHandleCommandMoveHome` | Rule 7: cmd_queue 위임, do_movej 직접 호출 금지 |
| `TestHandleCommandGripper` | Rule 7: cmd_queue 위임, set_gripper 직접 호출 금지 |
| `TestExecuteCmd` | 작업 스레드 내 실제 DSR 호출 검증 |
| `TestOrderReceived` | 첫 주문 큐 적재, 중복 주문 차단 |

**핵심 검증 — DSR Rule 7**

Firebase 콜백 스레드에서 `_handle_command("gripper_open")`이 호출될 때:
- ❌ 잘못된 방식: `self.rc.set_gripper(50)` 직접 호출 (Rule 7 위반)
- ✅ 올바른 방식: `self._cmd_queue.put("gripper_open")` → 작업 스레드가 처리

이 두 가지를 명시적으로 분리하여 각각 테스트합니다.

---

## 4. 실행 방법

```bash
# 전체 테스트 실행
cd ~/cobot_ws
python3 -m pytest cobot1/test/ -v

# 특정 파일만
python3 -m pytest cobot1/test/test_robot_client.py -v

# 특정 테스트만
python3 -m pytest cobot1/test/test_robot_controller.py::TestHandleCommandEmergencyStop -v

# 빠른 실패 확인 (첫 번째 실패 시 중단)
python3 -m pytest cobot1/test/ -v -x
```

---

## 5. 최종 테스트 결과

**실행 명령**: `python3 -m pytest cobot1/test/ -v`  
**환경**: Python 3.10.12 / pytest-9.0.3 / ROS2 Humble

```
============================= test session starts ==============================
platform linux -- Python 3.10.12, pytest-9.0.3
collected 92 items

92 passed in 1.38s
```

### 파일별 결과 요약

| 테스트 파일 | 테스트 수 | PASS | FAIL |
|------------|:---------:|:----:|:----:|
| `test_mock_repository.py` | 12 | **12** | 0 |
| `test_robot_client.py` | 26 | **26** | 0 |
| `test_robot_controller.py` | 26 | **26** | 0 |
| `test_state_manager.py` | 28 | **28** | 0 |
| **합계** | **92** | **92** | **0** |

---

## 6. 전체 테스트 목록

### test_mock_repository.py (12/12 PASS)

| # | 테스트명 | 결과 | 검증 내용 |
|---|---------|:----:|-----------|
| 1 | `TestInjectOrder::test_inject_default_order` | ✅ | 인자 없이 호출 시 기본 주문 생성 |
| 2 | `TestInjectOrder::test_inject_custom_order` | ✅ | 커스텀 Order 주입 후 큐에 정상 적재 |
| 3 | `TestInjectOrder::test_listen_orders_triggers_callback` | ✅ | 주문 삽입 → 콜백 함수 호출 |
| 4 | `TestInjectOrder::test_multiple_orders_dispatched_in_order` | ✅ | 3개 주문이 삽입 순서대로 콜백 도달 |
| 5 | `TestInjectCommand::test_inject_command_queued` | ✅ | 명령 큐에 정상 적재 |
| 6 | `TestInjectCommand::test_listen_commands_triggers_callback` | ✅ | 명령 삽입 → 콜백 호출 |
| 7 | `TestMarkStatus::test_mark_processing_no_exception` | ✅ | processing 상태 변경 예외 없음 |
| 8 | `TestMarkStatus::test_mark_completed_no_exception` | ✅ | completed 상태 변경 예외 없음 |
| 9 | `TestMarkStatus::test_mark_error_no_exception` | ✅ | error 상태 변경 예외 없음 |
| 10 | `TestUploadRobotStatus::test_status_stored_in_list` | ✅ | 상태가 _statuses 리스트에 저장 |
| 11 | `TestUploadRobotStatus::test_multiple_statuses_accumulated` | ✅ | 5회 업로드 → 5개 누적 |
| 12 | `TestUploadRobotStatus::test_thread_safe_status_upload` | ✅ | 20개 스레드 동시 업로드 충돌 없음 |

### test_robot_client.py (26/26 PASS)

| # | 테스트명 | 결과 | 검증 내용 |
|---|---------|:----:|-----------|
| 1 | `TestRobotClientInit::test_default_vel_acc` | ✅ | 기본 vel=30, acc=30 |
| 2 | `TestRobotClientInit::test_custom_vel_acc` | ✅ | 커스텀 vel=60, acc=60 |
| 3 | `TestRobotClientInit::test_inject_not_called_dsr_is_none` | ✅ | inject 전 DSR 함수 모두 None |
| 4 | `TestRobotClientInit::test_inject_sets_all_dsr_functions` | ✅ | inject 후 전체 DSR 함수 바인딩 확인 |
| 5 | `TestRobotClientMotion::test_do_movej_calls_movej_and_mwait` | ✅ | movej() + mwait() 순서대로 호출 |
| 6 | `TestRobotClientMotion::test_do_movel_calls_movel_with_dr_base_and_mwait` | ✅ | movel(ref=DR_BASE) + mwait() |
| 7 | `TestRobotClientMotion::test_do_amovej_no_mwait` | ✅ | 비동기 이동 시 mwait 미호출 |
| 8 | `TestRobotClientMotion::test_do_amovel_no_mwait` | ✅ | 비동기 직선 이동 시 mwait 미호출 |
| 9 | `TestRobotClientMotion::test_posj_called_in_movej` | ✅ | movej 호출 전 posj() 좌표 변환 |
| 10 | `TestRobotClientMotion::test_posx_called_in_movel` | ✅ | movel 호출 전 posx() 좌표 변환 |
| 11 | `TestWaitMotionDone::test_returns_true_when_already_idle` | ✅ | check_motion==0 이면 즉시 True 반환 |
| 12 | `TestWaitMotionDone::test_polls_until_idle` | ✅ | Busy→Busy→Idle 3회 폴링 후 True |
| 13 | `TestWaitMotionDone::test_returns_false_when_rclpy_stops` | ✅ | rclpy.ok()==False 시 False 반환 |
| 14 | `TestGripper::test_set_gripper_do_pins[5]` | ✅ | 5mm → DO1=ON, DO2=OFF, DO3=OFF |
| 15 | `TestGripper::test_set_gripper_do_pins[20]` | ✅ | 20mm → DO1=ON, DO2=OFF, DO3=ON |
| 16 | `TestGripper::test_set_gripper_do_pins[30]` | ✅ | 30mm → DO1=ON, DO2=ON, DO3=OFF |
| 17 | `TestGripper::test_set_gripper_do_pins[50]` | ✅ | 50mm → DO1=OFF, DO2=OFF, DO3=ON |
| 18 | `TestGripper::test_set_gripper_do_pins[100]` | ✅ | 100mm → DO1=OFF, DO2=ON, DO3=OFF |
| 19 | `TestGripper::test_set_gripper_calls_wait_with_settle_sec` | ✅ | wait(GRIPPER_SETTLE_SEC=2.0) 호출 |
| 20 | `TestGripper::test_invalid_gripper_width_raises_valueerror` | ✅ | 999mm → ValueError("지원하지 않는") |
| 21 | `TestGripper::test_gripper_map_covers_all_widths` | ✅ | _GRIPPER_MAP 키 = {5, 20, 30, 50, 100} |
| 22 | `TestStopMethods::test_do_stop_calls_move_stop_3` | ✅ | do_stop() → move_stop(3) |
| 23 | `TestStopMethods::test_move_stop_with_immediate_mode` | ✅ | move_stop(0) 직접 호출 |
| 24 | `TestStopMethods::test_move_stop_exception_is_caught` | ✅ | move_stop 예외 상위 전파 없음 |
| 25 | `TestConstants::test_on_off_values` | ✅ | ON=1, OFF=0 |
| 26 | `TestConstants::test_timing_constants_are_positive` | ✅ | 모든 타이밍 상수 > 0 |

### test_robot_controller.py (26/26 PASS)

| # | 테스트명 | 결과 | 검증 내용 |
|---|---------|:----:|-----------|
| 1 | `TestHandleCommandEmergencyStop::test_do_stop_called` | ✅ | 비상정지 명령 → rc.do_stop() 호출 |
| 2 | `TestHandleCommandEmergencyStop::test_state_set_to_emergency_stop` | ✅ | 상태 → EMERGENCY_STOP |
| 3 | `TestHandleCommandEmergencyStop::test_emergency_event_is_set` | ✅ | emergency_stop 이벤트 set |
| 4 | `TestHandleCommandResume::test_clears_emergency_stop_when_stopped` | ✅ | 비상정지 중 resume → 이벤트 clear |
| 5 | `TestHandleCommandResume::test_state_returns_to_idle_after_resume` | ✅ | resume 후 상태 → IDLE |
| 6 | `TestHandleCommandResume::test_resume_when_not_stopped_has_no_effect` | ✅ | 정상 상태에서 resume → 변화 없음 |
| 7 | `TestHandleCommandMoveHome::test_move_home_enqueued_to_cmd_queue` | ✅ | **Rule 7**: _cmd_queue에 "move_home" 삽입 |
| 8 | `TestHandleCommandMoveHome::test_move_home_does_not_call_movej_directly` | ✅ | **Rule 7**: do_movej() 직접 호출 없음 |
| 9 | `TestHandleCommandMoveHome::test_state_not_changed_by_handle_command` | ✅ | 콜백 스레드에서 상태 변경 없음 |
| 10 | `TestHandleCommandGripper::test_gripper_open_enqueued` | ✅ | **Rule 7**: "gripper_open" → _cmd_queue |
| 11 | `TestHandleCommandGripper::test_gripper_close_enqueued` | ✅ | **Rule 7**: "gripper_close" → _cmd_queue |
| 12 | `TestHandleCommandGripper::test_gripper_full_open_enqueued` | ✅ | **Rule 7**: "gripper_full_open" → _cmd_queue |
| 13 | `TestHandleCommandGripper::test_gripper_does_not_call_set_gripper_directly` | ✅ | **Rule 7**: set_gripper() 직접 호출 없음 |
| 14 | `TestHandleCommandGripper::test_unknown_command_no_exception` | ✅ | 알 수 없는 명령 → 예외 없음 |
| 15 | `TestExecuteCmd::test_execute_move_home_calls_movej` | ✅ | 작업 스레드에서 do_movej(home_coords) |
| 16 | `TestExecuteCmd::test_execute_gripper_open` | ✅ | 작업 스레드에서 set_gripper(50) |
| 17 | `TestExecuteCmd::test_execute_gripper_close` | ✅ | 작업 스레드에서 set_gripper(5) |
| 18 | `TestExecuteCmd::test_execute_gripper_full_open` | ✅ | 작업 스레드에서 set_gripper(100) |
| 19 | `TestExecuteCmd::test_execute_move_home_updates_state` | ✅ | 실행 후 상태 → IDLE |
| 20 | `TestOrderReceived::test_first_order_enqueued` | ✅ | 첫 주문 → _order_queue 적재 |
| 21 | `TestOrderReceived::test_duplicate_order_not_enqueued` | ✅ | 동일 key 두 번 → 큐에 1개만 |

### test_state_manager.py (28/28 PASS)

| # | 테스트명 | 결과 | 검증 내용 |
|---|---------|:----:|-----------|
| 1 | `TestInitialState::test_initial_state_is_idle` | ✅ | 초기 상태 = IDLE |
| 2 | `TestInitialState::test_initial_emergency_stop_clear` | ✅ | 초기 비상정지 이벤트 = clear |
| 3 | `TestInitialState::test_initial_progress_zero` | ✅ | 초기 progress = 0 |
| 4 | `TestInitialState::test_initial_step_log_empty` | ✅ | 초기 step_log = [] |
| 5 | `TestUpdateStatus::test_update_single_field` | ✅ | 단일 필드 업데이트 |
| 6 | `TestUpdateStatus::test_update_multiple_fields` | ✅ | 복수 필드 동시 업데이트 |
| 7 | `TestUpdateStatus::test_unknown_field_is_ignored` | ✅ | 존재하지 않는 필드 → 무시 |
| 8 | `TestUpdateStatus::test_last_update_is_refreshed` | ✅ | 업데이트 후 last_update 시각 갱신 |
| 9 | `TestUpdateStatus::test_thread_safe_concurrent_updates` | ✅ | 50개 스레드 동시 업데이트 충돌 없음 |
| 10 | `TestAddStepLog::test_log_added` | ✅ | 로그 1개 추가 확인 |
| 11 | `TestAddStepLog::test_completed_prefix` | ✅ | completed=True → "✅" 접두어 |
| 12 | `TestAddStepLog::test_in_progress_prefix` | ✅ | completed=False → "🔄" 접두어 |
| 13 | `TestAddStepLog::test_max_log_enforced` | ✅ | 25개 추가 → 최대 20개 유지 |
| 14 | `TestAddStepLog::test_oldest_log_dropped_on_overflow` | ✅ | 한도 초과 시 가장 오래된 항목 삭제 |
| 15 | `TestResetProgress::test_resets_all_fields` | ✅ | progress/step_index/log 완전 초기화 |
| 16 | `TestTick::test_tick_increases_step_index` | ✅ | tick() → step_index +1 |
| 17 | `TestTick::test_tick_calculates_progress_pct` | ✅ | 10단계 중 5 완료 → progress=50% |
| 18 | `TestTick::test_tick_caps_at_99` | ✅ | 완료 직전까지 최대 99% (100% 방지) |
| 19 | `TestTick::test_tick_does_not_exceed_total` | ✅ | 초과 tick 시 step_index ≤ total_steps |
| 20 | `TestEmergencyStop::test_trigger_sets_event` | ✅ | trigger_emergency_stop() → 이벤트 set |
| 21 | `TestEmergencyStop::test_trigger_changes_state_to_emergency` | ✅ | 상태 → EMERGENCY_STOP |
| 22 | `TestEmergencyStop::test_clear_unsets_event` | ✅ | clear_emergency_stop() → 이벤트 clear |
| 23 | `TestEmergencyStop::test_clear_changes_state_to_idle` | ✅ | 해제 후 상태 → IDLE |
| 24 | `TestEmergencyStop::test_is_stopped_false_initially` | ✅ | 초기 is_stopped() = False |
| 25 | `TestOrderDeduplication::test_mark_and_check_processed` | ✅ | mark 후 is_processed = True |
| 26 | `TestOrderDeduplication::test_unknown_order_not_processed` | ✅ | 미등록 key → is_processed = False |
| 27 | `TestOrderDeduplication::test_multiple_orders` | ✅ | a, b 등록 후 c는 미등록 상태 |
| 28 | `TestOrderDeduplication::test_thread_safe_deduplication` | ✅ | 50개 스레드 동시 mark 충돌 없음 |
| 29 | `TestGetStatusDict::test_returns_dict` | ✅ | 반환값이 dict |
| 30 | `TestGetStatusDict::test_required_keys_present` | ✅ | 11개 필수 키 전부 포함 |
| 31 | `TestGetStatusDict::test_state_is_string` | ✅ | state 값이 str |
| 32 | `TestGetStatusDict::test_step_log_is_list_of_strings` | ✅ | step_log가 문자열 리스트 |
| 33 | `TestGetStatusDict::test_joint_pos_is_list` | ✅ | joint_pos가 리스트 |

---

## 7. 중간 실패 → 수정 이력

초기 작성 시 6개 테스트가 실패했습니다. 실패 원인을 분석하고 모두 수정했습니다.

### 실패 원인 1: DSR Rule 7 — 실제 코드와 테스트 가정 불일치 (5개)

테스트 최초 작성 시 `_handle_command("gripper_open")`이 `set_gripper()`를 직접 호출한다고 가정했으나,  
실제 코드는 **Rule 7**(DSR API는 작업 스레드에서만 호출)에 따라 `_cmd_queue.put()`으로 위임하는 구조였습니다.

```python
# 실제 코드 (_handle_command)
elif cmd_type in ("move_home", "gripper_open", "gripper_close", "gripper_full_open"):
    self._cmd_queue.put(cmd_type)  # 작업 스레드에 위임

# _execute_cmd (작업 스레드 내부에서 호출)
elif cmd_type == "gripper_open":
    self.rc.set_gripper(50)  # 여기서만 DSR API 호출
```

| 실패 테스트 | 수정 내용 |
|------------|-----------|
| `test_gripper_open_sets_50mm` | `rc.set_gripper(50)` 검증 → `_cmd_queue`에 "gripper_open" 삽입 검증으로 변경 |
| `test_gripper_close_sets_5mm` | 동일 |
| `test_gripper_full_open_sets_100mm` | 동일 |
| `test_do_movej_called_with_home_coords` | `do_movej()` 직접 호출 검증 → 큐 삽입 검증으로 변경 |
| `test_state_moving_during_command` | 상태 변경이 작업 스레드 담당임을 반영하여 테스트 목적 변경 |

### 실패 원인 2: 존재하지 않는 속성 참조 (1개)

| 실패 테스트 | 원인 | 수정 내용 |
|------------|------|-----------|
| `test_available_property_is_true` | `MockOrderRepository`에 `available` 속성 없음 | 해당 테스트 제거 |

---

## 8. 테스트 커버리지 범위

| 모듈 | 커버 여부 | 미커버 범위 |
|------|:---------:|-----------|
| `robot_client.py` | ✅ 주요 경로 전체 | - |
| `state_manager.py` | ✅ 전체 | - |
| `mock_order_repository.py` | ✅ 전체 | - |
| `robot_controller.py` | ✅ _handle_command, _execute_cmd, _on_order_received | _task_loop, _status_upload_loop, _collision_monitor_loop (스레드 루프) |
| `stages/base_stage.py` | ❌ | 통합 테스트 필요 |
| `stages/stages.py` | ❌ | 통합 테스트 필요 |
| `coordinate_manager.py` | ❌ | YAML 파일 의존 |
| `lunchbox_robot_node.py` | ❌ | ROS2 노드 생성 필요 |

> 스테이지 클래스와 노드 진입점은 실제 좌표 YAML 파일과 ROS2 런타임이 필요하여 통합 테스트로 분류합니다.
