# cobot1 패키지 아키텍처 분석 문서

**작성일**: 2026년 5월 8일  
**최종 수정**: 2026년 5월 12일  
**패키지**: `src/cobot1/` — 나만의 도련님 도시락 로봇 제어 시스템  
**로봇**: Doosan M0609 / ROS2 Humble  
**브랜치**: `end_develop`

---

## 기술 스택

| 분류 | 기술 | 버전 / 상세 |
|------|------|------------|
| **로봇 미들웨어** | ROS2 | Humble Hawksbill |
| **로봇 SDK** | DSR_ROBOT2 (DR_common2) | Doosan Robotics 공식 SDK |
| **로봇 하드웨어** | Doosan M0609 | 6축 협동 로봇, 최대 반경 900mm |
| **언어** | Python | 3.10.12 |
| **DB (모드 A)** | Firebase Realtime Database | 주문 수신 + 상태 업로드 |
| **DB (모드 B)** | Google Firestore | Firestore 브리지 노드 경유 |
| **수치 연산** | NumPy | 토크 분류기 LDA 연산 |
| **설정 관리** | PyYAML | 관절/직선 좌표 YAML 로드 |
| **스레드 동기화** | threading | RLock, Event, Queue |
| **테스트** | pytest | 9.0.3, 168 테스트 |
| **그리퍼** | OnRobot RG2 | DO/DI 핀 기반 제어, 5~100mm |
| **비전** | OpenCV (camera_stream_server) | HTTP MJPEG 스트림 |
| **빌드 시스템** | colcon | ament_python |

---

## 1. 시스템 개요

나만의 도련님 도시락은 **Doosan M0609 협동 로봇**이 도시락을 자동으로 조립하는 시스템입니다.  
웹 주문(Firebase) → 로봇 동작(DSR_ROBOT2) → 상태 피드백(Firebase/ROS2) 의 흐름으로 동작합니다.

### 배포 모드 A — 단일 노드 (Realtime DB)

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

### 배포 모드 B — 2-노드 (Firestore 브리지)

```
고객 웹 주문
    │
    ▼
Firestore (/orders, status=pending)
    │
    ▼
FirebaseBridgeNode          ← lunchbox_database_node.py (별도 프로세스)
(items → main_dish/sub_dishes 분류)
    │  publish                              subscribe
    ▼  /robot_order (String/JSON)           /order_status (String/JSON)
RobotController._on_ros_order_msg()   ──▶  FirebaseBridgeNode.status_callback()
    │                                              │
    ▼                                              ▼
_order_queue → task_thread → Stages         Firestore 상태 업데이트
    │
    ▼
DSR_ROBOT2 API
```

두 모드는 `RobotController`의 ROS2 토픽 구독(`/robot_order`)을 공유하며,  
모드 B에서는 `FirebaseOrderRepository` 대신 ROS2 토픽이 주문 진입점 역할을 합니다.
---

## 2. 패키지 구조

```
src/cobot1/cobot1/
├── lunchbox_robot_node.py       # 진입점 — 모든 컴포넌트 조립
├── lunchbox_database_node.py    # Firestore↔ROS2 브리지 노드 (2-노드 배포 시 별도 실행)
├── robot_controller.py          # 스레드 통합 + 주문/명령/테스트 처리
├── robot_client.py              # DSR API 래퍼 (유일한 DSR 호출 계층)
├── state_manager.py             # 중앙 상태 관리 (스레드 안전, 일시정지 지원)
├── coordinate_manager.py        # YAML 좌표 로드 및 제공
├── torque_classifier.py         # 6축 토크 기반 페이로드 분류기 (LDA + 최근접 중심)
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
│              │  TorqueClassifier    │
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
 ├─ rclpy.init() + create_node("lunchbox_robot_node", namespace="dsr01")
 ├─ DR_init.__dsr__node = node           # DSR에 노드 주입 (필수 순서)
 ├─ from DSR_ROBOT2 import ...           # ← 노드 생성 이후에만 가능 (공식 규칙)
 ├─ set_robot_mode(ROBOT_MODE_AUTONOMOUS)
 ├─ CoordinateManager()                  # YAML 로드 (velocity/acceleration 포함)
 ├─ RobotStateManager()
 ├─ RobotClient(vel, acc).inject(...)    # DSR 함수 전체 주입
 ├─ Firebase 키 파일 존재 여부로 저장소 선택
 │    ├─ 존재 → FirebaseOrderRepository (Realtime DB)
 │    └─ 없음 또는 연결 실패 → MockOrderRepository
 └─ RobotController.start() → controller.join()
```

