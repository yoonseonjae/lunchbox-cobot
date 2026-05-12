# 주문 처리 시퀀스 다이어그램

## 1. 정상 주문 처리 (전체 흐름)

```mermaid
sequenceDiagram
    actor 고객
    participant WEB as App.tsx<br/>(React 웹앱)
    participant FS as Firestore<br/>orders
    participant DB as lunchbox<br/>_database_node
    participant RC as lunchbox_robot_node<br/>(RobotController)
    participant DSR as DSR M0609<br/>+ RG2
    participant ADMIN as admin_index.html<br/>(관리자 웹)

    고객->>WEB: 메인 1종 + 서브 최대 3종 선택
    고객->>WEB: 주문 확인
    WEB->>FS: addDoc(orders, {<br/>status: "pending",<br/>main_dish, sub_dishes,<br/>items})

    FS-->>DB: on_snapshot ADDED 감지
    DB->>DB: items에서 메뉴 이름 추출<br/>main_dish / sub_dishes 분류
    DB->>FS: update status → "cooking"
    DB->>RC: /robot_order 토픽 publish<br/>{_key, main_dish, sub_dishes}

    RC->>RC: _on_ros_order_msg() →<br/>_on_order_received() →<br/>_order_queue.put(order)

    Note over RC: task_thread가 큐에서 Order 꺼냄

    rect rgb(240, 248, 255)
    Note over RC,DSR: 🍱 Stage 1 — TraySetupStage (식판 세팅)
    RC->>DSR: movej(home) → gripper(50)
    RC->>DSR: movej(tray_storage.upper)<br/>→ movej(tray_storage.lower)
    RC->>DSR: DO1=ON DO2=OFF DO3=OFF → 5mm (식판 파지)
    RC->>DSR: movej(setting.upper)<br/>→ movej(setting.lower_1)<br/>→ movej(setting.lower_2)
    RC->>DSR: DO1=OFF DO2=OFF DO3=ON → 50mm (식판 안착)
    RC->>DSR: movej(setting.lower_3) → gripper(100)
    RC->>DSR: movej(home)
    end

    rect rgb(255, 248, 240)
    Note over RC,DSR: 🥗 Stage 2 — SubDishStage × N (서브 반찬, 최대 3회 반복)
    loop 서브 반찬 N종
        RC->>DSR: movej(home) → gripper(100)
        RC->>DSR: movej(pre_pick_j, radius=20)<br/>→ movel(pick_l, radius=20)
        RC->>DSR: DO1=ON DO2=OFF DO3=ON → 50mm (반찬 집기)
        RC->>DSR: amovel(up_pick_l, r=10)<br/>→ amovej(pre_place_j, r=10) [비동기 블렌딩]
        RC->>DSR: movel(place_l) → gripper(100)
        RC->>DSR: movej(home)
    end
    end

    rect rgb(255, 240, 240)
    Note over RC,DSR: 🍖 Stage 3 — MainDishStage (메인 반찬 + 토크 판별)
    RC->>DSR: movej(home) → gripper(100)
    RC->>DSR: movel(tong_approach_l) → DO1=ON DO2=ON DO3=OFF → 30mm (집게 파지)
    RC->>DSR: movel(tong_lift_l) → movel(main_dish_lift_l)
    Note over RC: ★ 집게만 든 상태에서<br/>J2 baseline 측정 (5샘플)
    RC->>DSR: movel(main_dish_pick_l) → DO 20mm (반찬 집기)
    RC->>DSR: movel(main_dish_lift_l)
    Note over RC: ★ J2 delta 비교로 파지 판별<br/>(빈그리퍼/집게/집게+돈까스)
    alt 미파지 감지 (집게 only)
        Note over RC: 재시도: 30mm → pick → 20mm → lift → 재측정
        loop 파지 성공할 때까지
            RC->>DSR: 재시도 시퀀스
        end
    end
    RC->>DSR: movel(tray_approach_l) → movel(tray_approach2_l)
    RC->>DSR: DO 30mm → movel(tray_release_l) (반찬 투하)
    RC->>DSR: movel(tong_return_above_l) → movel(tong_return_l)
    RC->>DSR: DO 100mm → movej(home)
    end

    rect rgb(240, 255, 240)
    Note over RC,DSR: 🍚 Stage 4 — RiceStage (밥 담기)
    RC->>DSR: movej(home) → gripper(50)
    RC->>DSR: movel(above_l) → DO 5mm (스쿱 파지)
    RC->>DSR: movel(scoop_1~6) [6점 스쿱 경로]
    RC->>DSR: move_periodic [밥 털기 흔들기 × 25회]
    Note over RC,DSR: ★ set_singular_handling(DR_VAR_VEL)<br/>가변속 특이점 통과 모드 ON
    RC->>DSR: movel(transit_l) → movel(place_pre_l)<br/>→ movel(place_down_l) → movel(place_pre2_l)<br/>→ movel(home_ready_l) → movel(place_up_l)<br/>→ movel(back_l) → movel(back_lean_l)
    Note over RC,DSR: set_singular_handling(DR_AVOID) 복원
    RC->>DSR: DO 100mm → movel(home_ready_l) → movej(home)
    end

    rect rgb(255, 250, 230)
    Note over RC,DSR: 📦 Stage 5 — DeliveryStage (식판 배달)
    RC->>DSR: movel(p004_l) → movej(p005_j) → movej(p006_j)
    RC->>DSR: DO 5mm (식판홀더 파지)
    RC->>DSR: movel(p007_l) → movej(p008_j) → movel(p009_l)
    RC->>DSR: movej(p010_j) → movel(p011_l) → movej(p012_j)
    RC->>DSR: DO 50mm (식판 안착) → movel(p013_l) (후퇴)
    end

    RC->>RC: _process_order() 완료<br/>sm.update_status(state=IDLE)
    RC->>FS: mark_completed(key) → status = "completed"
    FS-->>WEB: onSnapshot 실시간 반영
    WEB-->>고객: ✅ 완료 화면 + 픽업 번호

    loop 1초마다 (전 과정)
        RC-->>+ADMIN: /robot_status (Firebase RTDB)<br/>→ admin 카드 갱신
    end

    loop 0.2초마다
        RC-->>ADMIN: /joint_states → SSE → 3D URDF 갱신
    end
```

