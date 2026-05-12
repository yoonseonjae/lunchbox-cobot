# 나만의 도련님 도시락 🍱

**Doosan M0609 협동로봇 + RG2 그리퍼**를 활용한 무인 도시락 자동 조립 시스템입니다.
웹앱 주문 → Firebase → ROS2 → 5단계 로봇 동작 → 픽업까지의 전체 파이프라인을 구현합니다.
별도의 아두이노, 외부 센서, 카메라 비전(YOLO 등) 없이 **로봇 본체의 다양한 툴과 기능만으로** 동작하는 것이 특징입니다.

## 문서

| 문서 | 설명 |
|------|------|
| [실행 가이드](docs/RUN_GUIDE.md) | Terminal 1~5 순서별 실행 명령어 및 비상정지 |
| [시스템 플로우차트](docs/SYSTEM_FLOWCHART.md) | 전체 시스템 구성 및 데이터 흐름 다이어그램 |
| [시퀀스 다이어그램](docs/SEQUENCE_DIAGRAM.md) | 주문 접수부터 완료까지 단계별 시퀀스 |
| [아키텍처](docs/ARCHITECTURE.md) | 패키지 계층 구조 및 컴포넌트 상세 분석 |
| [토크 분류 알고리즘](docs/torque_classification_report.md) | J2 기반 페이로드 분류 알고리즘 |
| [테스트 리포트](docs/TEST_REPORT.md) | 단위 테스트 결과 (92/92 PASS) |

---

## 시스템 구조

```
cobot_ws/src/
├── cobot1/                      # ROS2 메인 패키지
│   ├── cobot1/
│   │   ├── lunchbox_robot_node.py        # 진입점 (의존성 주입 & 조립)
│   │   ├── lunchbox_database_node.py     # Firestore ↔ ROS2 브릿지
│   │   ├── robot_controller.py           # 4개 스레드 통합 컨트롤러
│   │   ├── robot_client.py               # DSR API 래퍼 (락 직렬화)
│   │   ├── state_manager.py              # 중앙 상태 관리 (스레드 안전)
│   │   ├── coordinate_manager.py         # YAML 좌표 로드
│   │   ├── torque_classifier.py          # J2 기반 페이로드 분류기
│   │   ├── robot_dashboard.py            # 3D URDF + SSE 대시보드
│   │   ├── camera_stream_server.py       # USB 카메라 MJPEG 스트리밍
│   │   ├── mini_jog.py                   # 수동 조그(좌표 기록용)
│   │   ├── move_basic.py                 # 단순 이동 테스트
│   │   ├── repositories/
│   │   │   ├── order_repository.py       # OrderRepository 인터페이스 (ABC)
│   │   │   ├── firebase_order_repository.py  # Firebase RTDB 구현체
│   │   │   └── mock_order_repository.py  # 테스트용 인메모리 구현체
│   │   ├── stages/
│   │   │   ├── base_stage.py             # 스테이지 추상 기본 클래스
│   │   │   └── stages.py                 # 5단계 로봇 동작 구현
│   │   └── config/
│   │       └── robot_coordinates.yaml    # 모든 관절/직선 좌표
│   ├── config/
│   │   └── serviceAccountKey.json        # Firebase 키 (.gitignore)
│   ├── launch/
│   │   └── lunchbox.launch.py
│   ├── test/                             # 단위 테스트 (92개)
│   │   ├── conftest.py                   # DSR/rclpy stub
│   │   ├── test_robot_client.py
│   │   ├── test_state_manager.py
│   │   ├── test_robot_controller.py
│   │   └── test_mock_repository.py
│   └── docs/                             # 문서 + HTML 시각화 자료
│       ├── ARCHITECTURE.md
│       ├── RUN_GUIDE.md
│       ├── SEQUENCE_DIAGRAM.md
│       ├── SYSTEM_FLOWCHART.md
│       ├── TEST_REPORT.md
│       ├── torque_classification_report.md
│       ├── network_architecture.html
│       ├── sequence_diagram.html
│       ├── dashboard.html
│       ├── torque_tester.html
│       ├── motion_sim.py                 # 동기 vs 비동기 모션 비교
│       └── ros2_ws_bridge.py             # ROS2 → WebSocket 브릿지
├── lunchbox_web/                # 관리자/사용자 웹 (ROS2 패키지)
│   ├── admin_index.html                  # 관리자 대시보드
│   └── lunchbox_web/
│       └── user_order_app.py             # Tkinter 데스크탑 주문앱
├── m0609_rg2_combined/          # DSR m0609 + RG2 그리퍼 URDF/메쉬
│   ├── m0609_rg2.urdf
│   └── meshes/                           # DAE/STL 메쉬 파일
└── App.tsx                      # React 사용자 주문앱 (Firebase 연동)
```