**inject() 전달 DSR 함수 (현재 코드 기준)**:

| 분류 | DSR 함수 |
|------|----------|
| 이동 | `movej`, `movel`, `amovej`, `amovel`, `mwait` |
| 그리퍼 | `set_digital_output`, `get_digital_input` |
| 제어 | `wait`, `drl_script_stop`, `check_motion`, `get_robot_state` |
| 센서 | `get_tool_force`, `get_external_torque` |
| 좌표 | `posj`, `posx`, `DR_BASE` |
| 순응제어 | `task_compliance_ctrl`, `release_compliance_ctrl` |
| 힘제어 | `set_desired_force`, `release_force` |
| 주기이동 | `move_periodic` |
| 특이점 | `set_singular_handling`, `DR_VAR_VEL`, `DR_AVOID` |

**주요 특징**:
- Firebase 키 파일 부재 또는 연결 실패 시 자동으로 `MockOrderRepository`로 전환
- `finally` 블록에서 노드 소멸 후에도 로깅 가능하도록 모듈 레벨 `_logger` 분리
- `/robot_order` 토픽을 `RobotController`가 구독 → 모드 A/B 모두 수신

---

### 4-2b. `lunchbox_database_node.py` — Firestore↔ROS2 브리지 노드

**역할**: Firestore 주문 감시 → ROS2 토픽 발행 → 로봇 상태를 Firestore에 역기록  
**클래스**: `FirebaseBridgeNode(Node)`  
**배포**: `lunchbox_robot_node.py`와 **별도 프로세스**로 독립 실행

#### 동작 흐름

```
초기화
 ├─ ROS2 노드 'firebase_bridge_node' 생성
 ├─ Publisher: /robot_order (std_msgs/String)   ← 로봇 제어 노드로 주문 전달
 ├─ Subscriber: /order_status (std_msgs/String) ← 로봇 제어 노드에서 상태 수신
 └─ Firestore 초기화 (serviceAccountKey.json)

listen_to_orders()
 ├─ /orders 컬렉션, status=="pending" 필터링 실시간 감시
 └─ 신규 주문(ADDED) 감지 시
     ├─ items 리스트에서 name 필드 추출
     ├─ 서브 반찬 분류: ['김치', '단무지', '피클', '샐러드']
     ├─ 나머지 → main_dish
     ├─ {'_key', 'sub_dishes', 'main_dish'} JSON → /robot_order 발행
     └─ 즉시 Firestore status → 'cooking' (중복 처리 방지)

status_callback(msg)
 ├─ /order_status 토픽 수신
 └─ {'_key', 'status'} 파싱 → Firestore 상태 업데이트
```

#### Firestore vs Realtime DB 비교

| 항목 | `lunchbox_database_node.py` | `FirebaseOrderRepository` |
|------|----------------------------|---------------------------|
| DB 종류 | **Firestore** | **Realtime DB** |
| 주문 진입 | ROS2 `/robot_order` 토픽 | 내부 콜백 직접 호출 |
| 상태 역기록 | `/order_status` 토픽 수신 | `upload_robot_status()` 직접 호출 |
| 주문 필터 | `status=="pending"` Firestore 쿼리 | Firebase 경로 리스너 |
| 항목 분류 | 브리지 노드 내에서 처리 | `RobotController`에서 처리 |

