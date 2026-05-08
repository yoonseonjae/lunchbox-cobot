"""
DSR_ROBOT2 / DR_init / rclpy 는 실제 로봇 환경에서만 import 가능.
테스트 환경에서는 sys.modules 에 모의(Mock) 모듈을 미리 등록해 ImportError 를 방지.
"""
import sys
import types
import threading
from unittest.mock import MagicMock, patch


# ── rclpy stub ──────────────────────────────────────────────────────────────
rclpy_mod = types.ModuleType("rclpy")
rclpy_mod.ok = MagicMock(return_value=True)
rclpy_mod.init = MagicMock()
rclpy_mod.shutdown = MagicMock()
rclpy_mod.create_node = MagicMock()

rclpy_logging = types.ModuleType("rclpy.logging")
rclpy_logging.get_logger = MagicMock(return_value=MagicMock(
    info=MagicMock(), warn=MagicMock(), error=MagicMock(), debug=MagicMock()
))

rclpy_executors = types.ModuleType("rclpy.executors")
rclpy_executors.MultiThreadedExecutor = MagicMock()

sys.modules.setdefault("rclpy", rclpy_mod)
sys.modules.setdefault("rclpy.logging", rclpy_logging)
sys.modules.setdefault("rclpy.executors", rclpy_executors)
sys.modules.setdefault("rclpy.node", types.ModuleType("rclpy.node"))
sys.modules.setdefault("rclpy.action", types.ModuleType("rclpy.action"))

# ── DR_init stub ─────────────────────────────────────────────────────────────
dr_init_mod = types.ModuleType("DR_init")
dr_init_mod.__dsr__id    = "dsr01"
dr_init_mod.__dsr__model = "m0609"
dr_init_mod.__dsr__node  = None
sys.modules.setdefault("DR_init", dr_init_mod)

# ── DSR_ROBOT2 stub ──────────────────────────────────────────────────────────
dsr_mod = types.ModuleType("DSR_ROBOT2")
for _fn in [
    "movej", "movel", "mwait", "amovej", "amovel",
    "set_tool", "set_tcp", "move_stop", "drl_script_stop",
    "set_digital_output", "get_digital_input",
    "wait", "check_motion", "get_robot_state",
    "set_robot_mode",
]:
    setattr(dsr_mod, _fn, MagicMock(return_value=None))

dsr_mod.DR_BASE = 0
dsr_mod.ROBOT_MODE_AUTONOMOUS = 1
sys.modules.setdefault("DSR_ROBOT2", dsr_mod)

# ── DR_common2 stub ──────────────────────────────────────────────────────────
dr_common2 = types.ModuleType("DR_common2")
dr_common2.posj = MagicMock(side_effect=lambda x: x)
dr_common2.posx = MagicMock(side_effect=lambda x: x)
sys.modules.setdefault("DR_common2", dr_common2)

# ── firebase_admin stub ──────────────────────────────────────────────────────
fb_mod = types.ModuleType("firebase_admin")
fb_mod.initialize_app = MagicMock()
fb_creds = types.ModuleType("firebase_admin.credentials")
fb_creds.Certificate = MagicMock()
fb_db = types.ModuleType("firebase_admin.db")
fb_db.reference = MagicMock(return_value=MagicMock(
    listen=MagicMock(), update=MagicMock()
))
sys.modules.setdefault("firebase_admin", fb_mod)
sys.modules.setdefault("firebase_admin.credentials", fb_creds)
sys.modules.setdefault("firebase_admin.db", fb_db)

# ── std_msgs stub ────────────────────────────────────────────────────────────
std_msgs = types.ModuleType("std_msgs")
std_msgs_msg = types.ModuleType("std_msgs.msg")
std_msgs_msg.String = MagicMock()
sys.modules.setdefault("std_msgs", std_msgs)
sys.modules.setdefault("std_msgs.msg", std_msgs_msg)