---

## 전체 플로우

```
[사용자 주문] App.tsx (React) — Firestore 클라우드에 status: pending 으로 저장
       │
       ▼
[브릿지] lunchbox_database_node
   ├─ Firestore /orders 컬렉션 실시간 감시 (on_snapshot)
   ├─ 메뉴 이름을 main_dish / sub_dishes로 분류
   ├─ /robot_order ROS2 토픽으로 발행
   └─ Firestore 상태를 즉시 'cooking'으로 업데이트
       │
       ▼
[로봇 제어] lunchbox_robot_node (RobotController)
   ├─ ros_spin_thread       : ROS2 MultiThreadedExecutor 실행
   ├─ task_thread           : 주문 큐 소비 → Stage 1~5 순차 실행
   ├─ status_upload_thread  : 1초마다 Firebase Realtime DB 상태 업로드
   ├─ collision_monitor     : 1초마다 로봇 충돌 감지 (토크/외력 기반)
   └─ torque_publish_thread : 1초마다 /robot_torque 토픽 발행
       │
       ▼
[5단계 로봇 동작]
  1️⃣ TraySetupStage  : 식판 보관소 → 세팅 장소 (그리퍼 파지/안착)
  2️⃣ SubDishStage    : 서브 반찬 Pick & Place (사용자 선택 최대 3종 반복)
                       - 동기 진입(movej+movel) + 비동기 이송(amovel+amovej, radius blending)
  3️⃣ MainDishStage   : 집게로 메인 반찬 집기
                       - J2 baseline 측정 → 동적 토크 판별로 파지 성공 확인
                       - 실패 시 자동 재시도
  4️⃣ RiceStage       : 스쿱으로 밥 퍼서 식판에 담기
                       - 가변속 특이점 모드(DR_VAR_VEL)로 손목 특이점 통과
  5️⃣ DeliveryStage   : 완성된 식판을 픽업 장소로 배달
                       - 비상정지 재개 시 파지 상태(빈그리퍼/홀더만/홀더+식판) 자동 판별
       │
       ▼
[완료 보고]
   ├─ /robot_status 토픽 발행 (state: idle, current_task: 대기 중)
   ├─ Firebase Realtime DB '/robot_status' 갱신
   └─ lunchbox_database_node가 Firestore 상태를 'done'으로 업데이트
       │
       ▼
[웹앱 실시간 반영] App.tsx의 onSnapshot이 완료 UI 표시 → 픽업 번호 안내
```

---

## 핵심 코드 설명

### `lunchbox_robot_node.py` — 메인 진입점
ROS2 노드 생성 → DSR API 임포트 → 컴포넌트 조립 → `RobotController.start()` 까지만 담당하는 얇은 진입점입니다.
Firebase 서비스 키 존재 여부에 따라 `FirebaseOrderRepository` / `MockOrderRepository` 를 자동 선택합니다.

