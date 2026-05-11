# cobot1 패키지 아키텍처 분석 문서

**작성일**: 2026년 5월 8일  
**최종 수정**: 2026년 5월 10일  
**패키지**: `src/cobot1/` — 나만의 도련님 도시락 로봇 제어 시스템  
**로봇**: Doosan M0609 / ROS2 Humble  
**브랜치**: `main`

---

## 1. 시스템 개요

나만의 도련님 도시락은 **Doosan M0609 협동 로봇**이 도시락을 자동으로 조립하는 시스템입니다.  
웹 주문(Firebase) → 로봇 동작(DSR_ROBOT2) → 상태 피드백(Firebase/ROS2) 의 흐름으로 동작합니다.

```
고객 웹 주문
    │
    ▼
Firebase Realtime DB (/orders)
    │
    ▼
FirebaseOrderRepository ── listen_orders() ──▶ RobotController._on_order_received()
                                                        │
                                                        ▼
                                               _order_queue (Queue)
                                                        │
                                                        ▼
                                               task_thread._process_order()
                                                        │
                              ┌─────────────────────────┼────────────────────────┐
                              ▼                         ▼                        ▼
                        Stage 1 (식판)          Stage 2 (서브반찬)        Stage 3~5 ...
                              │
                              ▼
                        RobotClient.do_movej/movel/set_gripper()
                              │
                              ▼
                        DSR_ROBOT2 API (실제 로봇 모터)
```
P
---

## 2. 패키지 구조

```
src/cobot1/cobot1/
├── lunchbox_robot_node.py       # 진입점 — 모든 컴포넌트 조립
├── lunchbox_database_node.py    # Firebase 전용 데이터베이스 노드 (독립 실행)
├── robot_controller.py          # 스레드 통합 + 주문/명령/테스트 처리
├── robot_client.py              # DSR API 래퍼 (유일한 DSR 호출 계층)
├── state_manager.py             # 중앙 상태 관리 (스레드 안전, 일시정지 지원)
├── coordinate_manager.py        # YAML 좌표 로드 및 제공
├── camera_stream_server.py      # 카메라 영상 스트림 HTTP 서버
├── robot_dashboard.py           # 로봇 상태 대시보드 (CLI)
├── mini_jog.py                  # 수동 조그 유틸리티
├── move_basic.py                # 기본 이동 테스트 스크립트
├── stages/
│   ├── base_stage.py            # 스테이지 추상 기본 클래스
│   └── stages.py                # 5개 스테이지 구현체
├── repositories/
│   ├── order_repository.py      # OrderRepository 인터페이스 + Order 데이터클래스
│   ├── firebase_order_repository.py  # Firebase 구현체
│   └── mock_order_repository.py      # 테스트용 인메모리 구현체
└── config/
    └── robot_coordinates.yaml   # 모든 관절/직선 좌표
```

---

## 3. 계층 구조 (Layer Architecture)

```
┌─────────────────────────────────────┐
│  lunchbox_robot_node.py             │  ← 진입점, DI(의존성 주입) 조립
├─────────────────────────────────────┤
│  RobotController                    │  ← 스레드 오케스트레이터
├──────────────┬──────────────────────┤
│  Stages      │  RobotStateManager   │  ← 도메인 로직 + 상태
│  (5개 클래스)│  CoordinateManager   │
├──────────────┴──────────────────────┤
│  RobotClient                        │  ← DSR API 래퍼 (유일한 HW 접점)
├─────────────────────────────────────┤
│  DSR_ROBOT2 / DR_common2            │  ← 로봇 제조사 SDK (하드웨어)
└─────────────────────────────────────┘
```

각 계층은 아래 계층에만 의존하며, **스테이지는 RobotClient를 직접 알지 못하고 BaseStage의 헬퍼(`_movej`, `_gripper`)만 사용**합니다.

---

## 4. 핵심 컴포넌트 상세 분석

### 4-1. `lunchbox_robot_node.py` — 진입점

**역할**: 컴포넌트 생성 → 의존성 주입 → 컨트롤러 시작  
**설계 원칙**: 생성 코드만 존재. 비즈니스 로직 없음.