#### 주의 사항
- `CustomJSONEncoder`: Firestore `datetime` 객체를 ISO 문자열로 변환 (현재 미사용 — 분류 단계에서 datetime 필드 제외됨)
- 주석 처리된 코드 블록: 이전 버전의 전체 payload 전달 방식 (datetime 직렬화 오류로 교체됨)

---

### 4-2. `RobotController` — 스레드 오케스트레이터

**역할**: 5개 스레드 생명주기 관리 + 주문/명령/테스트 라우팅

#### 스레드 구조

| 스레드명 | daemon | 역할 | DSR 호출 |
|---------|:------:|------|:--------:|
| `ros_spin` | False | MultiThreadedExecutor.spin() (4 threads) | ❌ |
| `task` | False | 주문 처리 + Stage 실행 + DSR 초기화 + 테스트 시나리오 | ✅ (유일) |
| `status_upload` | True | 1초 주기 Firebase 상태 업로드 + ROS2 토픽 발행 | ❌ |
| `collision_monitor` | True | 0.3초 주기 외력·토크 기반 충돌 감지 | ❌ |
| `torque_pub` | True | 0.1초 주기 외부 토크 `/robot_torque` 토픽 발행 | ❌ |

#### ROS2 발행 토픽 목록

| 토픽 | 타입 | 주기 | 내용 |
|------|------|------|------|
| `/robot_status` | `String` | 1초 | 상태 딕셔너리 JSON |
| `/robot_tcp_posx` | `String` | 1초 | TCP 위치 6축 JSON |
| `/robot_target_posj` | `String` | 1초 | 관절 각도(deg) JSON |
| `/robot_torque` | `String` | 0.1초 | 외부 토크 6축 JSON |
| `/robot_motion_segment` | `String` | 이벤트 | 모션 세그먼트 시작/종료 이벤트 |

#### 초기화 시퀀스

```
start()
 ├─ ros_spin 스레드 시작
 ├─ /robot_order 토픽 구독 등록
 ├─ Firebase 명령 리스너 등록
 ├─ Firebase 테스트 커맨드 리스너 등록 (listen_test_command 지원 시)
 ├─ task / status_upload / collision_monitor / torque_pub 스레드 시작
 │      │
 │      ▼ (task 스레드 내부 — DSR Rule 7)
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
  _on_command_received(cmd_type)
      │
      ├─ "pause"   → sm.set_pause() [즉시]
      │              sm.update_status(IDLE, "⏸️ 일시 정지됨")
      │              _cmd_queue.put("pause_stop")  ← do_stop()은 task 스레드 위임
      │
      ├─ "resume"  → sm.clear_pause() [즉시]
      │              sm.clear_emergency_stop() (비상정지 중이면)
      │              ├─ _in_delivery_stage5 == True
      │              │    → sm.update_status(MOVING, "배달 재개...")
      │              │      _cmd_queue.put("delivery_estop_resume")
      │              └─ 일반 재개
      │                   → sm.update_status(MOVING, "작업 재개 중...")
      │
      └─ 나머지 → _cmd_queue.put(cmd_type)  ← task 스레드에서 _execute_cmd()
```

#### 지원 명령 목록

| 명령 | 처리 방식 | 동작 |
|------|----------|------|
| `emergency_stop` | 큐 위임 | `do_stop()` + 3초 후 홈 복귀 시도 |
| `pause` | 즉시 플래그 + 큐(`pause_stop`) | 일시정지 + `do_stop()` |
| `resume` | 즉시 (Stage5 분기 포함) | 일시정지/비상정지 해제 |
| `reset_and_restart` | 큐 위임 | SetRobotControl 서비스 + 주문 1단계부터 재시작 |
| `delivery_estop_resume` | 큐 위임 | 토크 분류 기반 배달 재개 처리 |
| `move_home` | 큐 위임 | 홈 이동 |
| `gripper_open` | 큐 위임 | 그리퍼 50mm |
| `gripper_close` | 큐 위임 | 그리퍼 5mm |
| `gripper_full_open` | 큐 위임 | 그리퍼 100mm |
| `test_cancel` | 큐 위임 | `_test_cancel` 이벤트 세팅 + `do_stop()` |
| `pause_stop` | 큐 위임 | `do_stop()` (pause의 DSR 호출 부분) |

