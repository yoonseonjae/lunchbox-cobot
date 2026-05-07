# 나만의 도련님 도시락 🍱 — 실행 가이드

## 사전 준비

```bash
# 의존 패키지 설치
pip install firebase-admin flask opencv-python aiohttp PyYAML

# Firebase 서비스 계정 키 배치 (.gitignore 처리됨 — 별도 발급 필요)
cp serviceAccountKey.json ~/cobot_ws/src/cobot1/config/

# 빌드
cd ~/cobot_ws
colcon build --packages-select cobot1 lunchbox_web --symlink-install
source install/setup.bash
```

---

## 실행 순서

> **주의:** 각 터미널에서 반드시 `source install/setup.bash` 를 먼저 실행하세요.  
> 이전 터미널이 완전히 뜬 것을 확인한 후 다음 터미널로 넘어가세요.

---

### Terminal 1 — DSR 로봇 드라이버

> 로봇 본체 전원 및 네트워크 연결 확인 후 가장 먼저 실행

```bash
cd ~/cobot_ws && source install/setup.bash
ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py \
    model:=m0609 mode:=real host:=192.168.137.100 port:=12345
```

| 항목 | 값 |
|---|---|
| 로봇 IP | `192.168.137.100` (환경에 맞게 수정) |
| 포트 | `12345` |
| 성공 로그 | `dsr_bringup2` 노드 정상 기동 확인 |

---

### Terminal 2 — 메인 로봇 제어 노드

> Terminal 1 드라이버가 완전히 뜬 후 실행

```bash
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 lunchbox_robot_node
```

**✅ 다음 로그 확인 후 Terminal 3으로 넘어갈 것:**
```
[CoordinateManager] 설정 로드 완료: .../robot_coordinates.yaml
[Firebase] ✅ 초기화 완료
[ROS] spin 스레드 시작
[GRIPPER] 100mm  DO1=0 DO2=1 DO3=0
[Controller] ✅ 홈 이동 완료
[Firebase] /command 리스너 등록
[Task] 작업 스레드 시작
[Controller] ✅ 모든 스레드 시작 완료
```

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

---

### Terminal 4 — 관리자 웹 대시보드

> 3D URDF 뷰어 + 관절 실시간 SSE + 주문 큐 모니터링

```bash
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 robot_dashboard
```

**✅ 성공 로그:**
```
DSR M0609 Web Dashboard
http://localhost:8080
http://localhost:8080/state  (JSON 직접 확인)
```

---

### Terminal 5 — CCTV 카메라 스트리밍

```bash
cd ~/cobot_ws && source install/setup.bash
ros2 run cobot1 camera_stream_server
```

| 항목 | 값 |
|---|---|
| 스트림 URL | `http://localhost:5000/video_feed` |
| 미리보기 | `http://localhost:5000/` |
| 카메라 인덱스 변경 | `ros2 run cobot1 camera_stream_server --camera 1` |

---

### Browser — 관리자 화면 열기

```bash
xdg-open file:///home/yoon/cobot_ws/src/lunchbox_web/admin_index.html
```

또는 브라우저 주소창에 직접 입력:
```
file:///home/yoon/cobot_ws/src/lunchbox_web/admin_index.html
```

---

## 노드 관계 요약

```
[App.tsx / user_order.html]
        │  addDoc(orders, status:pending)
        ▼
   [Firestore]
        │  on_snapshot ADDED
        ▼
[lunchbox_database_node]  ──→  /robot_order 토픽
        │                            │
        │  status = cooking          ▼
        ▼                   [lunchbox_robot_node]
   [Firestore]                       │  Stage 1~5 실행
        │  status = completed        │  movej / movel / DO 핀
        ▼                            ▼
   [App.tsx]              [DSR_ROBOT2 API] → [M0609 + RG2]
   onSnapshot 반영
```

```
[lunchbox_robot_node]
        │  /joint_states 토픽
        ▼
  [robot_dashboard]
        │  SSE /events (0.2초 주기)
        ▼
  [admin_index.html]  →  3D URDF 뷰어 실시간 동기화
```

---

## 비상 시 처리

### 비상정지
`admin_index.html` → 🛑 비상정지 버튼  
또는 Firebase `/command` 에 직접 쓰기:
```json
{ "type": "emergency_stop", "timestamp": <unix_timestamp> }
```

### 재개
`admin_index.html` → Resume 버튼  
또는:
```json
{ "type": "resume", "timestamp": <unix_timestamp> }
```

### 홈 복귀
```json
{ "type": "move_home", "timestamp": <unix_timestamp> }
```