```
main()
 ├─ rclpy.init() + create_node()         # ROS2 초기화
 ├─ DR_init.__dsr__node = node           # DSR에 노드 주입 (필수 순서)
 ├─ from DSR_ROBOT2 import ...           # ← 노드 생성 이후에만 가능 (공식 규칙)
 ├─ set_robot_mode(ROBOT_MODE_AUTONOMOUS)
 ├─ CoordinateManager()                  # YAML 로드
 ├─ RobotStateManager()
 ├─ RobotClient().inject(movej, ...)     # DSR 함수 주입
 ├─ Firebase 또는 Mock 저장소 선택
 └─ RobotController.start()
```

**주요 특징**:
- Firebase 키 파일 부재 시 자동으로 `MockOrderRepository`로 전환
- `finally` 블록에서 노드 소멸 후에도 로깅 가능하도록 모듈 레벨 `_logger` 분리

---

### 4-2. `RobotController` — 스레드 오케스트레이터

**역할**: 4개 스레드 생명주기 관리 + 주문/명령 라우팅

#### 스레드 구조

| 스레드명 | daemon | 역할 | DSR 호출 |
|---------|:------:|------|:--------:|
| `ros_spin` | False | ROS2 MultiThreadedExecutor.spin() (4 threads) | ❌ |
| `task` | False | 주문 처리 + Stage 실행 + DSR 초기화 + 테스트 시나리오 | ✅ (유일) |
| `status_upload` | True | 1초 주기 Firebase 상태 업로드 (pause/collision 상태 오버라이드) | ❌ |
| `collision_monitor` | True | 0.3초 주기 외력/토크 기반 충돌 감지 | ❌ |

#### 초기화 시퀀스

```
start()
 ├─ ros_spin 스레드 시작
 ├─ ROS 토픽 구독 등록 (/robot_order)
 ├─ Firebase 명령 리스너 등록
 ├─ task / status / monitor 스레드 시작
 │      │
 │      ▼ (task 스레드 내부)
 │   set_tool() → set_tcp() → do_movej(home) → set_gripper(100)
 │   성공 → _init_ok = True → _init_event.set()
 │   실패 → _init_ok = False → _init_event.set()
 │
 └─ _init_event.wait(timeout=30초)  ← 메인 스레드 여기서 블록
      ├─ 성공 → True 반환
      └─ 실패/타임아웃 → stop() 호출 후 False 반환
```

#### 명령 처리 흐름 (Rule 7 준수)

```
Firebase 콜백 스레드
  _on_command_received("pause")
      │
      ▼
  _handle_command("pause")
      │
      ├─ "pause"          → sm.set_pause() 즉시 세팅 + _cmd_queue.put("pause_stop")
      │                     (스테이지가 wait_if_paused()에서 즉시 블로킹됨)
      │
      ├─ "resume"         → sm.clear_pause() + sm.clear_emergency_stop() [즉시]
      │
      ├─ "emergency_stop" → _cmd_queue.put("emergency_stop")
      │
      └─ 나머지 명령들
              │
              ▼
         _cmd_queue.put(cmd_type)  ← 큐에만 삽입
              │
              ▼ (task 스레드가 꺼냄)
         _execute_cmd(cmd_type)
              │
              ├─ "emergency_stop"    → rc.do_stop() + sm.trigger_emergency_stop()
              ├─ "pause_stop"        → rc.do_stop()
              ├─ "reset_and_restart" → SetRobotControl 서비스 호출 + 주문 큐 재삽입
              ├─ "test_cancel"       → _test_cancel.set() + rc.do_stop()
              ├─ "move_home"         → rc.do_movej(home)
              └─ "gripper_*"         → rc.set_gripper(...)
```

**지원 명령 목록** (Firebase `/command` 경유):