### `robot_controller.py` — 4개 스레드 통합 컨트롤러
- **ros_spin_thread**: MultiThreadedExecutor 로 ROS2 콜백 처리
- **task_thread**: 주문 큐에서 Order 를 꺼내 Stage 1→5 순차 실행 (★ DSR API 호출은 이 스레드에서만)
- **status_upload_thread**: 1초 주기로 상태를 Firebase + /robot_status 토픽에 발행
- **collision_monitor**: 1초 주기로 로봇 상태(state), TCP 합력, J1~J6 외부 토크 감시
  - 합력 80N / Z축 60N / 단일 관절 80Nm 초과 시 자동 비상정지

**핵심 안전 규칙**: 모션 중에는 `_motion_active` 플래그가 set 되어 모든 read API 호출이 차단됩니다.
이로써 DSR service generator 의 동시 호출 충돌(`generator already executing`)을 원천 차단합니다.

### `robot_client.py` — DSR API 래퍼
모든 DSR_ROBOT2 함수 호출을 `threading.RLock` 으로 직렬화합니다. 그리퍼는 3개 DO 핀 조합으로 5/20/30/50/100mm 폭을 표현하며, 비동기 모션은 `wait_motion_done()` 으로 `check_motion()` 폴링 후 완료 대기합니다.

### `state_manager.py` — 중앙 상태 관리
스레드 안전한 `RobotStateManager` 가 로봇 상태, 진행률, 단계 로그(최대 20개), 비상정지 이벤트, 일시정지 이벤트, 중복 주문 방지 set 을 통합 관리합니다.

### `coordinate_manager.py` — YAML 좌표 로드
`config/robot_coordinates.yaml` 에서 모든 관절/직선 좌표를 읽어 Stage 코드에 제공합니다. 좌표 수정 시 코드 변경 없이 YAML 만 편집하면 됩니다.

### `stages/stages.py` — 5단계 로봇 동작
각 Stage 는 `BaseStage` 를 상속하여 `execute() → StageResult` 패턴으로 구현됩니다.
`STOPPED` 반환 시 안전하게 중단되며, DSR generator 충돌 발생 시 재시도하지 않고 `ERROR` 반환 후 상위에서 처리합니다.

### `torque_classifier.py` — 페이로드 판별
J2 토크 기반 동적 baseline 방식으로 **빈그리퍼 / 집게 / 집게+돈까스 / 책받침 / 책받침+가득식판** 을 외부 센서 없이 구분합니다.
- 메인 반찬 단계에서 집게 들고 측정 → J2 baseline 저장 → 반찬 집은 후 J2 delta 비교로 파지 성공 판별
- 비상정지 재개 시에도 그리퍼 상태를 판별하여 안전하게 복귀

### `lunchbox_database_node.py` — Firebase ↔ ROS2 브릿지
Firestore `orders` 컬렉션의 `status=pending` 문서를 실시간 감시(`on_snapshot`)하여 새 주문 감지 시 `/robot_order` 토픽으로 발행하고 즉시 `cooking` 으로 상태를 변경합니다.

### `robot_dashboard.py` — 모니터링 대시보드
- ROS2 토픽 구독: `/joint_states`, `/error`, `/io/ctrl_box_digital_input_state`, `/robot_disconnection`
- 2초마다 서비스 폴링: `get_current_posx`, `get_robot_mode`, `get_robot_state`, `get_robot_speed_mode`, `get_last_alarm`
- aiohttp HTTP 서버(포트 8080): SSE `/events` 로 0.2초 주기 JSON push + URDF/메쉬 파일 서빙
- 브라우저에서 3D URDF 뷰어 + 6축 게이지 + 토크/속도 바 + 디지털 IO LED + 알람 로그 실시간 표시

### `camera_stream_server.py` — CCTV 스트리밍
Flask 기반으로 USB 카메라 영상을 MJPEG 스트림(포트 5000, `/video_feed`)으로 발행합니다. 관리자 웹의 `<img>` 태그가 직접 src 로 사용합니다.

