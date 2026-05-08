# cobot1 패키지 아키텍처 분석 문서

**작성일**: 2026년 5월 8일  
**패키지**: `src/cobot1/` — 나만의 도련님 도시락 로봇 제어 시스템  
**로봇**: Doosan M0609 / ROS2 Humble  
**브랜치**: `ksw_develop`

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

---

## 2. 패키지 구조

```
src/cobot1/cobot1/
├── lunchbox_robot_node.py       # 진입점 — 모든 컴포넌트 조립
├── robot_controller.py          # 스레드 통합 + 주문/명령 처리
├── robot_client.py              # DSR API 래퍼 (유일한 DSR 호출 계층)
├── state_manager.py             # 중앙 상태 관리 (스레드 안전)
├── coordinate_manager.py        # YAML 좌표 로드 및 제공
├── stages/
│   ├── base_stage.py            # 스테이지 추상 기본 클래스
│   └── stages.py                # 5개 스테이지 구현체
├── repositories/
│   ├── order_repository.py      # OrderRepository 인터페이스
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
| `ros_spin` | False | ROS2 executor.spin() | ❌ |
| `task` | False | 주문 처리 + Stage 실행 + DSR 초기화 | ✅ (유일) |
| `status_upload` | True | 1초 주기 Firebase 상태 업로드 | ❌ |
| `collision_monitor` | True | 0.5초 주기 로봇 충돌 상태 감시 | ❌ |

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
  _on_command_received("gripper_open")
      │
      ▼
  _handle_command("gripper_open")
      │
      ├─ "emergency_stop" → rc.do_stop() 즉시 실행 (안전 우선)
      │
      └─ "move_home" / "gripper_*"
              │
              ▼
         _cmd_queue.put("gripper_open")  ← 큐에만 삽입
              │
              ▼ (task 스레드가 꺼냄)
         _execute_cmd("gripper_open")
              │
              ▼
         rc.set_gripper(50)  ← 작업 스레드에서만 DSR 호출
```

---

### 4-3. `RobotClient` — DSR API 래퍼

**역할**: DSR_ROBOT2 함수를 직접 호출하는 **유일한 계층**  
**설계 원칙**: 의존성 주입(inject)으로 DSR 함수 수신 → 테스트 가능성 확보

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
         │  MOVING  │      │  EMERGENCY_STOP  │
         └────┬─────┘      └──────────────────┘
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
    step_log:     List[StepLog] # 최근 20개 단계 로그
    collision_detected: bool    # 충돌 감지 여부
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
| 웹 명령 (`move_home`, `gripper_*`) | `_cmd_queue.put()` → task thread가 소비 | Rule 7 |
| 비상정지 (`emergency_stop`) | 예외적으로 즉시 실행 (`do_stop`) | 안전 우선 |

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
    ├─ "emergency_stop" → rc.do_stop() + sm.trigger_emergency_stop()  [즉시]
    ├─ "resume"         → sm.clear_emergency_stop()                   [즉시]
    └─ "move_home" / "gripper_*" → _cmd_queue.put(cmd)               [위임]
                                          │
                               task_thread._execute_cmd(cmd)
                                          │
                               rc.do_movej() or rc.set_gripper()     [DSR 호출]
```

---

## 9. 설계 강점과 개선 여지

### 강점

| 항목 | 내용 |
|------|------|
| 의존성 역전 | `OrderRepository` 인터페이스로 Firebase/Mock 교체 자유 |
| 의존성 주입 | `RobotClient.inject()`로 DSR 함수 주입 → 단위 테스트 가능 |
| 스레드 안전 | `RLock` 기반 상태 관리, `threading.Event` 기반 초기화 동기화 |
| Rule 7 준수 | 모든 DSR 호출을 작업 스레드에 격리 |
| 단계별 중단 | 비상정지 시 `_movej()` → `False` → `STOPPED` 즉시 반환 |
| 로그 표준화 | 전체 파일 ROS2 logger 통일, 모듈별 이름 부여 |

### 개선 여지

| 항목 | 현황 | 제안 |
|------|------|------|
| `_handle_command` vs `_execute_cmd` 이중화 | move_home/gripper 로직이 양쪽에 중복 | `_handle_command`에서 항상 큐 위임으로 통일 |
| 스테이지 단위 테스트 | YAML 좌표 의존으로 미커버 | 좌표를 픽스처로 주입하는 구조 개선 |
| 충돌 감지 후 처리 | 상태 업데이트만 수행 | 자동 비상정지 연동 고려 |
| `total_steps` 하드코딩 | `8 + (7×n) + 11 + 13 + 10` | 각 Stage가 자신의 스텝 수를 선언하는 구조 |
| 주문 타임아웃 | 무제한 대기 | 최대 처리 시간 상한 설정 |

---

## 10. 테스트 커버리지 현황

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
