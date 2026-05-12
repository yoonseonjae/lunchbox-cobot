# cobot1 단위 테스트 보고서

**작성일**: 2026년 5월 12일  
**패키지**: `src/cobot1/` — 나만의 도련님 도시락 로봇 제어 시스템  
**로봇**: Doosan M0609 / ROS2 Humble  
**브랜치**: `main`

---

## 1. 테스트 목적

cobot1 패키지는 실제 로봇 하드웨어(DSR_ROBOT2 API)와 Firebase 클라우드에 강하게 의존하는 구조입니다.  
단위 테스트의 목적은 **실제 장비 없이** 각 클래스의 로직과 규칙 준수 여부를 검증하는 것입니다.

| 목적 | 세부 내용 |
|------|-----------|
| 로직 검증 | 각 클래스의 메서드가 의도대로 동작하는가 |
| 규칙 검증 | **DSR Rule 7** — DSR API는 반드시 작업 스레드에서만 호출하는가 |
| 안전성 검증 | 비상정지·일시정지·재개·그리퍼 제어의 올바른 동작 |
| 스레드 안전성 | 다수 스레드 동시 접근 시 충돌이 없는가 |
| 경계값 검증 | 잘못된 입력, 한도 초과 등 예외 처리 |
| 도메인 모델 | Order 데이터클래스 필드 및 OrderRepository 인터페이스 |

---

## 2. 테스트 환경 구성

### 핵심 문제
`DSR_ROBOT2`, `DR_init`, `rclpy`, `dsr_msgs2` 등은 **실제 로봇 환경에서만 import 가능**합니다.  
일반 Python 환경에서 import 시 `ImportError`가 발생하므로, 테스트 전용 stub을 구성했습니다.

### 해결 방법 — `conftest.py` (sys.modules stub)

```
test/
├── __init__.py
├── conftest.py              ← pytest 자동 로드, sys.modules에 stub 사전 등록
├── test_mock_repository.py
├── test_order_model.py      ← 2026-05-09 신규 추가
├── test_robot_client.py
├── test_robot_controller.py
└── test_state_manager.py
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
| `dsr_msgs2`, `dsr_msgs2.srv` | DSR 서비스 타입 (2026-05-09 추가) |

### Mock 패턴

```python
# DSR 이동 함수 mock
mock_movej = MagicMock()
client.inject(movej=mock_movej, ...)