#### 배달 재개 특수 경로 (`delivery_estop_resume`)

Stage 5 배달 중 비상정지 후 `resume` 수신 시 토크 분류기로 상태를 판별합니다.

```
_handle_delivery_estop_resume()
 ├─ DeliveryStage.execute_after_estop_resume() 호출
 │    ├─ TorqueClassifier로 그리퍼 상태 분류
 │    │    ├─ "빈그리퍼"      → StageResult.STOPPED  (식판 낙하)
 │    │    └─ "집게"/"집게+…" → StageResult.SUCCESS  (홀더 복귀)
 │    └─ 결과 반환
 ├─ STOPPED → last_failed_order를 target_stage=1로 재삽입
 └─ SUCCESS → mark_error + IDLE
```

---

### 4-3. `RobotClient` — DSR API 래퍼

**역할**: DSR_ROBOT2 함수를 직접 호출하는 **유일한 계층**  
**설계 원칙**: 의존성 주입(inject)으로 DSR 함수 수신 → 테스트 가능성 확보

#### inject() 주입 인자 전체 목록

| 인자 | DSR 함수 | 용도 | 필수 |
|------|---------|------|:---:|
| `movej` | `movej` | 관절 동기 이동 | ✅ |
| `movel` | `movel` | 직선 동기 이동 | ✅ |
| `mwait` | `mwait` | 모션 완료 대기 | ✅ |
| `amovej` | `amovej` | 관절 비동기 이동 | ✅ |
| `amovel` | `amovel` | 직선 비동기 이동 | ✅ |
| `set_digital_output` | `set_digital_output` | 그리퍼 DO 핀 제어 | ✅ |
| `get_digital_input` | `get_digital_input` | 그리퍼 DI 핀 읽기 | ✅ |
| `wait` | `wait` | DSR 대기 | ✅ |
| `drl_script_stop` | `drl_script_stop` | 스크립트 정지 | ✅ |
| `check_motion` | `check_motion` | 모션 상태 확인 | ✅ |
| `move_stop` | `move_stop` | 로봇 정지 | ✅ |
| `get_robot_state` | `get_robot_state` | 로봇 상태 조회 | ✅ |
| `get_tool_force` | `get_tool_force` | TCP 외력 6축 (충돌 감지) | ✅ |
| `get_external_torque` | `get_external_torque` | 외부 토크 6축 (충돌·분류) | ✅ |
| `posj` | `posj` | 관절 좌표 생성자 | ✅ |
| `posx` | `posx` | 직선 좌표 생성자 | ✅ |
| `DR_BASE` | `DR_BASE` | 기준 좌표계 상수 | ✅ |
| `task_compliance_ctrl` | `task_compliance_ctrl` | 순응제어 활성화 | 선택 |
| `release_compliance_ctrl` | `release_compliance_ctrl` | 순응제어 해제 | 선택 |
| `set_desired_force` | `set_desired_force` | Z축 힘제어 | 선택 |
| `release_force` | `release_force` | 힘제어 해제 | 선택 |
| `move_periodic` | `move_periodic` | 주기적 이동 | 선택 |
| `set_singular_handling` | `set_singular_handling` | 특이점 회피 | 선택 |
| `DR_VAR_VEL` | `DR_VAR_VEL` | 특이점 속도 상수 | 선택 |
| `DR_AVOID` | `DR_AVOID` | 특이점 회피 상수 | 선택 |

#### 주요 메서드

