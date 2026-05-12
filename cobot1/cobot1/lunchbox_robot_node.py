#!/usr/bin/env python3
"""
==============================================================================
나만의 도련님 도시락 - 메인 노드 (generator 충돌 해결판)
==============================================================================
변경 요약:
  1) set_robot_mode 를 main()에서 호출하지 않음 → _task_loop 안에서 작업 스레드가 호출
     (이유: spin 시작 전이라도 같은 노드의 service client 가 generator 를 열어두면
      이후 spin 이 시작될 때 충돌 가능성이 있음)
  2) robot_client.inject()의 read API 인자 순서/이름 명시 호출로 변경 (가독성)
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

SERVICE_ACCOUNT_KEY = os.path.expanduser("~/cobot_ws/cobot1/config/serviceAccountKey.json")
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
            get_tool_force, get_external_torque,
            get_current_posx, get_current_posj,
            DR_BASE, DR_TOOL,
            move_periodic,
        )
        from DSR_ROBOT2 import ROBOT_MODE_AUTONOMOUS
        from DR_common2 import posj, posx
    except ImportError as e:
        node.get_logger().error(f"DSR_ROBOT2 import 실패: {e}")
        rclpy.shutdown()
        return

    # ⛔ [제거됨] 여기서 set_robot_mode 호출하지 않음
    # → _task_loop 가 시작될 때 작업 스레드에서 호출하도록 변경
    #   (spin 시작 전 service generator 가 미완료 상태로 남아 충돌의 씨앗이 됨)

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
        check_motion, drl_script_stop,   # move_stop 자리에 drl_script_stop 유지
        get_robot_state,
        get_tool_force, get_external_torque,
        posj, posx, DR_BASE,
        move_periodic, DR_TOOL,
        get_current_posx, get_current_posj,
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