# 호출 검증
mock_movej.assert_called_once_with(coords, vel=30, acc=30, radius=None)
```

---

## 3. 테스트 파일 구성

### 3-1. `test_robot_client.py` — 46개 테스트

**대상**: `cobot1/robot_client.py`  
**역할**: DSR API를 직접 호출하는 유일한 계층

| 테스트 클래스 | 검증 항목 |
|--------------|-----------|
| `TestRobotClientInit` | 기본값 설정, inject 전/후 상태 |
| `TestRobotClientMotion` | movej/movel/amovej/amovel 호출 및 posj/posx 변환, radius 파라미터 |
| `TestWaitMotionDone` | check_motion 폴링 루프 |
| `TestGripper` | 5가지 폭의 DO핀 조합, 잘못된 폭 무시 |
| `TestStopMethods` | do_stop → move_stop(3), inject 전 안전 호출 |
| `TestConstants` | ON/OFF 값, 타이밍 상수 양수 여부 |
| `TestCheckGrip` | DI1 핀 기반 파지 확인, 예외 시 True 반환 |
| `TestGetRobotState` | DSR 위임, inject 전 기본값 1 |
| `TestGetForce` | get_tool_force/get_external_torque 반환값 형식 |
| `TestMotionWithRadius` | radius 파라미터 DSR 전달 확인 |
| `TestDoMovePeriodic` (신규) | move_periodic DSR 전달, inject 전 안전 리턴, 인수별 전달 확인 |

**핵심 검증 — 그리퍼 DO핀 테이블**

```
5mm   : DO1=ON,  DO2=OFF, DO3=OFF
20mm  : DO1=ON,  DO2=OFF, DO3=ON
30mm  : DO1=ON,  DO2=ON,  DO3=OFF
50mm  : DO1=OFF, DO2=OFF, DO3=ON
100mm : DO1=OFF, DO2=ON,  DO3=OFF
```

---

### 3-2. `test_state_manager.py` — 63개 테스트

**대상**: `cobot1/state_manager.py`  
**역할**: 로봇 상태 관리, 비상정지·일시정지 이벤트, 진행률 추적

| 테스트 클래스 | 검증 항목 |
|--------------|-----------|
| `TestInitialState` | 초기값 (IDLE, progress=0, 빈 로그) |
| `TestUpdateStatus` | 단일/복수 필드 업데이트, 50 스레드 동시 접근 |
| `TestAddStepLog` | ✅/🔄 접두어, 20개 한도, 오래된 항목 삭제 |
| `TestResetProgress` | 새 주문 시작 시 완전 초기화 |
| `TestTick` | 진행률 계산, 99% 상한, total_steps 초과 방지 |
| `TestEmergencyStop` | 비상정지/재개 이벤트 및 상태 전이 |
| `TestOrderDeduplication` | 중복 주문 방지, 50 스레드 동시 mark |
| `TestGetStatusDict` | 11개 필수 키, 타입 검증, collision/gripper 반영 |
| `TestPauseResume` (신규) | set_pause/clear_pause/is_paused/wait_if_paused |
| `TestEnumValues` (신규) | RobotState·GripperWidth 열거형 값 및 멤버 수 |
| `TestRobotStatusDefaults` (신규) | 기본 gripper(100mm), joint_pos([0]*6), collision(False) |
| `TestStepLogDataclass` (신규) | timestamp/completed 필드, 30 스레드 동시 추가 |

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

### 3-4. `test_order_model.py` — 21개 테스트 (신규)

**대상**: `cobot1/repositories/order_repository.py`, `mock_order_repository.py`  
**역할**: Order 도메인 객체 및 OrderRepository 추상 인터페이스 검증

| 테스트 클래스 | 검증 항목 |
|--------------|-----------|
| `TestOrderDataclass` | 필드 저장, default(status=pending, target_stage=0, run_mode=from) |
| `TestOrderRepositoryAbstract` | 직접 생성 불가, Mock이 구현체임을 확인, 추상 메서드 목록 |
| `TestMockOrderRepositoryExtra` | 기본 주문 key/dish, 다양한 명령, 20 스레드 동시 삽입 |

---

### 3-5. `test_robot_controller.py` — 26개 테스트

**대상**: `cobot1/robot_controller.py`  
**역할**: 명령 수신·주문 큐 관리·ROS 메시지 파싱

| 테스트 클래스 | 검증 항목 |
|--------------|-----------|
| `TestCommandReceivedPause` | pause → is_paused, "pause_stop" 큐 삽입, 상태 IDLE |
| `TestCommandReceivedResume` | resume → 일시정지 해제, 비상정지 해제, 상태 MOVING |
| `TestCommandReceivedQueueDelegation` | Rule 7: 명령 → _cmd_queue 위임, resume은 큐 비삽입 |
| `TestOrderReceived` | 첫 주문 큐 적재, 중복 방지, 10 스레드 동시 수신 |
| `TestRosOrderMsg` | JSON 파싱, 빈 key 거부, 잘못된 JSON 예외 없음 |

**핵심 검증 — pause/resume 즉시 처리 vs 큐 위임**

| 명령 | 처리 방식 |
|------|----------|
| `pause` | 즉시: sm.set_pause() + 상태 IDLE → 큐에 "pause_stop" (do_stop 위임) |
| `resume` | 즉시: sm.clear_pause() + 비상정지 해제 → 큐에 아무것도 삽입 안 함 |
| 나머지 | 전부 cmd_queue 에 위임 (Rule 7) |

---

## 4. 실행 방법

```bash
# 전체 테스트 실행
cd ~/cobot_ws/src
python3 -m pytest cobot1/test/ -v

# 특정 파일만
python3 -m pytest cobot1/test/test_robot_client.py -v

# 신규 추가 테스트만
python3 -m pytest cobot1/test/test_order_model.py -v
python3 -m pytest cobot1/test/test_state_manager.py::TestPauseResume -v

# 빠른 실패 확인 (첫 번째 실패 시 중단)
python3 -m pytest cobot1/test/ -v -x
```

---

## 5. 최종 테스트 결과

**실행 일시**: 2026년 5월 12일  
**실행 명령**: `python3 -m pytest cobot1/test/ -v`  
**환경**: Python 3.10.12 / pytest-9.0.3 / ROS2 Humble

```
============================= test session info ==============================
platform linux -- Python 3.10.12, pytest-9.0.3
collected 168 items