| 메서드 | 설명 |
|--------|------|
| `do_movej(coords, radius)` | 관절 이동 + mwait |
| `do_movel(coords, radius)` | 직선 이동 + mwait |
| `do_amovej(coords, radius)` | 관절 비동기 이동 (mwait 없음) |
| `do_amovel(coords, radius)` | 직선 비동기 이동 (mwait 없음) |
| `do_mwait()` | DSR mwait() 직접 호출 |
| `set_gripper(width_mm)` | DO 핀 조합으로 그리퍼 제어 |
| `get_gripper()` | DI 핀 읽어 현재 그리퍼 폭 반환 |
| `check_grip()` | DI1 핀으로 파지 확인 (오류 시 True fallback) |
| `get_tool_force()` | TCP 외력 6축 반환 (DR_BASE 기준) |
| `get_external_torque()` | 외부 토크 6축 반환 |
| `do_stop()` | 감속 정지 (`move_stop(3)`) |
| `get_robot_state()` | 로봇 상태 정수 반환 |
| `wait_motion_done(stop_check)` | 폴링 기반 완료 대기, stop_check로 즉시 탈출 가능 |
| `start_compliance_ctrl(stx)` | 순응제어 활성화 (기본 stx: [1000,1000,500,100,100,100]) |
| `stop_compliance_ctrl()` | 순응제어 해제 |
| `set_force_ctrl(fd_z)` | Z축 힘제어 (기본 -10.0N) |
| `release_force_ctrl()` | 힘제어 해제 |
| `do_move_periodic(amp, period_ms, atime, count)` | 주기적 이동 |
| `do_set_singular_handling(enable)` | 특이점 회피 ON/OFF |

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
def wait_motion_done(self, stop_check=None) -> bool:
    time.sleep(MOTION_START_DELAY_SEC)    # 0.2초: Busy 상태 진입 대기
    while self._drs_check_motion() != 0:  # 0=Idle, 1=Init, 2=Busy
        if stop_check and stop_check():   # 비상정지 감지 시 즉시 탈출
            return False
        time.sleep(MOTION_CHECK_INTERVAL_SEC)  # 0.1초 폴링
        if not rclpy.ok():
            return False   # 프로세스 종료 시 탈출
    return True
```

---

### 4-5. `TorqueClassifier` — 토크 기반 페이로드 분류기

**역할**: Stage 5 배달 중 비상정지 후 그리퍼 상태(페이로드)를 6축 토크 벡터로 분류  
**파일**: `torque_classifier.py`  
**알고리즘**: 자세 감지 → 자세별 LDA + 최근접 중심 결합

#### 분류 클래스

| 클래스 | 설명 | 사용 경로 |
|--------|------|----------|
| `빈그리퍼` | 그리퍼가 비어있음 (식판 낙하) | Stage 5 비상정지 재개 → 주문 재시작 |
| `집게` | 집게만 파지 | Stage 3 메인반찬 분류 |
| `집게+돈까스` | 집게 + 메인반찬 파지 | Stage 3 메인반찬 분류 |
| `책받침` | 책받침만 파지 | Stage 5 비상정지 재개 → 홀더 복귀 |
| `책받침+가득식판` | 책받침 + 가득한 식판 | Stage 5 비상정지 재개 → 홀더 복귀 |

#### 분류 알고리즘

```
predict_class(torque_array: List[float]) → str

1. J2(2번째 축) 부호로 자세 판별
   J2 < 0 → 자세1 (_LDA_POSE1 사용)
   J2 > 0 → 자세2 (_LDA_POSE2 사용)

2. 자세별 2-Stage LDA
   Step A: 빈그리퍼(양성) vs 집게류(음성) — LDA 투영 + 임계값
     점수 ≥ 임계값 → "빈그리퍼" 반환

   Step B: 집게(음성) vs 집게+돈까스(양성)
     점수 ≥ 임계값 → "집게+돈까스"
     점수 <  임계값 → "집게"
