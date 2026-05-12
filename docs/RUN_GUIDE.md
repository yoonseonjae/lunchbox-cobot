# 나만의 도련님 도시락 🍱 — 실행 가이드

## 사전 준비

```bash
# 1) 의존 Python 패키지 설치
pip install firebase-admin flask opencv-python aiohttp PyYAML

# 2) Firebase 서비스 계정 키 배치 (.gitignore 처리됨 — 별도 발급 필요)
cp serviceAccountKey.json ~/cobot_ws/src/cobot1/config/

# 3) doosan-robot2 패키지 (용량 큼, .gitignore 처리됨)
cd ~/cobot_ws/src
git clone https://github.com/doosan-robotics/doosan-robot2

# 4) 빌드
cd ~/cobot_ws
colcon build --packages-select cobot1 lunchbox_web --symlink-install
source install/setup.bash
```

> **메모**: `--symlink-install` 옵션 덕분에 Python 파일 수정 시 재빌드 불필요. 노드만 재시작하면 됩니다.

---

## 실행 순서

> **주의**: 각 터미널에서 반드시 `source install/setup.bash` 를 먼저 실행하세요.
> 이전 터미널이 완전히 뜬 것을 확인한 후 다음 터미널로 넘어가세요.

---

### Terminal 1 — DSR 로봇 드라이버

> 로봇 본체 전원 ON 및 네트워크 연결 확인 후 가장 먼저 실행

```bash
cd ~/cobot_ws && source install/setup.bash
ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py \
    model:=m0609 mode:=real host:=192.168.137.100 port:=12345
```

| 항목 | 값 |
|---|---|
| 로봇 IP | `192.168.137.100` (환경에 맞게 수정) |
| 포트 | `12345` |
| 성공 신호 | `dsr_bringup2` 노드 기동 완료 + RViz 창에 로봇 표시 |

---

### Terminal 2 — 메인 로봇 제어 노드

> Terminal 1 드라이버가 완전히 뜬 후 실행

```bash
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 lunchbox_robot_node
```

**✅ 다음 로그 확인 후 Terminal 3 으로 넘어갈 것:**
```
[lunchbox_robot_node] 노드 'dsr01/lunchbox_robot_node' 생성
[coordinate_manager] 설정 로드 완료: .../robot_coordinates.yaml
[robot_controller] spin 스레드 시작, 0.5s 안정화 대기
[robot_controller] /robot_order 토픽 구독 등록
[firebase_order_repository] ✅ Firebase 초기화 완료
[firebase_order_repository] /orders 리스너 등록
[firebase_order_repository] /command 리스너 등록
[firebase_order_repository] /test_command 리스너 등록
[robot_client] 그리퍼 100mm 설정
[robot_controller] ✅ 홈 이동 완료
[robot_controller] 홈 이동 완료 — 모니터 스레드 시작
[robot_controller] ✅ 모든 스레드 시작 완료
```

> ⚠️ **홈 이동 실패 시**: 30초 타임아웃으로 자동 종료됩니다. 로봇 모드, TCP/Tool 설정, 작업영역 장애물을 확인하세요.

---

### Terminal 3 — Firebase ↔ ROS2 브릿지 노드

> 주문 수신 → `/robot_order` 토픽 발행 담당

```bash
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 lunchbox_database_node
```

**✅ 성공 로그:**
```
✅ Firebase Admin SDK 초기화 성공!
🚀 Firestore 감시 모드 작동 중...
```

이 노드가 켜져 있어야 사용자 웹앱에서 보낸 주문이 로봇에 도달합니다.

---

### Terminal 4 — 관리자 웹 대시보드 (3D URDF + SSE)

> 3D URDF 뷰어 + 관절 실시간 + 토크/속도/IO 모니터링

```bash
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 robot_dashboard
```

**✅ 성공 로그:**
```
==================================================
  DSR M0609 Web Dashboard
  http://localhost:8080
  http://localhost:8080/state  (JSON 직접 확인)
==================================================
```