### `admin_index.html` — 관리자 대시보드
- KPI 카드: 대기/처리중/완료/오류 주문 수
- 실시간 주문 큐 테이블 (강제 완료/삭제 액션)
- 6축 관절 위치 + 그리퍼 + 진행률 원형 차트 + 단계별 로그
- CCTV 라이브 (MJPEG)
- 3D URDF 뷰어 (Three.js + urdf-loader)
- 비상정지 / 일시정지 / 재개 / 1단계부터 재시작 버튼
- 🧪 테스트 모드: 시나리오별 테스트(스테이지 범위, 집게 Pick&Place, 메인반찬 전체, 밥/배달 전체) × 1~10회 반복

---

## 실행 방법

### 사전 준비
```bash
# 의존 패키지 설치
pip install firebase-admin flask opencv-python aiohttp PyYAML

# Firebase 서비스 계정 키 배치 (.gitignore 처리됨, 별도 발급 필요)
cp serviceAccountKey.json ~/cobot_ws/src/cobot1/config/

# doosan-robot2 패키지 클론 (용량 문제로 .gitignore 처리됨)
cd ~/cobot_ws/src
git clone https://github.com/doosan-robotics/doosan-robot2

# 빌드
cd ~/cobot_ws
colcon build --packages-select cobot1 lunchbox_web --symlink-install
source install/setup.bash
```

### 실행 순서 (자세한 내용은 [RUN_GUIDE.md](docs/RUN_GUIDE.md) 참고)

```bash
# Terminal 1 — DSR 드라이버 (로봇 본체 연결 후 가장 먼저 실행)
ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py \
    model:=m0609 mode:=real host:=192.168.137.100 port:=12345

# Terminal 2 — 메인 로봇 제어 노드 (홈 이동 완료 후 다음 단계로)
ros2 run cobot1 lunchbox_robot_node

# Terminal 3 — Firebase ↔ ROS2 브릿지
ros2 run cobot1 lunchbox_database_node

# Terminal 4 — 관리자 웹 대시보드 (3D URDF + SSE)
ros2 run cobot1 robot_dashboard

# Terminal 5 — CCTV 카메라 스트림
ros2 run cobot1 camera_stream_server

# Browser — 관리자 화면
xdg-open ~/cobot_ws/src/lunchbox_web/admin_index.html
```

---

## 환경

| 항목 | 내용 |
|------|------|
| 로봇 | Doosan DSR M0609 |
| 그리퍼 | OnRobot RG2 (DO1/DO2/DO3 핀 제어, 5종 폭) |
| OS | Ubuntu 22.04 |
| ROS2 | Humble |
| 언어 | Python 3.10 |
| 클라우드 DB | Firebase Firestore (주문) + Realtime Database (로봇 상태/명령) |
| 사용자 웹앱 | React + TypeScript + Firebase SDK (배포: rokey-d3991.web.app) |
| 관리자 웹 | 순수 HTML + Three.js + urdf-loader + Firebase SDK |
| 외부 의존성 차단 | 별도 아두이노/센서/카메라 비전/YOLO 사용 안 함 |

---

## 주의사항

- `config/serviceAccountKey.json` 은 `.gitignore` 로 제외됨. Firebase 콘솔에서 별도 발급 필요.
- `doosan-robot2` 패키지는 용량(~479MB) 문제로 제외됨. [공식 레포](https://github.com/doosan-robotics/doosan-robot2) 에서 클론 필요.
- 좌표 수정은 코드가 아니라 `cobot1/config/robot_coordinates.yaml` 만 편집하면 됩니다.
- 좌표 기록은 `ros2 run cobot1 mini_jog` 로 GUI 조그 후 posx/posj 클립보드 복사 기능 사용.
- 모든 DSR API 호출은 **반드시 작업 스레드(task_thread)** 에서만 일어나야 하며, 콜백 스레드에서는 `_cmd_queue` 로 위임합니다.