168 passed in 11.70s
```

### 파일별 결과 요약

| 테스트 파일 | 테스트 수 | PASS | FAIL | 비고 |
|------------|:---------:|:----:|:----:|------|
| `test_mock_repository.py` | 12 | **12** | 0 | 기존 유지 |
| `test_order_model.py` | 21 | **21** | 0 | 기존 유지 |
| `test_robot_client.py` | 46 | **46** | 0 | +6 TestDoMovePeriodic 신규 추가 |
| `test_robot_controller.py` | 26 | **26** | 0 | 기존 유지 |
| `test_state_manager.py` | 63 | **63** | 0 | 기존 유지 |
| **합계** | **168** | **168** | **0** | |

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

### test_order_model.py (21/21 PASS) — 신규

| # | 테스트명 | 결과 | 검증 내용 |
|---|---------|:----:|-----------|
| 1 | `TestOrderDataclass::test_required_fields_stored` | ✅ | key/sub_dishes/main_dish 저장 |
| 2 | `TestOrderDataclass::test_default_status_is_pending` | ✅ | status 기본값 = "pending" |
| 3 | `TestOrderDataclass::test_default_target_stage_zero` | ✅ | target_stage 기본값 = 0 |
| 4 | `TestOrderDataclass::test_default_run_mode_from` | ✅ | run_mode 기본값 = "from" |
| 5 | `TestOrderDataclass::test_custom_target_stage` | ✅ | target_stage=3 지정 가능 |
| 6 | `TestOrderDataclass::test_custom_run_mode_only` | ✅ | run_mode="only" 지정 가능 |
| 7 | `TestOrderDataclass::test_custom_status` | ✅ | status="processing" 지정 가능 |
| 8 | `TestOrderDataclass::test_sub_dishes_can_be_empty_list` | ✅ | 빈 sub_dishes 허용 |
| 9 | `TestOrderDataclass::test_sub_dishes_multiple_items` | ✅ | 3개 반찬 목록 저장 |
| 10 | `TestOrderDataclass::test_order_equality_by_key` | ✅ | 동일 key 비교 |
| 11 | `TestOrderRepositoryAbstract::test_cannot_instantiate_abstract_class` | ✅ | 직접 생성 시 TypeError |
| 12 | `TestOrderRepositoryAbstract::test_mock_order_repository_is_concrete` | ✅ | Mock이 구체 구현체임을 확인 |
| 13 | `TestOrderRepositoryAbstract::test_abstract_methods_defined` | ✅ | 6개 추상 메서드 전부 정의됨 |
| 14 | `TestMockOrderRepositoryExtra::test_inject_order_default_key_starts_with_mock` | ✅ | 기본 주문 key는 "mock_" 시작 |
| 15 | `TestMockOrderRepositoryExtra::test_inject_order_default_main_dish` | ✅ | 기본 주문 main_dish = "돈까스" |
| 16 | `TestMockOrderRepositoryExtra::test_inject_order_default_sub_dishes` | ✅ | 기본 주문 sub_dishes ≥ 1개 |
| 17 | `TestMockOrderRepositoryExtra::test_multiple_listeners_not_supported_but_safe` | ✅ | listen_orders 두 번 호출 예외 없음 |
| 18 | `TestMockOrderRepositoryExtra::test_upload_robot_status_accumulates_payloads` | ✅ | 3회 업로드 → 3개 누적 |
| 19 | `TestMockOrderRepositoryExtra::test_upload_robot_status_payload_content` | ✅ | 저장된 페이로드 내용 일치 |
| 20 | `TestMockOrderRepositoryExtra::test_inject_command_various_types` | ✅ | 4가지 명령 타입 큐 적재 |
| 21 | `TestMockOrderRepositoryExtra::test_concurrent_inject_order_is_thread_safe` | ✅ | 20개 스레드 동시 삽입 충돌 없음 |

### test_robot_client.py (46/46 PASS)

| # | 테스트명 | 결과 | 검증 내용 |
|---|---------|:----:|-----------|
| 1 | `TestRobotClientInit::test_default_vel_acc` | ✅ | 기본 vel=50, acc=50 |
| 2 | `TestRobotClientInit::test_custom_vel_acc` | ✅ | 커스텀 vel=60, acc=60 |
| 3 | `TestRobotClientInit::test_inject_not_called_dsr_is_none` | ✅ | inject 전 DSR 함수 모두 None |
| 4 | `TestRobotClientInit::test_inject_sets_all_dsr_functions` | ✅ | inject 후 전체 DSR 함수 바인딩 확인 |
| 5 | `TestRobotClientMotion::test_do_movej_calls_movej_and_mwait` | ✅ | movej(coords, vel, acc, radius=None) + mwait() |
| 6 | `TestRobotClientMotion::test_do_movel_calls_movel_with_dr_base_and_mwait` | ✅ | movel(ref=DR_BASE, radius=None) + mwait() |
| 7 | `TestRobotClientMotion::test_do_amovej_no_mwait` | ✅ | 비동기 이동 시 mwait 미호출 |
| 8 | `TestRobotClientMotion::test_do_amovel_no_mwait` | ✅ | 비동기 직선 이동 시 mwait 미호출 |
| 9 | `TestRobotClientMotion::test_posj_called_in_movej` | ✅ | movej 호출 전 posj() 좌표 변환 |
| 10 | `TestRobotClientMotion::test_posx_called_in_movel` | ✅ | movel 호출 전 posx() 좌표 변환 |
| 11 | `TestWaitMotionDone::test_returns_true_when_already_idle` | ✅ | check_motion==0 이면 즉시 True 반환 |
| 12 | `TestWaitMotionDone::test_polls_until_idle` | ✅ | Busy→Busy→Idle 3회 폴링 후 True |
| 13 | `TestWaitMotionDone::test_returns_true_after_polling` | ✅ | Busy→Idle 전환 후 True 반환 |
| 14 | `TestGripper::test_set_gripper_do_pins[5]` | ✅ | 5mm → DO1=ON, DO2=OFF, DO3=OFF |
| 15 | `TestGripper::test_set_gripper_do_pins[20]` | ✅ | 20mm → DO1=ON, DO2=OFF, DO3=ON |
| 16 | `TestGripper::test_set_gripper_do_pins[30]` | ✅ | 30mm → DO1=ON, DO2=ON, DO3=OFF |
| 17 | `TestGripper::test_set_gripper_do_pins[50]` | ✅ | 50mm → DO1=OFF, DO2=OFF, DO3=ON |
| 18 | `TestGripper::test_set_gripper_do_pins[100]` | ✅ | 100mm → DO1=OFF, DO2=ON, DO3=OFF |
| 19 | `TestGripper::test_set_gripper_calls_time_sleep_with_settle_sec` | ✅ | time.sleep(GRIPPER_SETTLE_SEC=2.0) 호출 |
| 20 | `TestGripper::test_invalid_gripper_width_silently_ignored` | ✅ | 999mm → DO 출력 없이 무시 |
| 21 | `TestGripper::test_gripper_map_covers_all_widths` | ✅ | _GRIPPER_MAP 키 = {5, 20, 30, 50, 100} |
| 22 | `TestStopMethods::test_do_stop_calls_move_stop_3` | ✅ | do_stop() → move_stop(3) |
| 23 | `TestStopMethods::test_do_stop_no_error_when_not_injected` | ✅ | inject 전 do_stop() 예외 없음 |
| 24 | `TestStopMethods::test_do_stop_propagates_dsr_error` | ✅ | DSR 예외는 호출자에게 전파됨 확인 |
| 25 | `TestConstants::test_on_off_values` | ✅ | ON=1, OFF=0 |
| 26 | `TestConstants::test_timing_constants_are_positive` | ✅ | 모든 타이밍 상수 > 0 |
| 27 | `TestCheckGrip::test_check_grip_returns_true_when_di1_is_1` | ✅ | DI1=1 → 파지 성공(True) |
| 28 | `TestCheckGrip::test_check_grip_returns_false_when_di1_is_0` | ✅ | DI1=0 → 파지 실패(False) |
| 29 | `TestCheckGrip::test_check_grip_returns_true_on_exception` | ✅ | DI 오류 시 안전 fallback(True) |
| 30 | `TestGetRobotState::test_get_robot_state_delegates_to_dsr` | ✅ | DSR 반환값 그대로 전달 |
| 31 | `TestGetRobotState::test_get_robot_state_returns_1_when_not_injected` | ✅ | inject 전 기본값 1(STANDBY) |
| 32 | `TestGetRobotState::test_get_robot_state_returns_standby_by_default` | ✅ | inject 후 DSR 기본값 1 확인 |
| 33 | `TestGetForce::test_get_tool_force_returns_6_element_list` | ✅ | 반환값 list, 길이 6 |
| 34 | `TestGetForce::test_get_tool_force_returns_zeros_when_not_injected` | ✅ | inject 전 [0.0]*6 반환 |
| 35 | `TestGetForce::test_get_external_torque_returns_6_element_list` | ✅ | 반환값 list, 길이 6 |
| 36 | `TestGetForce::test_get_external_torque_returns_zeros_when_not_injected` | ✅ | inject 전 [0.0]*6 반환 |
| 37 | `TestMotionWithRadius::test_do_movej_with_radius_passed_to_dsr` | ✅ | radius=50.0 DSR에 전달 |
| 38 | `TestMotionWithRadius::test_do_movel_with_radius_passed_to_dsr` | ✅ | radius=30.0 DSR에 전달 |
| 39 | `TestMotionWithRadius::test_do_movej_radius_none_by_default` | ✅ | 미지정 시 radius=None |
| 40 | `TestMotionWithRadius::test_do_amovej_with_radius` | ✅ | 비동기 이동에도 radius 전달 |

| 41 | `TestDoMovePeriodic::test_calls_dsr_move_periodic_with_correct_args` | ✅ | move_periodic(amp, period_ms, atime, count) DSR 전달 |
| 42 | `TestDoMovePeriodic::test_does_nothing_before_inject` | ✅ | inject 전 do_move_periodic() 예외 없이 리턴 |
| 43 | `TestDoMovePeriodic::test_period_ms_forwarded_as_period_kwarg` | ✅ | period_ms가 DSR 두 번째 positional 인수로 전달 |
| 44 | `TestDoMovePeriodic::test_count_forwarded_correctly` | ✅ | count가 DSR 네 번째 positional 인수로 전달 |
| 45 | `TestDoMovePeriodic::test_amp_forwarded_correctly` | ✅ | amp 벡터가 DSR 첫 번째 positional 인수로 전달 |
| 46 | `TestDoMovePeriodic::test_called_only_once_per_invocation` | ✅ | do_move_periodic 1회 호출 시 DSR 1회만 호출 |

### test_robot_controller.py (26/26 PASS)

| # | 테스트명 | 결과 | 검증 내용 |
|---|---------|:----:|-----------|
| 1 | `TestCommandReceivedPause::test_pause_sets_paused_state` | ✅ | pause → is_paused() = True |
| 2 | `TestCommandReceivedPause::test_pause_puts_pause_stop_in_cmd_queue` | ✅ | pause → "pause_stop" 큐 삽입 |
| 3 | `TestCommandReceivedPause::test_pause_updates_state_to_idle` | ✅ | pause → 상태 IDLE |
| 4 | `TestCommandReceivedPause::test_pause_does_not_directly_call_do_stop` | ✅ | Rule 7: do_stop() 직접 호출 없음 |
| 5 | `TestCommandReceivedResume::test_resume_clears_paused_state` | ✅ | resume → is_paused() = False |
| 6 | `TestCommandReceivedResume::test_resume_clears_emergency_stop_when_stopped` | ✅ | 비상정지 중 resume → 이벤트 해제 |
| 7 | `TestCommandReceivedResume::test_resume_updates_state_to_moving` | ✅ | resume → 상태 MOVING |
| 8 | `TestCommandReceivedResume::test_resume_when_not_paused_no_exception` | ✅ | 정상 상태 resume → 예외 없음 |
| 9 | `TestCommandReceivedQueueDelegation::test_emergency_stop_enqueued_to_cmd_queue` | ✅ | emergency_stop → 큐 위임 |
| 10 | `TestCommandReceivedQueueDelegation::test_move_home_enqueued_to_cmd_queue` | ✅ | Rule 7: move_home → 큐 위임 |
| 11 | `TestCommandReceivedQueueDelegation::test_gripper_open_enqueued` | ✅ | Rule 7: gripper_open → 큐 위임 |
| 12 | `TestCommandReceivedQueueDelegation::test_gripper_close_enqueued` | ✅ | Rule 7: gripper_close → 큐 위임 |
| 13 | `TestCommandReceivedQueueDelegation::test_gripper_full_open_enqueued` | ✅ | Rule 7: gripper_full_open → 큐 위임 |
| 14 | `TestCommandReceivedQueueDelegation::test_unknown_command_enqueued` | ✅ | 알 수 없는 명령도 큐 위임 |
| 15 | `TestCommandReceivedQueueDelegation::test_pause_converts_to_pause_stop_in_queue` | ✅ | pause는 "pause_stop"으로 변환 |
| 16 | `TestCommandReceivedQueueDelegation::test_resume_does_not_enqueue_to_cmd_queue` | ✅ | resume은 즉시 처리, 큐 비삽입 |
| 17 | `TestOrderReceived::test_first_order_enqueued` | ✅ | 첫 주문 → _order_queue 적재 |
| 18 | `TestOrderReceived::test_duplicate_order_not_enqueued` | ✅ | 동일 key 두 번 → 큐에 1개만 |
| 19 | `TestOrderReceived::test_different_orders_both_enqueued` | ✅ | 다른 key 두 주문 → 큐에 2개 |
| 20 | `TestOrderReceived::test_order_marked_processed_after_receive` | ✅ | 수신 즉시 processed 마킹 |
| 21 | `TestOrderReceived::test_concurrent_order_deduplication` | ✅ | 10 스레드 동시 수신 → 1건만 적재 |
| 22 | `TestRosOrderMsg::test_valid_json_order_enqueued` | ✅ | 유효한 JSON → 큐 적재 |
| 23 | `TestRosOrderMsg::test_invalid_json_does_not_raise` | ✅ | 잘못된 JSON → 예외 없음 |
| 24 | `TestRosOrderMsg::test_empty_key_order_not_enqueued` | ✅ | key="" 주문 → 큐 비적재 |
| 25 | `TestRosOrderMsg::test_missing_key_field_not_enqueued` | ✅ | _key 필드 없음 → 큐 비적재 |
| 26 | `TestRosOrderMsg::test_ros_order_sub_dishes_parsed_correctly` | ✅ | sub_dishes 목록 파싱 정확성 |

### test_state_manager.py (63/63 PASS)

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
| 18 | `TestTick::test_tick_caps_at_99` | ✅ | 완료 직전까지 최대 99% |
| 19 | `TestTick::test_tick_does_not_exceed_total` | ✅ | step_index ≤ total_steps |
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
| 34 | `TestGetStatusDict::test_collision_reflects_true_when_set` | ✅ | collision_detected=True 반영 |
| 35 | `TestGetStatusDict::test_gripper_value_is_string` | ✅ | gripper 값이 str |
| 36 | `TestGetStatusDict::test_last_update_is_float` | ✅ | last_update가 float |
| 37 | `TestGetStatusDict::test_step_log_empty_initially` | ✅ | 초기 step_log=[] |
| 38 | `TestPauseResume::test_initial_not_paused` | ✅ | 초기 is_paused() = False |
| 39 | `TestPauseResume::test_set_pause_makes_is_paused_true` | ✅ | set_pause() 후 is_paused = True |
| 40 | `TestPauseResume::test_clear_pause_makes_is_paused_false` | ✅ | clear_pause() 후 is_paused = False |
| 41 | `TestPauseResume::test_clear_pause_without_set_is_safe` | ✅ | set 없이 clear 해도 예외 없음 |
| 42 | `TestPauseResume::test_wait_if_paused_does_not_block_when_not_paused` | ✅ | 미정지 시 즉시 반환 |
| 43 | `TestPauseResume::test_wait_if_paused_unblocks_after_clear` | ✅ | clear 후 블로킹 스레드 재개 |
| 44 | `TestPauseResume::test_pause_resume_cycle` | ✅ | 3회 반복 pause/clear 정상 동작 |
| 45 | `TestEnumValues::test_robot_state_idle_value` | ✅ | RobotState.IDLE.value = "idle" |
| 46 | `TestEnumValues::test_robot_state_moving_value` | ✅ | RobotState.MOVING.value = "moving" |
| 47 | `TestEnumValues::test_robot_state_processing_value` | ✅ | RobotState.PROCESSING.value = "processing" |
| 48 | `TestEnumValues::test_robot_state_error_value` | ✅ | RobotState.ERROR.value = "error" |
| 49 | `TestEnumValues::test_robot_state_emergency_stop_value` | ✅ | RobotState.EMERGENCY_STOP.value = "emergency_stop" |
| 50 | `TestEnumValues::test_robot_state_has_5_members` | ✅ | RobotState 멤버 수 = 5 |
| 51 | `TestEnumValues::test_gripper_width_mm5_value` | ✅ | GripperWidth.MM5.value = "5mm" |
| 52 | `TestEnumValues::test_gripper_width_mm100_value` | ✅ | GripperWidth.MM100.value = "100mm" |
| 53 | `TestEnumValues::test_gripper_width_has_5_members` | ✅ | GripperWidth 멤버 수 = 5 |
| 54 | `TestRobotStatusDefaults::test_default_gripper_is_mm100` | ✅ | 초기 그리퍼 = MM100 |
| 55 | `TestRobotStatusDefaults::test_default_joint_pos_is_6_zeros` | ✅ | 초기 joint_pos = [0.0]*6 |
| 56 | `TestRobotStatusDefaults::test_default_current_task` | ✅ | 초기 current_task = "대기 중" |
| 57 | `TestRobotStatusDefaults::test_default_collision_false` | ✅ | 초기 collision_detected = False |
| 58 | `TestRobotStatusDefaults::test_update_gripper_via_update_status` | ✅ | update_status로 gripper 변경 |
| 59 | `TestRobotStatusDefaults::test_update_joint_pos` | ✅ | update_status로 joint_pos 변경 |
| 60 | `TestStepLogDataclass::test_step_log_has_timestamp` | ✅ | StepLog.timestamp가 양수 float |
| 61 | `TestStepLogDataclass::test_step_log_completed_field` | ✅ | completed=True 필드 저장 |
| 62 | `TestStepLogDataclass::test_step_log_in_progress_field` | ✅ | completed=False 필드 저장 |
| 63 | `TestStepLogDataclass::test_step_log_thread_safe_add` | ✅ | 30개 스레드 동시 추가 충돌 없음 |

---

## 7. 변경 이력

### 2026-05-12 변경 이력

소스 코드 변경으로 인해 새 테스트를 추가했습니다.

| 파일 | 변경 내용 |
|------|----------|
| `test_robot_client.py` | `TestDoMovePeriodic` 6개 테스트 추가 (`do_move_periodic` → DSR `move_periodic` 전달 검증) |

### 2026-05-09 변경 이력 (API 업데이트 반영)

소스 코드 변경으로 인해 기존 테스트 일부를 수정하고 새 테스트를 추가했습니다.

| 파일 | 변경 내용 |
|------|----------|
| `conftest.py` | `dsr_msgs2`, `dsr_msgs2.srv` stub 추가 |
| `test_robot_client.py` | `inject()` 시그니처 업데이트 (get_tool_force/get_external_torque 추가), vel/acc 기본값 50으로 수정, radius 파라미터 반영, 신규 14개 테스트 추가 |
| `test_robot_controller.py` | `_handle_command` → `_on_command_received` API 전환, pause/resume/cmd_queue 위임 테스트 전면 재작성, ROS 메시지 파싱 테스트 추가 |
| `test_state_manager.py` | 일시정지·열거형·데이터클래스·기본값 테스트 29개 추가 |
| `test_order_model.py` | 신규 파일: Order 도메인 객체 및 OrderRepository 인터페이스 21개 테스트 |

---

## 8. 테스트 커버리지 범위

| 모듈 | 커버 여부 | 미커버 범위 |
|------|:---------:|-----------|
| `robot_client.py` | ✅ 전체 공개 API | - |
| `state_manager.py` | ✅ 전체 | - |
| `mock_order_repository.py` | ✅ 전체 | - |
| `order_repository.py` (Order/ABC) | ✅ 전체 | - |
| `robot_controller.py` | ✅ 명령·주문 수신 경로 | _task_loop, _status_upload_loop, _collision_monitor_loop (스레드 루프) |
| `stages/*.py` | ❌ | 통합 테스트 필요 |
| `coordinate_manager.py` | ❌ | YAML 파일 의존 |
| `lunchbox_robot_node.py` | ❌ | ROS2 노드 생성 필요 |

> 스테이지 클래스와 노드 진입점은 실제 좌표 YAML 파일과 ROS2 런타임이 필요하여 통합 테스트로 분류합니다.
