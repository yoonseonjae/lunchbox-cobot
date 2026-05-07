# 나만의 도련님 도시락 🍱

**Doosan DSR m0609 협동로봇**을 활용한 자동 도시락 조립 시스템입니다.  
웹앱에서 주문 → Firebase → ROS2 → 실제 로봇 팔 동작까지의 전체 파이프라인을 구현합니다.

---

## 시스템 구조

```
cobot_ws/src/
├── cobot1/                  # ROS2 메인 패키지
│   ├── cobot1/
│   │   ├── lunchbox_robot_node.py      # 메인 진입점 (컴포넌트 조립)
│   │   ├── robot_controller.py         # 스레드 통합 컨트롤러
│   │   ├── robot_client.py             # DSR API 래퍼
│   │   ├── state_manager.py            # 중앙 상태 관리
│   │   ├── coordinate_manager.py       # YAML 좌표 로드
│   │   ├── lunchbox_database_node.py   # Firebase ↔ ROS2 브릿지
│   │   ├── robot_dashboard.py          # 실시간 로봇 상태 모니터링
│   │   ├── camera_stream_server.py     # USB 카메라 MJPEG 스트리밍
│   │   ├── repositories/
│   │   │   ├── firebase_order_repository.py  # Firestore 주문 수신
│   │   │   └── mock_order_repository.py      # 테스트용 목 데이터
│   │   └── stages/
│   │       ├── stages.py               # 5단계 로봇 동작 구현
│   │       └── base_stage.py           # 스테이지 기본 클래스
│   ├── config/
│   │   └── robot_coordinates.yaml      # 관절 좌표 설정
│   └── launch/
│       └── lunchbox.launch.py
├── lunchbox_web/            # 관리자 웹 페이지 (ROS2 패키지)
│   └── admin_index.html
├── m0609_rg2_combined/      # DSR m0609 + RG2 그리퍼 URDF/메쉬
└── App.tsx                  # 사용자 주문 웹앱 (Firebase 연동)
```

---

## 전체 플로우

```
사용자 웹앱 (rokey-d3991.web.app)
  └─ 메뉴 선택 (메인 1 + 서브 최대 3종)
  └─ Firestore orders 컬렉션에 status: pending으로 저장

lunchbox_database_node
  └─ pending 주문 실시간 감지 (on_snapshot)
  └─ 주문 파싱 → /robot_order ROS2 토픽 발행
  └─ Firestore 상태를 즉시 cooking으로 변경

lunchbox_robot_node (RobotController)
  ├─ ros_spin_thread      : ROS2 executor
  ├─ task_thread          : 주문 큐 소비 → 5 Stage 순차 실행
  ├─ status_upload_thread : 1초마다 Firebase 상태 업로드
  └─ collision_monitor    : 0.5초마다 로봇 상태 감시

5단계 로봇 동작 (Stage 1~5)
  1. TraySetupStage  : 식판 보관소 → 세팅 장소
  2. SubDishStage    : 서브 반찬 Pick & Place (반찬마다 실행)
  3. MainDishStage   : 메인 반찬 집게로 집어 올리기 + 소스
  4. RiceStage       : 스쿱으로 밥 퍼서 식판에 담기
  5. DeliveryStage   : 완성된 식판을 픽업 장소로 배달

완료 후
  └─ /order_status 토픽 발행
  └─ lunchbox_database_node가 Firestore 상태를 done으로 업데이트
  └─ 웹앱에 실시간 반영
```

---

## 핵심 코드 설명

### `lunchbox_robot_node.py` — 메인 진입점
컴포넌트들을 조립해 `RobotController`를 시작하는 엔트리포인트.  
Firebase 서비스 키가 있으면 `FirebaseOrderRepository`, 없으면 `MockOrderRepository`를 사용.

### `robot_controller.py` — 스레드 통합 컨트롤러
4개 스레드를 생성·관리:
- `ros_spin_thread`: ROS2 MultiThreadedExecutor 실행
- `task_thread`: 주문 큐에서 Order를 꺼내 Stage 1→5 순차 실행
- `status_upload_thread`: 1초 주기로 현재 상태를 Firebase에 업로드
- `collision_monitor`: 0.5초 주기로 로봇 충돌/오류 상태 감시

### `robot_client.py` — DSR API 래퍼
`movej`, `movel`, `set_digital_output` 등 DSR API를 래핑해 속도/가속도 설정을 중앙화.

### `coordinate_manager.py` — 좌표 관리
`config/robot_coordinates.yaml`에서 각 Stage별 관절 좌표를 로드.  
좌표 수정 시 코드가 아닌 YAML 파일만 편집.

### `lunchbox_database_node.py` — Firebase ↔ ROS2 브릿지
Firestore `orders` 컬렉션의 `status=pending` 문서를 실시간 감시.  
새 주문 감지 시 `main_dish` / `sub_dishes`로 파싱해 `/robot_order` 토픽으로 발행.

### `robot_dashboard.py` — 모니터링 대시보드
ROS2 토픽(`joint_states`, `error`, `digital_io`)을 구독하고  
2초마다 서비스 폴링(`get_current_posx`, `get_robot_mode` 등)으로 상태 수집.  
aiohttp WebSocket 서버(포트 8765)로 웹 대시보드에 실시간 전송.

### `camera_stream_server.py` — CCTV 스트리밍
USB 카메라 영상을 MJPEG 스트림(포트 5000, `/video_feed`)으로 발행.  
웹앱 `<img src="http://<PC_IP>:5000/video_feed">`로 직접 수신.

### `stages/stages.py` — 5단계 동작 구현
각 Stage는 `BaseStage`를 상속해 `execute()` 구현.  
`StageResult.STOPPED` 반환 시 즉시 중단해 안전 정지 보장.

---

## 실행 방법

### 사전 준비
```bash
# Firebase 서비스 계정 키 배치 (gitignore 처리됨, 별도 발급 필요)
cp serviceAccountKey.json ~/cobot_ws/src/cobot1/config/

# 의존 패키지 설치
pip install firebase-admin flask opencv-python aiohttp

# doosan-robot2 패키지 설치 (별도 클론 필요)
# https://github.com/doosan-robotics/doosan-robot2
```

### 실행 순서
```bash
# Terminal 1 — DSR 드라이버
cd ~/cobot_ws && source install/setup.bash
ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py \
    model:=m0609 mode:=real host:=192.168.137.100 port:=12345

# Terminal 2 — 메인 로봇 노드
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 lunchbox_robot_node
# → [Main] ✅ 홈 이동 완료 확인 후

# Terminal 3 — Firebase ↔ ROS2 브릿지  ← 순서 변경
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 lunchbox_database_node

# Terminal 4 — 관리자 웹 대시보드  ← 순서 변경
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 robot_dashboard

# Terminal 5 — 카메라 스트림
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 camera_stream_server

# Browser
xdg-open file:///home/yoon/cobot_ws/src/lunchbox_web/admin_index.html
```

---

## 환경

| 항목 | 내용 |
|------|------|
| 로봇 | Doosan DSR m0609 |
| 그리퍼 | OnRobot RG2 |
| OS | Ubuntu 22.04 |
| ROS2 | Humble |
| 언어 | Python 3.10 |
| DB | Firebase Firestore + Realtime Database |
| 웹앱 | React + Firebase SDK |

---

## 주의사항

- `config/serviceAccountKey.json`은 `.gitignore`로 제외됨. Firebase 콘솔에서 별도 발급 필요.
- `doosan-robot2` 패키지는 용량(~479MB) 문제로 제외됨. [공식 레포](https://github.com/doosan-robotics/doosan-robot2)에서 클론 필요.