---

## 2. 비상정지 및 재개 흐름

```mermaid
sequenceDiagram
    actor 관리자
    participant ADMIN as admin_index.html
    participant FB as Firebase RTDB<br/>/command
    participant RC as RobotController
    participant SM as RobotStateManager
    participant DSR as DSR API

    Note over RC,DSR: 정상 작업 중...

    관리자->>ADMIN: 🛑 비상정지 버튼 클릭
    ADMIN->>FB: set /command { type: "pause", timestamp }

    FB-->>RC: listen_commands() 콜백
    RC->>RC: _on_command_received("pause")
    RC->>SM: set_pause() → pause_event.clear()
    RC->>SM: update_status(state=IDLE, current_task="⏸️ 일시정지됨")
    RC->>DSR: do_stop() — move_stop(3) [즉시 감속 정지]

    Note over RC,SM: 작업 스레드는 다음 _movej 호출 시<br/>wait_if_paused() 에서 블로킹

    관리자->>ADMIN: ▶️ 재개 버튼 클릭
    ADMIN->>FB: set /command { type: "resume", timestamp }

    FB-->>RC: 콜백
    RC->>SM: clear_pause() → pause_event.set()
    RC->>SM: clear_emergency_stop() (if stopped)

    alt Stage 5 (Delivery) 중이었던 경우
        Note over RC: 식판/홀더 파지 상태 불확실<br/>토크 측정으로 자동 판별
        RC->>RC: _handle_delivery_estop_resume()
        RC->>DSR: get_external_torque() × 5회 평균
        RC->>RC: TorqueClassifier.predict()
        alt 빈그리퍼
            RC->>DSR: gripper(100) → movej(home)
            Note over RC: 1단계부터 재시작 큐 삽입
        else 책받침 또는 책받침+가득식판
            RC->>DSR: gripper(5) → 홀더 초기위치 복귀<br/>(p012 → p011 → ... → p006)
        end
    else 다른 Stage 중
        Note over RC,SM: pause_event.wait() 가 풀려<br/>작업 스레드가 자동 재개
    end
```

---

## 3. 자동 충돌 감지 흐름

```mermaid
sequenceDiagram
    participant CM as collision_monitor<br/>(1초 주기)
    participant RC_API as RobotClient
    participant DSR as DSR API
    participant SM as RobotStateManager
    participant FB as Firebase RTDB
    participant ADMIN as admin_index.html

    loop 매 1초
        CM->>RC_API: is_motion_active()?
        alt 모션 중
            Note over CM: 즉시 스킵 (read 차단)
        else 모션 멈춤 상태
            CM->>DSR: get_robot_state()
            CM->>DSR: get_tool_force()
            CM->>DSR: get_external_torque()

            alt state ∈ {3,5,6,7} OR<br/>합력 > 80N OR<br/>Z축 > 60N OR<br/>관절 토크 > 80Nm
                CM->>SM: trigger_emergency_stop()
                CM->>RC_API: do_stop() (3초 대기 후 홈 이동)
                CM->>SM: update_status(state=ERROR, "🚨 충돌 감지: ...")
                CM->>FB: upload_robot_status(state=collision)

                FB-->>ADMIN: 실시간 반영
                Note over ADMIN: 빨간색 오버레이 표시<br/>"🔄 초기화 및 처음부터 다시 시작" 버튼
            end
        end
    end
```