| 명령 | 처리 방식 | 동작 |
|------|----------|------|
| `emergency_stop` | 큐 위임 | `do_stop()` + 비상정지 상태 |
| `pause` | 즉시 플래그 + 큐(`pause_stop`) | 일시정지 + `do_stop()` |
| `resume` | 즉시 | 일시정지/비상정지 해제 |
| `reset_and_restart` | 큐 위임 | 하드웨어 복구 서비스 + 주문 재시작 |
| `move_home` | 큐 위임 | 홈 이동 |
| `gripper_open` | 큐 위임 | 그리퍼 50mm |
| `gripper_close` | 큐 위임 | 그리퍼 5mm |
| `gripper_full_open` | 큐 위임 | 그리퍼 100mm |
| `test_cancel` | 큐 위임 | 테스트 시나리오 중단 |

---

### 4-3. `RobotClient` — DSR API 래퍼

**역할**: DSR_ROBOT2 함수를 직접 호출하는 **유일한 계층**  
**설계 원칙**: 의존성 주입(inject)으로 DSR 함수 수신 → 테스트 가능성 확보

#### inject() 주입 인자 전체 목록

| 인자 | DSR 함수 | 용도 |
|------|---------|------|
| `movej` | `movej` | 관절 동기 이동 |
| `movel` | `movel` | 직선 동기 이동 |
| `mwait` | `mwait` | 모션 완료 대기 |
| `amovej` | `amovej` | 관절 비동기 이동 |
| `amovel` | `amovel` | 직선 비동기 이동 |
| `set_digital_output` | `set_digital_output` | 그리퍼 DO 핀 제어 |
| `get_digital_input` | `get_digital_input` | 그리퍼 DI 핀 읽기 |
| `wait` | `wait` | DSR 대기 |
| `drl_script_stop` | `drl_script_stop` | 스크립트 정지 |
| `check_motion` | `check_motion` | 모션 상태 확인 |
| `move_stop` | `move_stop` | 로봇 정지 |
| `get_robot_state` | `get_robot_state` | 로봇 상태 조회 |
| `get_tool_force` | `get_tool_force` | 툴 외력 벡터 조회 (충돌 감지용) |
| `get_external_torque` | `get_external_torque` | 외부 토크 조회 (충돌 감지용) |
| `posj` | `posj` | 관절 좌표 생성자 |
| `posx` | `posx` | 직선 좌표 생성자 |
| `DR_BASE` | `DR_BASE` | 기준 좌표계 상수 |

#### 주요 메서드

| 메서드 | 설명 |
|--------|------|
| `do_movej(coords)` | 관절 이동 + mwait |
| `do_movel(coords)` | 직선 이동 + mwait |
| `do_amovej(coords)` | 관절 비동기 이동 (mwait 없음) |
| `do_amovel(coords)` | 직선 비동기 이동 (mwait 없음) |
| `set_gripper(width_mm)` | 그리퍼 DO 핀 제어 |
| `check_grip()` | 파지 확인 (DI 핀 읽기) |
| `get_tool_force()` | 툴 외력 6축 벡터 반환 |
| `get_external_torque()` | 외부 토크 6축 벡터 반환 |
| `do_stop()` | 감속 정지 (`move_stop(3)`) |
| `get_robot_state()` | 로봇 상태 정수 반환 |
| `wait_motion_done()` | 폴링 기반 모션 완료 대기 |

#### 그리퍼 DO핀 매핑 테이블

| 폭(mm) | DO1 | DO2 | DO3 | 용도 |
|:------:|:---:|:---:|:---:|------|
| 5 | ON | OFF | OFF | 집기 (최소) |
| 20 | ON | OFF | ON | 서브 반찬 집기 |
| 30 | ON | ON | OFF | - |
| 50 | OFF | OFF | ON | 반쯤 열기 |
| 100 | OFF | ON | OFF | 완전 열기 (기본) |

#### 비동기 이동 완료 대기 패턴

```python
def wait_motion_done(self) -> bool:
    time.sleep(MOTION_START_DELAY_SEC)   # 0.2초: Busy 상태 진입 대기
    while self._drs_check_motion() != 0:  # 0=Idle, 1=Init, 2=Busy
        time.sleep(MOTION_CHECK_INTERVAL_SEC)  # 0.1초 폴링
        if not rclpy.ok():
            return False   # 프로세스 종료 시 탈출
    return True
```

