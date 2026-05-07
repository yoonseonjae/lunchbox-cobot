# 나만의 도련님 도시락 — 실행 가이드

## 사전 준비

```bash
# Firebase 서비스 키 배치 (별도 발급 필요)
cp serviceAccountKey.json ~/cobot_ws/src/cobot1/config/

# 의존 패키지 설치
pip install firebase-admin flask opencv-python aiohttp

# ROS2 패키지 빌드
cd ~/cobot_ws
colcon build --packages-select cobot1
source install/setup.bash
```

---

## Terminal 1 — 로봇 드라이버 + RViz

```bash
ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py \
    model:=m0609 mode:=real host:=192.168.1.100 port:=12345
```

**성공 로그:**
```
[dsr_bringup2]: Robot connected: 192.168.1.100:12345
[rviz2]: Loaded
```

---

## Terminal 2 — 메인 로봇 제어 노드

```bash
ros2 run cobot1 lunchbox_robot_node
```

**성공 로그:**
```
[Main] 노드 'dsr01/lunchbox_robot_node' 생성
[Controller] ✅ 홈 이동 완료
[Controller] ✅ 모든 스레드 시작 완료
```

---

## Terminal 3 — Firebase ↔ ROS2 브릿지

```bash
ros2 run cobot1 lunchbox_database_node
```

**성공 로그:**
```
✅ Firebase Admin SDK 초기화 성공!
🚀 Firestore 감시 모드 작동 중...
```

---

## Terminal 4 — 모니터링 대시보드

```bash
ros2 run cobot1 robot_dashboard
```

**성공 로그:**
```
[robot_dashboard] WebSocket server started on port 8765
```

---

## Terminal 5 — CCTV 카메라 스트리밍

```bash
ros2 run cobot1 camera_stream_server
# 카메라 인덱스/해상도 변경 시:
ros2 run cobot1 camera_stream_server --camera 0 --port 5000 --width 1280 --height 720
```

**성공 로그:**
```
[Camera] 카메라 인덱스 2 열기...
[Camera] 스트리밍 시작: http://0.0.0.0:5000/video_feed
```

---

## 실행 순서 요약

| 순서 | Terminal | 명령 | 준비 신호 |
|------|----------|------|-----------|
| 1 | T1 | `dsr_bringup2_rviz.launch.py` | RViz 창 열림 |
| 2 | T2 | `lunchbox_robot_node` | 홈 이동 완료 |
| 3 | T3 | `lunchbox_database_node` | Firestore 감시 모드 |
| 4 | T4 | `robot_dashboard` | WebSocket 포트 8765 |
| 5 | T5 | `camera_stream_server` | /video_feed 스트림 시작 |

> T2가 홈 이동을 완료한 뒤 T3를 실행해야 주문 수신이 정상 동작합니다.

---

## 비상 정지

```bash
# 모든 노드 즉시 종료
Ctrl+C  # 각 터미널에서

# 로봇 긴급 정지 (DSR 전용)
ros2 service call /dsr01/motion/stop dsr_msgs2/srv/Stop "{stop_mode: 1}"
```

---

## 접속 주소

| 서비스 | 주소 |
|--------|------|
| 사용자 주문 웹앱 | https://rokey-d3991.web.app |
| 카메라 스트림 | http://\<PC_IP\>:5000/video_feed |
| 대시보드 WebSocket | ws://\<PC_IP\>:8765 |
