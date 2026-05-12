# 시스템 전체 플로우차트

```mermaid
flowchart TD
    subgraph WEB["🌐 사용자 웹앱 (App.tsx · rokey-d3991.web.app)"]
        W1[알레르기 / 할랄 / 비건 선호 선택]
        W2[메인 메뉴 선택<br/>제육 / 돈까스]
        W3[서브 반찬 선택<br/>최대 3개 - 피클·단무지·김치·샐러드]
        W4[주문 확인]
        W5[실시간 진행률 + 픽업 번호 표시]
        W1 --> W2 --> W3 --> W4
        W5 -.실시간 onSnapshot.- W4
    end

    subgraph ADMIN["🖥️ 관리자 웹 (admin_index.html)"]
        A1[KPI 카드<br/>대기/처리중/완료/오류]
        A2[실시간 주문 큐 테이블]
        A3[3D URDF 뷰어<br/>Three.js + urdf-loader]
        A4[CCTV 라이브 MJPEG]
        A5[진행률 원형 차트<br/>+ 단계별 로그]
        A6[비상정지/일시정지/재개 버튼]
        A7[🧪 테스트모드 패널<br/>시나리오 × 1~10회]
        A8[6축 관절 게이지<br/>+ 그리퍼 상태]
    end

    subgraph FB["☁️ Firebase 클라우드"]
        FB1[(Firestore: orders<br/>status: pending)]
        FB2[(Firestore: orders<br/>status: cooking)]
        FB3[(Firestore: orders<br/>status: completed/error)]
        FB4[(Realtime DB: /robot_status<br/>1초 주기 업로드)]
        FB5[(Realtime DB: /command<br/>긴급 명령)]
        FB6[(Realtime DB: /test_command<br/>테스트 시나리오)]
        FB7[(Realtime DB: /orders<br/>로봇용 주문 큐)]
    end

    subgraph ROS["🤖 ROS2 시스템 (Ubuntu 22.04 PC · Humble)"]
        subgraph DB_NODE["lunchbox_database_node [Terminal 3]"]
            DB1[Firestore 리스너<br/>on_snapshot pending 감시]
            DB2[주문 파싱<br/>main_dish / sub_dishes 분류]
            DB3[Publisher /robot_order]
            DB4[Subscriber /order_status]
        end

        subgraph ROBOT_NODE["lunchbox_robot_node [Terminal 2]"]
            RN1[CoordinateManager<br/>robot_coordinates.yaml]
            RN2[RobotClient<br/>DSR API 래퍼 + RLock]
            RN3[RobotStateManager<br/>스레드 안전 상태]
            RN4[TorqueClassifier<br/>J2 baseline 동적 판별]
            RN5[FirebaseOrderRepository<br/>orders/command 리스너]
            RN6[RobotController<br/>스레드 통합 + 주문 큐]
        end

        subgraph CTRL_THREADS["RobotController 4개 스레드"]
            T1[ros_spin_thread<br/>MultiThreadedExecutor]
            T2[task_thread ★<br/>주문 큐 소비 + DSR API]
            T3[status_upload_thread<br/>1초마다 Firebase + topic]
            T4[collision_monitor<br/>1초마다 충돌 감지]
            T5[torque_publish_thread<br/>1초마다 외부 토크 publish]
        end

        subgraph STAGES["5단계 로봇 동작"]
            S1["Stage 1: TraySetupStage<br/>식판 보관소 → 세팅 장소"]
            S2["Stage 2: SubDishStage<br/>서브 반찬 × 최대 3종<br/>동기 진입 + 비동기 이송"]
            S3["Stage 3: MainDishStage<br/>집게 도구 + J2 baseline 측정<br/>토크 판별로 재시도"]
            S4["Stage 4: RiceStage<br/>스쿱 + 가변속 특이점 통과"]
            S5["Stage 5: DeliveryStage<br/>식판 픽업장소 배달<br/>비상정지 재개 시 파지 판별"]
            S1 --> S2 --> S3 --> S4 --> S5
        end

        subgraph DASHBOARD["robot_dashboard [Terminal 4]"]
            D1[/joint_states 구독]
            D2[/error /io 구독]
            D3[2초마다 서비스 폴링<br/>posx / mode / state / alarm]
            D4[aiohttp 서버<br/>포트 8080 SSE /events]
            D5[URDF/메쉬 정적 파일 서빙]
        end

        subgraph CAM["camera_stream_server [Terminal 5]"]
            C1[USB 카메라 캡처<br/>1280×720 @ 20fps]
            C2[Flask MJPEG 서버<br/>포트 5000 /video_feed]
        end
    end

    subgraph ROBOT["🦾 DSR M0609 + RG2 (192.168.137.100:12345) [Terminal 1]"]
        R1[dsr_bringup2_rviz.launch.py]
        R2[실제 로봇 팔<br/>movej / movel / amovej / amovel]
        R3[RG2 그리퍼<br/>DO1/DO2/DO3 핀 제어]
        R4[RViz2 시각화]
    end

    %% 주문 흐름
    W4 -- addDoc orders --> FB1
    FB1 -- on_snapshot ADDED --> DB1
    DB1 --> DB2 --> DB3
    DB3 -- /robot_order 토픽 --> T1
    T1 --> T2
    T2 -- Order 객체 --> STAGES
    STAGES -- 좌표 조회 --> RN1
    STAGES -- DSR API --> RN2
    STAGES -- 토크 판별 --> RN4
    RN2 --> R2
    RN2 --> R3
    DB2 -- status=cooking --> FB2

    %% 상태 흐름
    T3 -- 상태 업로드 --> FB4
    T4 -- 충돌 감지 --> RN3
    T5 -- /robot_torque --> D1

    %% 완료
    S5 -- /order_status --> DB4
    DB4 -- status=completed --> FB3
    FB3 -. onSnapshot .-> W5

    %% 명령
    FB5 -- pause/resume/reset --> RN5
    FB6 -- 시나리오 --> RN5
    RN5 --> RN6

    %% 모니터링
    R1 -- 실제 토픽 --> D1
    R1 --> D2
    R1 -- 서비스 호출 --> D3
    D4 -- SSE 0.2초 주기 --> A3
    D4 -- SSE --> A8
    D5 -- URDF/메쉬 --> A3
    C2 -- MJPEG --> A4
    FB4 -- 실시간 상태 --> A1
    FB4 --> A2
    FB4 --> A5
    A6 -- 명령 발행 --> FB5
    A7 -- 테스트 명령 --> FB6
    R1 --> R4
```