---

### 4-4. `RobotStateManager` — 중앙 상태 관리

**역할**: 모든 전역 상태를 단일 객체로 관리. `RLock` 기반 스레드 안전 보장.  
**신규**: `pause_event` (threading.Event) 기반 일시정지 메커니즘 추가.

#### 상태 전이 다이어그램

```
         ┌─────────────────────────────┐
         │           IDLE              │ ← 초기 상태 / 주문 완료 / resume
         └────┬───────────────────┬────┘
              │                   │
        order │             emergency_stop
        수신  │                   │
              ▼                   ▼
         ┌──────────┐      ┌──────────────────┐
         │  MOVING  │──────│  EMERGENCY_STOP  │
         └────┬─────┘pause └──────────────────┘
              │   ↕ resume
              │  [PAUSED: pause_event.clear()]   ← RobotState enum 외부,
              │   스테이지는 wait_if_paused()에서   상태 업로드 시 'paused' 오버라이드
              │   블로킹. resume 시 재개.
              │
        stage │ 실행 중
              ▼
         ┌─────────────┐
         │ PROCESSING  │
         └────┬────┬───┘
              │    │
         완료 │    │ 예외
              ▼    ▼
          IDLE    ERROR
```

#### 주요 데이터 구조

```python
@dataclass
class RobotStatus:
    state:        RobotState    # IDLE / MOVING / PROCESSING / ERROR / EMERGENCY_STOP
    current_task: str           # 현재 수행 중인 작업 이름
    gripper:      GripperWidth  # 현재 그리퍼 폭 (5~100mm)
    joint_pos:    List[float]   # 현재 관절 각도 6축
    progress:     int           # 진행률 0~100% (완료 전 최대 99%)
    step_index:   int           # 현재 스텝 번호
    total_steps:  int           # 전체 스텝 수
    current_step: str           # 현재 스텝 이름/레이블
    step_log:     List[StepLog] # 최근 20개 단계 로그
    last_update:  float         # 마지막 업데이트 타임스탬프
    collision_detected: bool    # 충돌 감지 여부
```

#### 일시정지 메커니즘

```python
# 일시정지: pause_event.clear() → 스테이지 내 wait_if_paused()가 블로킹
sm.set_pause()          # pause_event.clear()
sm.clear_pause()        # pause_event.set()
sm.is_paused()          # not pause_event.is_set()
sm.wait_if_paused()     # pause_event.wait()  ← 스테이지 루프에서 호출

# 상태 업로드 시 오버라이드
if sm.is_paused():      payload['state'] = 'paused'
elif sm.is_stopped():   payload['state'] = 'collision'
```

---

### 4-5. `BaseStage` + 5개 스테이지

**역할**: 로봇 동작 시퀀스를 스테이지 단위로 캡슐화

#### 스테이지 구성

| 스테이지 | 클래스 | 동작 | 이동 횟수 |
|---------|--------|------|:---------:|
| Stage 1 | `TraySetupStage` | 식판 보관소 → 세팅 장소 | ~8회 |
| Stage 2 | `SubDishStage` | 서브 반찬 Pick & Place (반찬당 1 인스턴스) | ~7회/종 |
| Stage 3 | `MainDishStage` | 메인 반찬 + 소스 | ~11회 |
| Stage 4 | `RiceStage` | 밥 스쿱 | ~13회 |
| Stage 5 | `DeliveryStage` | 완성 식판 배달 | ~10회 |

**총 이동 횟수**: `8 + (7 × 서브반찬수) + 11 + 13 + 10`

#### `execute()` 공통 패턴

```python
def execute(self) -> StageResult:
    try:
        if not self._movej(home, "홈 이동"):
            return StageResult.STOPPED      # 비상정지 시 즉시 반환
        self._gripper(100)
        if not self._movej(target, "목표"):
            return StageResult.STOPPED
        ...
        return StageResult.SUCCESS
    except Exception as e:
        self._logger.error(f"오류: {e}")
        return StageResult.ERROR
```