| 항목 | 값 |
|---|---|
| 대시보드 URL | `http://localhost:8080` |
| URDF 파일 | `http://localhost:8080/urdf/m0609_rg2.urdf` |
| 메쉬 디렉토리 | `http://localhost:8080/urdf/meshes/...` |
| SSE 스트림 | `http://localhost:8080/events` (0.2초 주기) |
| JSON API | `http://localhost:8080/state` |

---

### Terminal 5 — CCTV 카메라 스트리밍

```bash
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 camera_stream_server
```

옵션 지정 시:
```bash
ros2 run cobot1 camera_stream_server --camera 0 --port 5000 --width 1280 --height 720 --fps 20 --quality 70
```

**✅ 성공 로그:**
```
============================================================
  📷 도련님 도시락 - 카메라 스트리밍 서버
============================================================
  카메라 인덱스 : 0
  해상도        : 1280x720
  목표 FPS      : 20
  JPEG 품질     : 70
  HTTP 포트     : 5000
============================================================
[Camera] 해상도: 1280x720

📺 미리보기 : http://localhost:5000/
📡 스트림 URL: http://<내PC_IP>:5000/video_feed
🛑 종료      : Ctrl+C
```

| 엔드포인트 | 용도 |
|---|---|
| `http://localhost:5000/` | 브라우저 미리보기 |
| `http://localhost:5000/video_feed` | MJPEG 스트림 (관리자 웹의 `<img src>` 가 사용) |
| `http://localhost:5000/snapshot` | 단일 JPEG 스냅샷 |

---

### Browser — 관리자 화면 열기

```bash
xdg-open ~/cobot_ws/src/lunchbox_web/admin_index.html
```

또는 브라우저 주소창에 직접 입력:
```
file:///home/yoon/cobot_ws/src/lunchbox_web/admin_index.html
```

> 관리자 화면 우측 상단에서 Firebase 연결 상태와 로봇 상태 뱃지를 확인할 수 있습니다.

---

## 노드 관계 요약

### 주문 처리 흐름

```
[App.tsx] (사용자 웹앱, rokey-d3991.web.app)
        │  addDoc(orders, status:pending)
        ▼
   [Firestore]
        │  on_snapshot ADDED 감지
        ▼
[lunchbox_database_node]  ──→  /robot_order 토픽 publish
        │                            │
        │  Firestore status=cooking  ▼
        ▼                   [lunchbox_robot_node]
   [Firestore]                       │  Stage 1~5 순차 실행
        │  status = completed        │  movej/movel + DO 핀 + 토크 측정
        ▼                            ▼
   [App.tsx]              [DSR_ROBOT2 API] → [M0609 + RG2]
   onSnapshot 반영                   │
                                     ▼
                          [Firebase Realtime DB]
                            /robot_status (1초 주기)
                                     │
                                     ▼
                          [admin_index.html]
                          실시간 상태 카드 반영
```

### 모니터링 흐름

```
[DSR 드라이버]
        │  /joint_states 토픽 (실시간 6축)
        │  /error, /io/digital_input
        ▼
  [robot_dashboard]
        │  SSE /events (0.2초 주기 JSON)
        ▼
  [admin_index.html]
        │  3D URDF 뷰어 + 관절 게이지 + 토크 바
        ▼
  사용자 (관리자)

[USB Camera]
        │  OpenCV 캡처
        ▼
[camera_stream_server]
        │  MJPEG /video_feed
        ▼
  [admin_index.html <img>]
```

---

## 비상 시 처리

### 비상정지 (일시 정지)
**관리자 웹**: 우측 상단 🛑 **비상정지/일시정지** 버튼 클릭
**또는 Firebase** `/command` 에 직접 쓰기:
```json
{ "type": "pause", "timestamp": <unix_timestamp> }
```
→ `move_stop` 즉시 발동, 상태가 `paused` 로 전환. 작업이 중단된 위치에서 멈춤.