---

## 핵심 노드별 역할 요약

| 노드 / 컴포넌트 | 실행 위치 | 역할 |
|---|---|---|
| `lunchbox_robot_node` | Terminal 2 | 메인 진입점, 컴포넌트 조립 |
| `RobotController` | 노드 내부 | 4개 스레드 통합 + 주문 큐 + 명령 라우팅 |
| `RobotClient` | 노드 내부 | DSR API 락 직렬화, 그리퍼 DO 핀 제어 |
| `RobotStateManager` | 노드 내부 | 스레드 안전 상태 + 비상정지/일시정지 이벤트 |
| `CoordinateManager` | 노드 내부 | YAML 좌표 로드 + 좌표 제공 |
| `TorqueClassifier` | 노드 내부 | J2 토크 동적 baseline 페이로드 판별 |
| `FirebaseOrderRepository` | 노드 내부 | Firebase RTDB orders/command/test_command 리스너 |
| `lunchbox_database_node` | Terminal 3 | Firestore → /robot_order 토픽 브릿지 |
| `robot_dashboard` | Terminal 4 | 3D URDF + SSE 실시간 모니터링 |
| `camera_stream_server` | Terminal 5 | USB 카메라 MJPEG 스트림 |
| `dsr_bringup2` | Terminal 1 | Doosan 공식 드라이버 |

---

## 데이터 채널 정리

### ROS2 토픽

| 토픽 이름 | 방향 | 메시지 타입 | 용도 |
|---|---|---|---|
| `/robot_order` | DB → Robot | `std_msgs/String` (JSON) | 주문 전달 |
| `/order_status` | Robot → DB | `std_msgs/String` (JSON) | 완료 보고 |
| `/robot_status` | Robot → 외부 | `std_msgs/String` (JSON) | 1초 주기 상태 |
| `/robot_tcp_posx` | Robot → 외부 | `std_msgs/String` (JSON) | TCP 좌표 |
| `/robot_target_posj` | Robot → 외부 | `std_msgs/String` (JSON) | 목표 관절각 |
| `/robot_torque` | Robot → 외부 | `std_msgs/String` (JSON) | 외부 토크 6축 |
| `/robot_motion_segment` | Robot → 외부 | `std_msgs/String` (JSON) | 동기/비동기 세그먼트 분석 |
| `/dsr01/joint_states` | DSR → 외부 | `sensor_msgs/JointState` | 실시간 관절 |
| `/dsr01/error` | DSR → 외부 | `dsr_msgs2/RobotError` | 에러 |

### Firebase 채널

| 경로 | 방향 | 용도 |
|---|---|---|
| Firestore `orders/{id}` | Web → Robot | 사용자 주문 (status: pending→cooking→completed) |
| RTDB `/orders/{id}` | Web → Robot | (구) Realtime DB 주문 (FirebaseOrderRepository 가 감시) |
| RTDB `/command` | Web → Robot | pause / resume / reset_and_restart / move_home / gripper_* |
| RTDB `/test_command` | Web → Robot | 테스트 시나리오 (scenario, repeat, stage_from, stage_to) |
| RTDB `/robot_status` | Robot → Web | 1초 주기 상태 업로드 |
| RTDB `/menu_config` | Web ↔ Web | 메뉴 구성 표시용 |

### HTTP/SSE 채널

| URL | 방향 | 용도 |
|---|---|---|
| `http://localhost:8080/events` (SSE) | dashboard → admin | 0.2초 주기 JSON push |
| `http://localhost:8080/state` (GET) | dashboard → 사용자 | JSON 스냅샷 |
| `http://localhost:8080/urdf/m0609_rg2.urdf` | dashboard → admin | URDF + 메쉬 |
| `http://localhost:5000/video_feed` (MJPEG) | camera → admin | CCTV 라이브 |