비상정지 시 `_movej()`가 `False`를 반환하면 즉시 `STOPPED`를 반환하여 안전하게 중단합니다.

---

### 4-6. `OrderRepository` — 의존성 역전 (DIP)

**역할**: 주문 저장소를 인터페이스로 추상화 → Firebase / Mock 교체 가능

#### `Order` 데이터클래스

```python
@dataclass
class Order:
    key:          str           # Firebase /orders/{key}
    sub_dishes:   List[str]     # 서브 반찬 목록 (최대 4종)
    main_dish:    str           # 메인 반찬
    target_stage: int = 0       # 시작 스테이지 (0 = 처음부터)
    run_mode:     str = "from"  # "from" = target_stage부터 끝까지
                                # "only" = target_stage만 실행
    status:       str = "pending"
```

```
OrderRepository (ABC)
 ├─ listen_orders(callback)
 ├─ listen_commands(callback)
 ├─ mark_processing(key)
 ├─ mark_completed(key)
 ├─ mark_error(key)
 └─ upload_robot_status(payload)
      │
      ├── FirebaseOrderRepository  ← 실제 운영 환경
      └── MockOrderRepository      ← 테스트 / Firebase 없는 환경
```

`RobotController`는 `OrderRepository` 인터페이스만 알고 있어, Firebase 없이도 동일한 코드로 실행됩니다.

---

### 4-7. 테스트 모드

**역할**: Firebase `/test_command` 경로를 통해 특정 스테이지 또는 시나리오를 독립 실행

#### 테스트 시나리오 목록

| 시나리오 | 메서드 | 설명 |
|----------|--------|------|
| `stage_only` | `_process_test_stages()` | `stage_from` ~ `stage_to` 범위 스테이지 실행 |
| `tong_pick_place` | `_run_tong_pick_place()` | 집게 집기 → 내려놓기만 수행 (Stage3 부분) |
| `main_dish_full` | `_run_main_dish_full()` | MainDishStage 전체 실행 |
| `rice_full` | `_process_test_stages()` | Stage4(밥) 단독 실행 |
| `delivery_full` | `_process_test_stages()` | Stage5(배달) 단독 실행 |

#### 테스트 페이로드 구조

```json
{
  "scenario":   "stage_only",
  "repeat":     1,
  "stage_from": 1,
  "stage_to":   5,
  "main_dish":  "돈까스",
  "sub_dishes": ["피클", "단무지", "김치"]
}
```

- `test_cancel` 명령으로 진행 중인 테스트 중단 → 홈 복귀
- `_test_cancel` (threading.Event)로 루프 내 폴링 방식 취소 처리

---

## 5. DSR Rule 7 — 스레드 안전 규칙

> **DSR API는 반드시 작업 스레드(task thread)에서만 호출해야 한다.**

이 규칙 위반 시 발생하는 문제:
- 잘못된 관절 위치 이동
- DSR 내부 상태 오염
- 예측 불가능한 로봇 동작 → **안전사고**

### 준수 방식

| 호출 시점 | 방법 | 근거 |
|----------|------|------|
| 초기화 (`set_tool`, `set_tcp`, `do_movej(home)`) | `_task_loop()` 첫 부분에서만 실행 | Rule 7 |
| 주문 처리 중 이동 | `_task_loop()` → `_process_order()` → Stage | Rule 7 |
| 웹 명령 (`move_home`, `gripper_*`, `emergency_stop`, 등) | `_cmd_queue.put()` → task thread가 소비 | Rule 7 |
| 일시정지 플래그 (`pause`, `resume`) | 예외적으로 즉시 `pause_event` 조작 | 스테이지 즉시 블로킹 필요 |
| 비상정지 실제 정지 (`do_stop`) | `pause_stop` 큐 경유 → task thread 실행 | Rule 7 |

---

## 6. 주요 버그 수정 이력