```

`get_classifier()` 싱글톤으로 제공됩니다.  
`BaseStage`에서 `from ..torque_classifier import get_classifier`로 임포트합니다.

---

### 4-5. `RobotStateManager` — 중앙 상태 관리

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

### 4-6. `BaseStage` + 5개 스테이지

**역할**: 로봇 동작 시퀀스를 스테이지 단위로 캡슐화

#### 스테이지 구성

| 스테이지 | 클래스 | 동작 | 이동 횟수 |
|---------|--------|------|:---------:|
| Stage 1 | `TraySetupStage` | 식판 보관소 → 세팅 장소 (순응+힘제어 사용) | ~8회 |
| Stage 2 | `SubDishStage` | 서브 반찬 Pick & Place (slot_index, seg_publish_fn 파라미터) | ~7회/종 |
| Stage 3 | `MainDishStage` | 메인 반찬 + 소스 | ~11회 |
| Stage 4 | `RiceStage` | 밥 스쿱 | ~13회 |
| Stage 5 | `DeliveryStage` | 완성 식판 배달 + `execute_after_estop_resume()` | ~10회 |

**총 이동 횟수**: `8 + (7 × 서브반찬수) + 11 + 13 + 10`

#### `_movej` / `_movel` 공통 재시도 패턴

```python
def _movej(self, coords, label="", radius=None) -> bool:
    if not self._ok(): return False
    while True:
        self.sm.wait_if_paused()      # 일시정지 시 블로킹
        if not self._ok(): return False
        try:
            time.sleep(0.05)          # API 냉각 시간
            self.rc.do_movej(coords, radius=radius)
            break
        except Exception as e:
            if "generator already executing" in str(e):
                time.sleep(0.5); continue    # DSR 충돌 → 재시도
            if self.sm.is_paused():
                self.sm.wait_if_paused(); continue
            self._logger.error(f"_movej 오류: {e}")
            return False
    if label: self._tick(label)
    return self._ok()
```

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

#### `seg_publish_fn` 모션 세그먼트 알림

`BaseStage.__init__`에 `seg_publish_fn: Optional[Callable[[dict], None]]` 파라미터를 받아  
`SubDishStage` 등에서 각 모션 세그먼트 시작/종료를 `/robot_motion_segment` 토픽으로 발행합니다.

```python
# RobotController에서 주입
SubDishStage(..., slot_index=idx, seg_publish_fn=self._seg_publish)

# 형식
{"type": "seg_start" | "seg_end", "seg_id": str, ...}
```

---

### 4-7. `OrderRepository` — 의존성 역전 (DIP)

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
 ├─ listen_test_command(callback)   ← FirebaseOrderRepository만 지원
 ├─ mark_processing(key)
 ├─ mark_completed(key)
 ├─ mark_error(key)
 └─ upload_robot_status(payload)
      │
      ├── FirebaseOrderRepository  ← 실제 운영 (Realtime DB)
      └── MockOrderRepository      ← 테스트 / Firebase 없는 환경
```

`RobotController`는 `OrderRepository` 인터페이스만 알고 있어, Firebase 없이도 동일한 코드로 실행됩니다.

---

### 4-8. 테스트 모드

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
| 비상정지 실제 정지 (`do_stop`) | `pause_stop` 큐 경유 → task 스레드 실행 | Rule 7 |
| 충돌 감지 후 정지 | `collision_monitor` → `_cmd_queue.put("emergency_stop")` | Rule 7 |

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

### 주문 처리 흐름 — 모드 A (Realtime DB, 단일 노드)

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

### 주문 처리 흐름 — 모드 B (Firestore, 2-노드)

```
[lunchbox_database_node.py 프로세스]

1. Firestore /orders (status=="pending") 실시간 감시 (on_snapshot)
         │ ADDED 이벤트
2. items 리스트 파싱 → main_dish / sub_dishes 분류
3. {'_key', 'sub_dishes', 'main_dish'} JSON → /robot_order 토픽 발행
4. Firestore /orders/{id} status → 'cooking' (즉시, 중복 방지)

[lunchbox_robot_node.py 프로세스]

5. RobotController._on_ros_order_msg(msg) ← /robot_order 토픽 수신
   └─ JSON 파싱 → Order 객체 생성 → _order_queue.put(order)
         │
6. task_thread._process_order(order) → Stage 1~5 순차 실행
         │
7. 처리 완료/실패 시 /order_status 토픽 발행
   └─ {'_key': doc_id, 'status': 'completed' | 'error'}

[lunchbox_database_node.py 프로세스]

8. status_callback() ← /order_status 토픽 수신
   └─ Firestore /orders/{id} status 업데이트
```

