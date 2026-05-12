#!/usr/bin/env python3
"""
==============================================================================
나만의 도련님 도시락 - 메인 노드 (리팩토링 완성본)
==============================================================================
아키텍처:
  main()
   ├─ CoordinateManager   (Phase 2) : YAML에서 좌표 로드
   ├─ RobotStateManager   (Phase 1) : 중앙 상태 관리
   ├─ RobotClient         (Phase 4.5): DSR API 래퍼
   ├─ FirebaseOrderRepository (Phase 4): 주문/명령 리스닝 + 상태 업로드
   └─ RobotController     (Phase 5) : 스레드 통합 + Stage 실행

Firebase 없는 환경에서는 use_firebase=False 로 MockOrderRepository 를 사용.
==============================================================================
"""

import os
import rclpy

import DR_init
from rclpy.logging import get_logger as _get_logger

_logger = _get_logger('lunchbox_robot_node')

ROBOT_ID    = "dsr01"
ROBOT_MODEL = "m0609"

DR_init.__dsr__id    = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

# cobot1/config/serviceAccountKey.json (패키지 루트 config)
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_ACCOUNT_KEY = os.path.join(_PKG_DIR, "config", "serviceAccountKey.json")
DATABASE_URL = "https://rokey-d3991-default-rtdb.asia-southeast1.firebasedatabase.app"

def main(args=None) -> None:
    rclpy.init(args=args)
    node = rclpy.create_node("lunchbox_robot_node", namespace=ROBOT_ID)
    DR_init.__dsr__node = node
    node.get_logger().info(f"노드 '{ROBOT_ID}/lunchbox_robot_node' 생성")

    try:
        from DSR_ROBOT2 import (
            movej, movel, mwait, amovej, amovel,
            set_tool, set_tcp,
            set_digital_output, get_digital_input,
            wait,
            drl_script_stop,
            check_motion,
            get_robot_state,
            set_robot_mode,
            # 🚨 [복구됨] 외력 감지 센서 API
            get_tool_force, get_external_torque,
            # 순응제어 (집기/놓기 힘제어)
            task_compliance_ctrl, release_compliance_ctrl,
            # 힘제어 (목표 접촉력 유지)
            set_desired_force, release_force,
            DR_BASE,
            DR_TOOL,
            move_periodic,
        )
        from DSR_ROBOT2 import ROBOT_MODE_AUTONOMOUS
        from DSR_ROBOT2 import (set_singular_handling, DR_VAR_VEL, DR_AVOID)
        from DR_common2 import posj, posx
    except ImportError as e:
        node.get_logger().error(f"DSR_ROBOT2 import 실패: {e}")
        rclpy.shutdown()
        return

    try:
        set_robot_mode(ROBOT_MODE_AUTONOMOUS)
    except Exception as e:
        node.get_logger().error(f"set_robot_mode 실패: {e}")

    from .coordinate_manager import CoordinateManager
    from .state_manager      import RobotStateManager
    from .robot_client       import RobotClient
    from .robot_controller   import RobotController

    coord_mgr    = CoordinateManager()         
    state_mgr    = RobotStateManager()          
    robot_client = RobotClient(
        vel = coord_mgr.velocity,
        acc = coord_mgr.acceleration,
    )
    robot_client.inject(
        movej, movel, mwait, amovej, amovel,
        set_digital_output, get_digital_input,
        wait, drl_script_stop,
        check_motion, drl_script_stop,
        get_robot_state,
        # 🚨 [복구됨] 클라이언트에 센서 주입
        get_tool_force, get_external_torque,
        posj, posx, DR_BASE,
        # 순응제어
        task_compliance_ctrl=task_compliance_ctrl,
        release_compliance_ctrl=release_compliance_ctrl,
        # 힘제어
        set_desired_force=set_desired_force,
        release_force=release_force,
        # 주기적 이동
        move_periodic=move_periodic,
        # singularity handling
        set_singular_handling=set_singular_handling,
        DR_VAR_VEL=DR_VAR_VEL,
        DR_AVOID = DR_AVOID
    )

    use_firebase = os.path.exists(SERVICE_ACCOUNT_KEY)

    if use_firebase:
        from .repositories import FirebaseOrderRepository
        order_repo = FirebaseOrderRepository(SERVICE_ACCOUNT_KEY, DATABASE_URL)
        if not order_repo.available:
            node.get_logger().warn("⚠️ Firebase 연결 실패 → Mock 으로 전환")
            use_firebase = False

    if not use_firebase:
        from .repositories import MockOrderRepository
        order_repo = MockOrderRepository()
        node.get_logger().info("ℹ️  MockOrderRepository 사용 (Firebase 없음)")

    controller = RobotController(
        node         = node,
        state_mgr    = state_mgr,
        robot_client = robot_client,
        coord_mgr    = coord_mgr,
        order_repo   = order_repo,
    )

    if not controller.start():
        node.get_logger().error("컨트롤러 시작 실패 → 종료")
        return

    try:
        controller.join()
    except KeyboardInterrupt:
        node.get_logger().info("Ctrl+C 감지 - 종료")
    finally:
        controller.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        _logger.info("종료 완료")

if __name__ == "__main__":
    main()