| # | 위치 | 버그 | 수정 |
|---|------|------|------|
| 1 | `robot_controller.py` | `self.rc.stop()` — 존재하지 않는 메서드 호출 | `self.rc.do_stop()` |
| 2 | `robot_controller.py` | `start()` 에서 DSR API 직접 호출 (Rule 7 위반) | `_task_loop()` 내부로 이전 |
| 3 | `robot_controller.py` | Firebase 콜백에서 `do_movej/set_gripper` 직접 호출 (Rule 7 위반) | `_cmd_queue.put()` 위임 |
| 4 | `lunchbox_robot_node.py` | `inject()` 누락 인자 (`check_motion`, `move_stop`, `get_robot_state`) | 전체 인자 보완 |
| 5 | `lunchbox_robot_node.py` | `DSR_ROBOT2` import 가 노드 생성 이전에 위치 | 노드 생성 이후로 이동 |
| 6 | `base_stage.py` | `from rclpy.logging import get_logger` 중복 import | 중복 제거 |
| 7 | `robot_controller.py` | `"대 기 중"` — 숨겨진 문자로 인한 깨진 문자열 | `"대기 중"` 으로 수정 |

---

## 7. 코딩 규칙 준수 현황

### 전체 파일 적용 항목

| 규칙 | 내용 | 적용 전 | 적용 후 |
|------|------|---------|---------|
| 로거 | `print()` 대신 ROS2 로거 사용 | `print("완료")` | `_logger.info("완료")` |
| 상수 | magic number 제거 | `time.sleep(2.0)` | `time.sleep(GRIPPER_SETTLE_SEC)` |
| 타입 힌트 | 주요 메서드 반환 타입 명시 | `def upload_status(self, p):` | `def upload_status(self, p) -> None:` |
| 비동기 대기 | 공식 check_motion 패턴 | `time.sleep(5)` | `wait_motion_done()` |
| 비상정지 | 올바른 감속정지 | `move_stop(0)` | `move_stop(3)` |

### 파일별 로거 설정

| 파일 | 로거 이름 | 방식 |
|------|-----------|------|
| `robot_controller.py` | 노드 이름 | `self.node.get_logger()` |
| `robot_client.py` | `'robot_client'` | 모듈 레벨 `_logger` |
| `state_manager.py` | `'state_manager'` | 모듈 레벨 `_logger` |
| `coordinate_manager.py` | `'coordinate_manager'` | 모듈 레벨 `_logger` |
| `stages/base_stage.py` | 스테이지 이름 | `get_logger(name)` |
| `repositories/firebase_*.py` | `'firebase_order_repository'` | 모듈 레벨 `_logger` |
| `repositories/mock_*.py` | `'mock_order_repository'` | 모듈 레벨 `_logger` |
| `lunchbox_robot_node.py` | `'lunchbox_robot_node'` | 모듈 레벨 `_logger` (finally용) |

---

## 8. 데이터 흐름 분석

### 주문 처리 전체 흐름

```
1. Firebase /orders/{key} 변경 감지
         │
2. FirebaseOrderRepository.listen_orders() 콜백 호출
         │
3. RobotController._on_order_received(order)
   ├─ is_order_processed(key) → True이면 무시 (중복 방지)
   ├─ mark_order_processed(key)
   └─ _order_queue.put(order)
         │
4. task_thread._process_order(order)
   ├─ valid_subs 필터링 (최대 4종, YAML에 좌표 있는 것만)
   ├─ total_steps 계산: 8 + (7×n) + 11 + 13 + 10
   ├─ sm.reset_progress(total_steps)
   ├─ repo.mark_processing(key)
   ├─ Stage 1~5 순차 실행
   └─ 완료: repo.mark_completed(key) / 실패: repo.mark_error(key)
         │
5. status_upload_thread → 1초마다 sm.get_status_dict() → Firebase /robot_status
```

### 명령 처리 흐름

```
Firebase /command 변경
         │
FirebaseOrderRepository 콜백
         │
RobotController._on_command_received(cmd)
         │
_handle_command(cmd)
    ├─ "pause"          → sm.set_pause() + sm.update_status("⏸️ 일시 정지됨") [즉시]
    │                     + _cmd_queue.put("pause_stop")
    ├─ "resume"         → sm.clear_pause() + sm.clear_emergency_stop()             [즉시]
    └─ "move_home" / "gripper_*" / "emergency_stop" / 나머지 → _cmd_queue.put(cmd)  [위임]
                                          │
                               task_thread._execute_cmd(cmd)
                                          │
                               rc.do_movej() or rc.set_gripper()     [DSR 호출]
```