---

## 4. 테스트 모드 흐름

```mermaid
sequenceDiagram
    actor 관리자
    participant ADMIN as admin_index.html
    participant FB as Firebase RTDB<br/>/test_command
    participant RC as RobotController
    participant STAGES as 5단계 스테이지

    관리자->>ADMIN: 🧪 테스트모드 패널 열기
    관리자->>ADMIN: 시나리오 선택<br/>(스테이지 범위 / 집게 / 메인반찬 / 밥 / 배달)
    관리자->>ADMIN: 반복 횟수 1~10회 설정
    관리자->>ADMIN: ▶ 테스트 실행

    ADMIN->>FB: set /test_command {<br/>scenario, repeat, stage_from,<br/>stage_to, main_dish, sub_dishes,<br/>timestamp}

    FB-->>RC: listen_test_command() 콜백
    RC->>RC: _on_test_command_received(payload)
    RC->>RC: _order_queue.put(("__test__", payload))

    Note over RC: task_thread가 큐에서 꺼냄

    RC->>RC: _run_test_scenario(payload)
    loop repeat 횟수만큼
        alt scenario == "stage_only"
            RC->>STAGES: _process_test_stages(<br/>stage_from~stage_to)
        else scenario == "tong_pick_place"
            RC->>STAGES: _run_tong_pick_place()
        else scenario == "main_dish_full"
            RC->>STAGES: MainDishStage.execute()
        else scenario == "rice_full"
            RC->>STAGES: RiceStage.execute()
        else scenario == "delivery_full"
            RC->>STAGES: DeliveryStage.execute()
        end

        alt 관리자가 ⏹ 테스트 중단 클릭
            ADMIN->>FB: /command { type: "test_cancel" }
            FB-->>RC: _test_cancel.set()
            RC->>RC: 다음 반복 진입 전 break
            RC->>RC: 홈 복귀 + 그리퍼 100mm
        end
    end

    RC->>RC: sm.update_status(state=IDLE, "대기 중")
    RC-->>ADMIN: 다음 status 업로드 시 idle 표시<br/>→ ⏹ 버튼 숨김
```

---

## 5. 토크 기반 파지 판별 (Stage 3 핵심)

```mermaid
sequenceDiagram
    participant ST as MainDishStage
    participant RC as RobotClient
    participant DSR as DSR API
    participant TC as TorqueClassifier

    ST->>DSR: 집게 30mm 파지 → tong_lift_l
    ST->>DSR: movel(main_dish_lift_l)<br/>[집게만 든 상태]

    Note over ST,DSR: ★ baseline 측정 위치

    loop 5회, 0.1초 간격
        ST->>RC: get_external_torque()
        RC->>DSR: /dsr01/aux_control/get_external_torque
        DSR-->>RC: [J1..J6] Nm
        RC-->>ST: torque[1] (J2) 만 수집
    end
    ST->>ST: baseline_j2 = mean(J2 samples)

    ST->>DSR: movel(main_dish_pick_l) → gripper 20mm (반찬 집기)
    ST->>DSR: movel(main_dish_lift_l) [같은 위치 복귀]

    loop 3회, 0.15초 간격
        ST->>RC: get_external_torque()
        RC-->>ST: J2 samples
    end
    ST->>ST: mean_j2 = mean(samples)<br/>boundary = baseline_j2 + DELTA/2<br/>(DELTA = 0.25)

    alt mean_j2 < boundary
        Note over ST: 미파지 (집게만)<br/>→ 재시도
        ST->>DSR: gripper 30mm → movel(pick_l) → gripper 20mm → lift_l
        ST->>ST: 다시 측정
    else mean_j2 ≥ boundary
        Note over ST: 파지 성공 (집게+돈까스)<br/>→ 다음 단계
        ST->>DSR: movel(tray_approach_l) → ... → 투하
    end
```

> **알고리즘 근거**: 집게만 들 때 J2 ≈ -3.38 Nm, 집게+돈까스(45g)일 때 J2 ≈ -3.06 Nm 로 약 0.32 Nm 차이. 자세별 절댓값이 달라지므로 **고정 임계값 대신 동적 baseline + delta** 방식을 채택하여 좌표 변경에도 강인하게 동작합니다. (자세한 내용은 [torque_classification_report.md](torque_classification_report.md) 참고)