### 명령 처리 흐름

```
Firebase /command 변경
         │
FirebaseOrderRepository 콜백
         │
RobotController._on_command_received(cmd)
         │
    ├─ "pause"   → sm.set_pause() + sm.update_status("⏸️ 일시 정지됨") [즉시]
    │              + _cmd_queue.put("pause_stop")
    ├─ "resume"  → sm.clear_pause() [즉시] (또는 delivery_estop_resume 큐 삽입)
    └─ 나머지  → _cmd_queue.put(cmd)  [위임]
                        │
              task_thread._execute_cmd(cmd)
                        │
              rc.do_movej() / rc.set_gripper() / DeliveryStage.execute_after_estop_resume()
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
| 배달 재개 | `TorqueClassifier`로 그리퍼 상태 판별 → 상황별 분기 복구 |
| 외력 감지 | 하드/소프트 이중 충돌 감지 (상태 코드 + 힘/토크 임계값) |
| 순응/힘제어 | Stage 1 식판 접촉 시 `start_compliance_ctrl()` + `set_force_ctrl()` 자동 적용 |
| 자동 재시도 | `BaseStage._movej/_movel`의 `generator already executing` 재시도 패턴 |
| 로그 표준화 | 전체 파일 ROS2 logger 통일, 모듈별 이름 부여 |

### 개선 여지

| 항목 | 현황 | 제안 |
|------|------|------|
| 스테이지 단위 테스트 | YAML 좌표 의존으로 미커버 | 좌표를 픽스처로 주입하는 구조 개선 |
| `total_steps` 하드코딩 | `8 + (7×n) + 11 + 13 + 10` | 각 Stage가 자신의 스텝 수를 선언하는 구조 |
| 주문 타임아웃 | 무제한 대기 | 최대 처리 시간 상한 설정 |
| `inject()` 중복 인자 | `lunchbox_robot_node.py`에서 `drl_script_stop`이 두 번 전달됨 | `move_stop` 인자 위치 수정 필요 |

---

## 11. 테스트 커버리지 현황

```
cobot1/
├── robot_client.py           ██████████ 100% (46 테스트)
├── state_manager.py          ██████████ 100% (63 테스트)
├── repositories/
│   ├── order_repository.py   ██████████ 100% (21 테스트, Order/ABC)
│   └── mock_*.py             ██████████ 100% (12 테스트)
├── robot_controller.py       ████████░░  80% (26 테스트, 루프 제외)
├── torque_classifier.py      ░░░░░░░░░░   0% (NumPy + 실측 데이터 의존)
├── stages/
│   ├── base_stage.py         ░░░░░░░░░░   0% (통합 테스트 필요)
│   └── stages.py             ░░░░░░░░░░   0% (통합 테스트 필요)
├── coordinate_manager.py     ░░░░░░░░░░   0% (YAML 파일 의존)
├── lunchbox_robot_node.py    ░░░░░░░░░░   0% (ROS2 런타임 필요)
└── lunchbox_database_node.py ░░░░░░░░░░   0% (Firestore + ROS2 런타임 필요)
```

**단위 테스트 미커버 범위 이유**:

| 모듈 | 이유 |
|------|------|
| `stages/` | YAML 좌표 + RobotClient 완전 동작 필요 → 통합 테스트 범주 |
| `torque_classifier.py` | 실측 토크 데이터 (NumPy) + 로봇 연결 필요 |
| `coordinate_manager.py` | `robot_coordinates.yaml` 파일 의존 |
| `lunchbox_robot_node.py` | ROS2 노드 생성 + DSR 연결 필요 |
| `lunchbox_database_node.py` | Firestore 인증 + ROS2 런타임 필요 |
| `robot_controller._task_loop` | 스레드 루프 + DSR 초기화 → E2E 테스트 범주 |