---

## 9. 충돌 감지 메커니즘

`_collision_monitor_loop`는 0.3초마다 외력/토크를 측정하여 임계값 초과 시 비상정지를 트리거합니다.

| 파라미터 | 임계값 | 설명 |
|----------|--------|------|
| `COLLISION_THRESHOLD` | 80.0 | 로봇 상태값 기반 임계 |
| `FORCE_THRESHOLD` | 80.0 N | `get_tool_force()` XYZ 합산 |
| `FORCE_Z_THRESHOLD` | 60.0 N | Z축 외력 단독 |

```
_collision_monitor_loop (0.3초 주기)
    │
    ├─ rc.get_robot_state() ∈ {3,5,6,7} (collision states)
    │   └─ sm.trigger_emergency_stop() + Firebase 'collision' 상태 업로드
    │
    └─ rc.get_tool_force() 또는 get_external_torque() 임계값 초과
        └─ sm.trigger_emergency_stop() + last_failed_order 보존
```

---

## 10. 설계 강점과 개선 여지

### 강점

| 항목 | 내용 |
|------|------|
| 의존성 역전 | `OrderRepository` 인터페이스로 Firebase/Mock 교체 자유 |
| 의존성 주입 | `RobotClient.inject()`로 DSR 함수 주입 → 단위 테스트 가능 |
| 스레드 안전 | `RLock` 기반 상태 관리, `threading.Event` 기반 초기화/일시정지 동기화 |
| Rule 7 준수 | 모든 DSR 호출을 작업 스레드에 격리 |
| 일시정지/재개 | `pause_event` 기반 → 스테이지 루프 내 `wait_if_paused()`로 즉시 블로킹 |
| 충돌 복구 | `reset_and_restart` 명령으로 하드웨어 복구 + 실패 주문 1단계부터 재시작 |
| 외력 감지 | `get_tool_force` / `get_external_torque` 기반 세밀한 충돌 감지 |
| 로그 표준화 | 전체 파일 ROS2 logger 통일, 모듈별 이름 부여 |

### 개선 여지

| 항목 | 현황 | 제안 |
|------|------|------|
| 스테이지 단위 테스트 | YAML 좌표 의존으로 미커버 | 좌표를 픽스처로 주입하는 구조 개선 |
| `total_steps` 하드코딩 | `8 + (7×n) + 11 + 13 + 10` | 각 Stage가 자신의 스텝 수를 선언하는 구조 |
| 주문 타임아웃 | 무제한 대기 | 최대 처리 시간 상한 설정 |

---

## 11. 테스트 커버리지 현황

```
cobot1/
├── robot_client.py          ██████████ 100% (26 테스트)
├── state_manager.py         ██████████ 100% (28 테스트)
├── repositories/
│   └── mock_*.py            ██████████ 100% (12 테스트)
├── robot_controller.py      ████████░░  80% (26 테스트, 루프 제외)
├── stages/
│   ├── base_stage.py        ░░░░░░░░░░   0% (통합 테스트 필요)
│   └── stages.py            ░░░░░░░░░░   0% (통합 테스트 필요)
├── coordinate_manager.py    ░░░░░░░░░░   0% (YAML 파일 의존)
└── lunchbox_robot_node.py   ░░░░░░░░░░   0% (ROS2 런타임 필요)
```

**단위 테스트 미커버 범위 이유**:

| 모듈 | 이유 |
|------|------|
| `stages/` | YAML 좌표 + RobotClient 완전 동작 필요 → 통합 테스트 범주 |
| `coordinate_manager.py` | `robot_coordinates.yaml` 파일 의존 |
| `lunchbox_robot_node.py` | ROS2 노드 생성 + DSR 연결 필요 |
| `robot_controller._task_loop` | 스레드 루프 + DSR 초기화 → E2E 테스트 범주 |