### 재개 (멈춘 곳부터 이어서)
**관리자 웹**: 비상정지 오버레이의 ▶️ **하던 행동부터 다시 진행** 버튼
```json
{ "type": "resume", "timestamp": <unix_timestamp> }
```
→ 작업 스레드가 일시정지를 해제하고 중단된 지점부터 이어서 진행.

### 초기화 후 1단계부터 재시작
관리자 웹: 충돌 시 🔄 **초기화 및 이 주문 처음부터 다시 시작** 버튼
```json
{ "type": "reset_and_restart", "timestamp": <unix_timestamp> }
```
→ `SetRobotControl(2)` 으로 충돌 해제 후 실패한 주문을 큐에 재삽입.

### 자동 충돌 감지
`collision_monitor` 스레드가 1초 주기로 다음을 감시하며 임계값 초과 시 자동 비상정지를 발동합니다:
| 항목 | 임계값 |
|---|---|
| 로봇 state | 3/5/6/7 (안전OFF/안전정지/비상정지/홈이동) |
| TCP 합력 | 80 N |
| Z축 외력 | 60 N |
| 관절 외부 토크 | 80 Nm (J1~J6 각각) |

### 홈 복귀
```json
{ "type": "move_home", "timestamp": <unix_timestamp> }
```

### 그리퍼 수동 제어
```json
{ "type": "gripper_open",      "timestamp": ... }   // 50mm
{ "type": "gripper_close",     "timestamp": ... }   // 5mm
{ "type": "gripper_full_open", "timestamp": ... }   // 100mm
```

---

## 테스트 모드 (관리자 웹)

관리자 웹 상단의 🧪 **테스트모드** 버튼으로 다음 시나리오를 실행할 수 있습니다:

| 시나리오 | 설명 |
|---|---|
| 스테이지 범위 실행 | Stage 1~5 중 임의 구간만 실행 (시작~종료 단계 지정) |
| 집게 집기/내려놓기만 | 메인 반찬 단계의 집게 도구 Pick & Place 만 |
| 메인반찬 전체 시퀀스 | Stage 3 전체 (집게 + 반찬 + 토크 판별 + 투하) |
| 밥 담기 전체 | Stage 4 전체 (스쿱 파지 + 6회 스쿱 + 가변속 특이점 통과) |
| 식판 배달 전체 | Stage 5 전체 |

각 시나리오는 1~10회 반복 실행 가능하며, 실행 중 ⏹ **테스트 중단 & 홈 복귀** 버튼으로 즉시 중단할 수 있습니다.

---

## 종료

각 터미널에서 `Ctrl+C` 로 정상 종료. 종료 순서는 위의 역순(Terminal 5 → 1) 을 권장합니다.

---

## 트러블슈팅

| 증상 | 원인/조치 |
|---|---|
| `generator already executing` 에러 | 모션 중 read API 가 호출됨. `robot_client._motion_active` 가 모션 중 read 를 차단하지만 그래도 발생 시 노드 재시작 |
| 홈 이동 30초 타임아웃 | 로봇 매뉴얼 모드인지 확인, 작업영역에 장애물 없는지 확인, `set_robot_mode(AUTONOMOUS)` 로그 확인 |
| 주문이 로봇에 전달 안 됨 | Terminal 3 (`lunchbox_database_node`) 실행 중인지, Firestore 콘솔에서 `/orders` 컬렉션의 새 문서가 `pending` 상태인지 확인 |
| 3D URDF 안 보임 | Terminal 4 의 robot_dashboard 가 켜져 있는지, 브라우저 콘솔에 mesh 404 에러 없는지 확인 |
| 카메라 인덱스 오류 | `ls /dev/video*` 로 가용 카메라 확인 후 `--camera 0/1/2` 변경 |
| 토크 판별이 항상 "빈그리퍼" | `main_dish_lift_l` 위치에서 baseline 측정 → 좌표 재확인 필요. mini_jog 로 재기록 권장 |
