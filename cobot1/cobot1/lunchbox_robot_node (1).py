#!/usr/bin/env python3
"""
==============================================================================
나만의 도련님 도시락 - 로봇 메인 노드 (예외처리 10종 + 부분실행 반영)
==============================================================================
그리퍼 (OnRobot RG2 - WebLogic DO 매핑):
  gripper_5mm()   : DO1=ON,  DO2=OFF, DO3=OFF  → Width  5mm  (#0)
  gripper_20mm()  : DO1=ON,  DO2=OFF, DO3=ON   → Width 20mm  (#6)
  gripper_30mm()  : DO1=ON,  DO2=ON,  DO3=OFF  → Width 30mm  (#7)
  gripper_50mm()  : DO1=OFF, DO2=OFF, DO3=ON   → Width 50mm  (#4)
  gripper_100mm() : DO1=OFF, DO2=ON,  DO3=OFF  → Width 100mm (#1)

Tool / TCP : "Tool Weight_2FG" / "2FG_TCP"

5 STAGE 순서:
  1. run_tray_setup()    - 식판 거치대 → 세팅장소
  2. run_sub_dish()      - 서브 반찬 담기 (3종)
  3. run_main_dish()     - 메인 반찬 담기
  4. run_rice()          - 밥 담기
  5. run_tray_delivery() - 식판 픽업장소로 배달
==============================================================================
"""

import os
import time
import threading
import queue

import rclpy
from rclpy.executors import MultiThreadedExecutor

import DR_init

# 예외처리 1: Firebase 선택적 import 및 Guard
FIREBASE_AVAILABLE = False
try:
    import firebase_admin
    from firebase_admin import credentials, db
    FIREBASE_AVAILABLE = True
except ImportError:
    print("[Firebase] ⚠️ firebase_admin 없음 - 오프라인 모드로 동작")

# ============================================================================
# 기본 설정
# ============================================================================
ROBOT_ID    = "dsr01"
ROBOT_MODEL = "m0609"
VELOCITY    = 30    # 처음엔 낮게, 익숙해지면 올릴 것
ACC         = 30

DR_init.__dsr__id    = ROBOT_ID
DR_init.__dsr__model = ROBOT_MODEL

ON,  OFF = 1, 0

# Firebase
SERVICE_ACCOUNT_KEY_PATH = os.path.expanduser(
    "~/cobot_ws/cobot1/config/serviceAccountKey.json"
)
DATABASE_URL = "https://rokey-d3991-b04b6-default-rtdb.asia-southeast1.firebasedatabase.app"

# ============================================================================
# 좌표 정의  ← teach 후 여기만 수정
# ============================================================================
# 홈 (cup_deliver.py 실측값)
HOME_J = [0.002, -0.043, 90.041, 0.001, 89.997, 0.004]

# ─────────────────────────────────────────────────────────
# 1️⃣ 식판 세팅 좌표 (식판보관소 → 세팅장소)
# ─────────────────────────────────────────────────────────
TRAY_STORAGE_UPPER_J = [-81.953, 0.242, 64.839, 0.018, 115.071, 8.12]
TRAY_STORAGE_LOWER_J = [-82.019, -4.471, 92.696, 0.045, 91.889, 8.056]

SETTING_UPPER_J   = [ 0.110, 25.207, 23.227, -0.194, 131.544,  0.021]
SETTING_LOWER_1_J = [-0.054, 13.814, 72.156, -0.065, 103.104, -0.006]
SETTING_LOWER_2_J = [-0.01, 31.641, 55.218, -0.157, 115.35, -0.02]
SETTING_LOWER_3_J = [-0.029, 43.646, 58.519, -0.227, 100.060, -0.045]

# ─────────────────────────────────────────────────────────
# 2️⃣ 서브 반찬 좌표 (move_side_dish 실측값)
# ─────────────────────────────────────────────────────────
SUB_WAYPOINTS = {
    "피클": {
        "pre_pick_j":  [-8.34, 56.09, 29.96, -4.98, 93.79, -7.07],
        "pick_l":      [697.47, -123.777, 10.479, 81.446, -175.702, 82.563],
        "up_pick_l":   [697.546, -123.664, 79.440, 86.21, -175.68, -2.57],
        "pre_place_j": [-6.83, 4.07, 104.59, -4.53, 71.12, -93.86],
        "place_l":     [374.034, -62.496, 28.810, 87.67, -175.94, -1.24],
    },
    "단무지": {
        "pre_pick_j":  [-1.17, 54.394, 33.207, -4.953, 92.804, -0.987],
        "pick_l":      [697.415, -35.009, 10.485, 81.387, -175.701, 82.547],
        "up_pick_l":   [697.576, -34.942, 79.564, 81.785, -175.704, 82.944],
        "pre_place_j": [4.96, 4.095, 104.571, -4.469, 71.995, -82.152],
        "place_l":     [373.967, 15.158, 28.716, 87.48, -175.942, -1.435],
    },
    "김치": {
        "pre_pick_j":  [5.198, 55.341, 31.445, -4.888, 94.157, 5.287],
        "pick_l":      [697.571, 42.818, 0.515, 83.579, -175.347, 83.802],
        "up_pick_l":   [697.593, 42.839, 79.59, 83.629, -175.347, 83.847],
        "pre_place_j": [18.74, 7.01, 101.337, -4.174, 73.302, -68.555],
        "place_l":     [373.18, 110.055, 28.62, 86.646, -175.763, -2.233],
    },
    "샐러드": {
        "pre_pick_j":  [12.16, 59.624, 23.173, -4.796, 98.679, 11.878],
        "pick_l":      [697.68, 130.238, 15.021, 83.493, -175.344, 83.696],
        "up_pick_l":   [692.609, 60.111, 76.329, 84.473, -175.37, 84.69],
        "pre_place_j": [-6.83, 4.07, 104.59, -4.53, 71.12, -93.86],
        "place_l":     [374.034, -62.496, 28.810, 87.67, -175.94, -1.24],
    },
}

# ─────────────────────────────────────────────────────────
# 3️⃣ 메인 반찬 좌표 (m0609_task_pickmain2 실측값)
# ─────────────────────────────────────────────────────────
MAIN_APPROACH_L    = [ 367.10,    8.57,  194.36, 132.58,  179.96,  132.24]  # 집게 상단
MAIN_ABOVE_L       = [ 510.39, -338.38,   99.83,  43.91, -175.22,   45.05]  # 집게 하단
MAIN_UP_L          = [ 506.24, -335.95,  207.38, 118.25, -170.73,  119.88]  # 집게 상단2
MAIN_TRANSIT_L     = [ 490.31, -381.44,  215.54, 115.64, -170.33,   26.46]  # 메인 상단
MAIN_PLACE_ABOVE_L = [ 498.07, -392.63,  146.82, 115.63, -170.36,   26.34]  # 메인 하단
MAIN_PLACE_UP2_L   = [ 490.07, -370.31,  282.53, 120.47, -169.71,   31.29]  # 메인 상단2
MAIN_SAUCE_ABOVE_L = [ 495.78,  -10.26,  150.74,  95.80,  136.85,   -1.12]  # 식판 상단
MAIN_SAUCE_POUR_L  = [ 496.46,  -31.07,  151.34,  96.11,  141.29,   -1.56]  # 살짝 뒤로 빼기
MAIN_RET1_L        = [ 502.01, -323.15,  261.09, 118.72, -175.38,  -61.00]  # 집게꽃이 상단
MAIN_RET2_L        = [ 510.59, -338.12,  104.08, 115.91, -175.44,  -63.96]  # 집게꽃이 하단

# ─────────────────────────────────────────────────────────
# 4️⃣ 밥 담기 좌표 (m0609_task_babpugi2 실측값)
# ─────────────────────────────────────────────────────────
RICE_APPROACH_L   = [ 367.34,   8.54,  194.85,  90.99,  179.96,   90.66]
RICE_ABOVE_L      = [ 308.06, -305.29,  130.00,  92.64, -148.82,   88.00]
RICE_SCOOP_1_L    = [ 311.51, -354.31,  141.72,  86.77, -172.62,   83.96]
RICE_SCOOP_2_L    = [ 311.14, -338.28,  261.99,  88.09, -172.48,   85.48]
RICE_SCOOP_3_L    = [ 302.95, -338.31,  145.90,  95.49, -123.36,   84.43]
RICE_SCOOP_4_L    = [ 308.50, -404.91,  100.07,  92.29, -127.87,   86.09]
RICE_SCOOP_5_L    = [ 306.90, -409.71,  129.17,  93.64, -125.28,   88.12]
RICE_SCOOP_6_L    = [ 295.93, -356.23,  199.44,  97.32, -115.74,   86.84]
RICE_TRANSIT_L    = [ 592.95,  -79.20,  401.79, 174.74, -101.29,   97.38]
RICE_PLACE_PRE_L  = [ 436.92, -150.80,  182.15,  65.42,  117.41,  -99.45]
RICE_PLACE_DOWN_L = [ 429.96, -151.37,  186.05,  65.71,  119.63,  131.19]
RICE_PLACE_UP_L   = [ 308.59, -329.39,  233.07,  97.65, -160.76,   86.04]
RICE_BACK_L       = [ 303.49, -344.05,  137.03,  97.63, -160.03,   97.66]
RICE_HOME_READY_L = [ 480.22, -221.15,  277.26, 125.91, -168.25,   40.68]

# ─────────────────────────────────────────────────────────
# 5️⃣ 식판 배달 좌표 (plate_finish 실측값)
# ─────────────────────────────────────────────────────────
DELIVERY_004_L = [367.450,   4.340, 194.210,  154.15,  179.94,  153.82]
DELIVERY_007_L = [322.030,  13.060, 172.310,    0.79,  162.43,   -0.44]
DELIVERY_009_L = [386.590, 426.490, 122.070,   80.31,  157.44,   -8.34]
DELIVERY_011_L = [385.330,  -3.630, 140.970,  107.10, -177.41,   20.02]
DELIVERY_013_L = [318.830,  26.960,  96.070,   58.56, -178.46,   58.42]

DELIVERY_005_J = [ 2.16, -6.56, 105.99, -1.37,  80.77,   0.00]
DELIVERY_006_J = [ 2.16, -3.96, 112.77, -0.10,  72.84,   0.00]
DELIVERY_008_J = [ 0.97,  4.29,  99.71, 16.33,  73.23, -90.93]
DELIVERY_010_J = [32.39, 15.08,  90.03, 10.91,  66.74, -61.75]
DELIVERY_012_J = [ 3.88, -5.40, 110.84, -2.61,  74.35,   4.37]


# # 이전 좌표 삭제 가능
# # ─────────────────────────────────────────────────────────
# # 1️⃣ 식판 세팅 좌표 (식판보관소 → 세팅장소)
# # ─────────────────────────────────────────────────────────
# TRAY_STORAGE_UPPER_J = [-89.909, 14.714, 38.856, -0.107, 126.434,  0.051]
# TRAY_STORAGE_LOWER_J = [-90.090,  4.716, 81.150, -0.025,  94.167, -0.007]

# SETTING_UPPER_J   = [ 0.110, 25.207, 23.227, -0.194, 131.544,  0.021]
# SETTING_LOWER_1_J = [-0.054, 13.814, 72.156, -0.065, 103.104, -0.006]
# SETTING_LOWER_2_J = [-0.011, 31.222, 55.079, -0.158, 115.835, -0.015]
# SETTING_LOWER_3_J = [-0.029, 43.646, 58.519, -0.227, 100.060, -0.045]
# SETTING_LOWER_4_J = [-0.023, 45.314, 55.549, -0.235, 101.378, -0.057]

# # ─────────────────────────────────────────────────────────
# # 2️⃣ 서브 반찬 좌표 (move_side_dish 실측값)
# # ─────────────────────────────────────────────────────────
# SUB_WAYPOINTS = {
#     "피클": {
#         "pre_pick_j":  [-8.34, 56.09, 29.96, -4.98, 93.79, -7.07],
#         "pick_l":      [697.47, -123.777, 10.479, 81.446, -175.702, 82.563],
#         "up_pick_l":   [697.546, -123.664, 79.440, 86.21, -175.68, -2.57],
#         "pre_place_j": [-6.83, 4.07, 104.59, -4.53, 71.12, -93.86],
#         "place_l":     [374.034, -62.496, 28.810, 87.67, -175.94, -1.24],
#     },
#     "단무지": {
#         "pre_pick_j":  [-1.17, 54.394, 33.207, -4.953, 92.804, -0.987],
#         "pick_l":      [697.415, -35.009, 10.485, 81.387, -175.701, 82.547],
#         "up_pick_l":   [697.576, -34.942, 79.564, 81.785, -175.704, 82.944],
#         "pre_place_j": [4.96, 4.095, 104.571, -4.469, 71.995, -82.152],
#         "place_l":     [373.967, 15.158, 28.716, 87.48, -175.942, -1.435],
#     },
#     "김치": {
#         "pre_pick_j":  [5.198, 55.341, 31.445, -4.888, 94.157, 5.287],
#         "pick_l":      [697.571, 42.818, 0.515, 83.579, -175.347, 83.802],
#         "up_pick_l":   [697.593, 42.839, 79.59, 83.629, -175.347, 83.847],
#         "pre_place_j": [18.74, 7.01, 101.337, -4.174, 73.302, -68.555],
#         "place_l":     [373.18, 110.055, 28.62, 86.646, -175.763, -2.233],
#     },
# }

# # ─────────────────────────────────────────────────────────
# # 3️⃣ 메인 반찬 좌표 (m0609_task_pickmain 실측값)
# # ─────────────────────────────────────────────────────────
# MAIN_HOME_PICK_J   = [-0.01,  0.04,  90.09, -0.02,  89.95,   0.01]
# MAIN_ABOVE_L       = [344.87, -339.80, 112.51, 150.30,  176.73,  156.04]
# MAIN_UP_L          = [338.58, -360.47, 220.92, 121.08,  173.14,  124.24]
# MAIN_TRANSIT_J     = [-50.78,  25.76,  54.85,  -2.31,   98.94, -137.98]
# MAIN_PLACE_ABOVE_L = [337.32, -424.23, 138.02,  49.52, -174.64,  -39.83]
# MAIN_PLACE_UP2_L   = [342.96, -420.83, 292.63,  49.37, -178.04,  -37.69]
# MAIN_SAUCE_ABOVE_L = [485.52,    4.80, 156.10,  95.26,  138.78,    1.56]
# MAIN_SAUCE_POUR_L  = [469.52,  -69.04, 172.25,  91.16,  139.80,    3.05]
# MAIN_RET1_L        = [344.74, -352.12, 221.10, 150.74,  177.13,  156.76]
# MAIN_RET2_L        = [343.12, -299.25, 119.33, 148.77,  176.41,  153.92]

# # ─────────────────────────────────────────────────────────
# # 4️⃣ 밥 담기 좌표 (m0609_task_babpugi 실측값)
# # ─────────────────────────────────────────────────────────
# RICE_APPROACH_L   = [367.14,   8.44,  193.92, 163.42,  179.90,  163.09]
# RICE_ABOVE_L      = [517.04, -295.50, 128.63,  83.12, -153.48,   84.23]
# RICE_SCOOP_1_L    = [507.94, -322.00, 165.19,  98.32, -161.27,   98.87]
# RICE_SCOOP_2_L    = [499.50, -298.92, 255.81, 107.37, -157.98,  107.94]
# RICE_SCOOP_3_L    = [534.71, -316.21, 152.20,  81.10, -130.17,   88.25]
# RICE_SCOOP_4_L    = [534.06, -397.66,  99.40,  79.88, -131.01,   88.89]
# RICE_SCOOP_5_L    = [531.25, -405.73, 127.09,  80.78, -128.75,   90.18]
# RICE_SCOOP_6_L    = [546.77, -357.00, 155.82,  82.53, -114.00,   89.97]
# RICE_TRANSIT_L    = [688.65,  -52.79, 330.71, 170.99, -106.77,   93.07]
# RICE_PLACE_PRE_L  = [380.86, -123.51, 176.83,  24.02,  128.41,  -82.76]
# RICE_PLACE_DOWN_L = [371.05, -116.12, 171.68,  25.93,  129.89,  120.76]
# RICE_PLACE_UP_L   = [514.34, -308.14, 278.53,  99.28, -166.14,  100.20]
# RICE_BACK_L       = [518.56, -334.83, 152.81,  98.37, -166.29,   98.94]
# RICE_HOME_READY_L = [480.22, -221.15, 277.26, 125.91, -168.25,   40.68]

# # ─────────────────────────────────────────────────────────
# # 5️⃣ 식판 배달 좌표 (plate_finish 실측값)
# # ─────────────────────────────────────────────────────────
# DELIVERY_004_L = [367.450,   4.340, 194.210,  154.15,  179.94,  153.82]
# DELIVERY_007_L = [322.030,  13.060, 172.310,    0.79,  162.43,   -0.44]
# DELIVERY_009_L = [386.590, 426.490, 122.070,   80.31,  157.44,   -8.34]
# DELIVERY_011_L = [385.330,  -3.630, 140.970,  107.10, -177.41,   20.02]
# DELIVERY_013_L = [318.830,  26.960,  96.070,   58.56, -178.46,   58.42]

# DELIVERY_005_J = [ 2.16, -6.56, 105.99, -1.37,  80.77,   0.00]
# DELIVERY_006_J = [ 2.16, -3.96, 112.77, -0.10,  72.84,   0.00]
# DELIVERY_008_J = [ 0.97,  4.29,  99.71, 16.33,  73.23, -90.93]
# DELIVERY_010_J = [32.39, 15.08,  90.03, 10.91,  66.74, -61.75]
# DELIVERY_012_J = [ 3.88, -5.40, 110.84, -2.61,  74.35,   4.37]

# ============================================================================
# 전역 상태
# ============================================================================
node_               = None
order_queue         = queue.Queue()
command_event       = threading.Event()
pending_command     = {"type": "", "timestamp": 0}
last_command_ts     = 0
emergency_stop_flag = threading.Event()

# 예외처리 6, 7: 중복 주문 방지 Set, 충돌 감시 모드 Flag, 유효 명령 리스트
processed_order_keys = set()
is_collision_mode    = False
VALID_COMMANDS       = {"emergency_stop", "resume", "move_home", "gripper_open", "gripper_close", "gripper_full_open"}

robot_status = {
    "state":        "idle",
    "current_task": "대기 중",
    "gripper":      "open",
    "joint_pos":    [0.0, 0.0, 90.0, 0.0, 90.0, 0.0],
    "last_update":  time.time(),
    "progress":     0,
    "step_index":   0,
    "total_steps":  0,
    "current_step": "",
    "step_log":     [],
}
robot_status_lock = threading.Lock()

movej = movel = mwait = posj = posx = None
DR_BASE = None
set_tool = set_tcp = None
set_digital_output = get_digital_input = wait = None
drl_script_stop = None

# 주문 전역 상태 변수
order_status_pub = None

# ============================================================================
# Firebase
# ============================================================================
# 예외처리 1: init_firebase() - 파일 없음 체크 및 연결 오류 대응
def init_firebase():
    if not FIREBASE_AVAILABLE:
        return False
    if not os.path.exists(SERVICE_ACCOUNT_KEY_PATH):
        print(f"[Firebase] ❌ 키 파일 없음: {SERVICE_ACCOUNT_KEY_PATH}")
        return False
    try:
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
        firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})
        print("[Firebase] 초기화 완료")
        return True
    except ValueError:
        print("[Firebase] 이미 초기화됨")
        return True
    except Exception as e:
        print(f"[Firebase] 초기화 실패: {e}")
        return False


def order_listener_callback(event):
    if event.data is None:
        return
    if event.path == "/":
        if isinstance(event.data, dict):
            for key, order in event.data.items():
                if order and order.get("status") == "pending":
                    # 예외처리 6: 중복 주문 처리 방지
                    if key in processed_order_keys:
                        continue
                    processed_order_keys.add(key)
                    order["_key"] = key
                    order_queue.put(order)
                    print(f"[Firebase] 주문 큐 추가: {key}")
    else:
        key = event.path.lstrip("/").split("/")[0]
        if isinstance(event.data, dict) and event.data.get("status") == "pending":
            # 예외처리 6: 중복 주문 처리 방지
            if key in processed_order_keys:
                return
            processed_order_keys.add(key)
            order = dict(event.data)
            order["_key"] = key
            order_queue.put(order)
            print(f"[Firebase] 주문 큐 추가: {key}")


def command_listener_callback(event):
    global pending_command, last_command_ts
    if event.data is None or not isinstance(event.data, dict):
        return
    cmd_type = event.data.get("type", "")
    ts       = event.data.get("timestamp", 0)
    
    # 예외처리 9: 유효하지 않은 명령 타입 방어
    if not cmd_type or ts <= last_command_ts:
        return
    if cmd_type not in VALID_COMMANDS:
        print(f"[Firebase] ⚠️ 알 수 없는 명령: '{cmd_type}' → 무시")
        return
        
    last_command_ts = ts
    pending_command = {"type": cmd_type, "timestamp": ts}
    print(f"[Firebase] 명령 수신: {cmd_type}")
    if cmd_type == "emergency_stop":
        emergency_stop_flag.set()
    command_event.set()


def start_firebase_listeners():
    db.reference("/orders").listen(order_listener_callback)
    db.reference("/command").listen(command_listener_callback)
    print("[Firebase] 리스너 시작")


# ============================================================================
# 상태 업로드 (1초마다)
# ============================================================================
# 예외처리 2: Firebase 연결 유실 방어 및 백오프 로직
def status_upload_thread():
    while rclpy.ok():
        try:
            if not FIREBASE_AVAILABLE:
                time.sleep(5.0)
                continue
            ref = db.reference("/robot_status")
            with robot_status_lock:
                robot_status["last_update"] = time.time()
                payload = dict(robot_status)
            ref.update(payload)
        except Exception as e:
            print(f"[StatusUpload] 오류: {e}")
            time.sleep(5.0)
            continue
        time.sleep(1.0)


def update_status(state=None, current_task=None, gripper=None,
                  progress=None, step_index=None, total_steps=None,
                  current_step=None):
    with robot_status_lock:
        if state         is not None: robot_status["state"]         = state
        if current_task  is not None: robot_status["current_task"]  = current_task
        if gripper       is not None: robot_status["gripper"]       = gripper
        if progress      is not None: robot_status["progress"]      = progress
        if step_index    is not None: robot_status["step_index"]    = step_index
        if total_steps   is not None: robot_status["total_steps"]   = total_steps
        if current_step  is not None: robot_status["current_step"]  = current_step


def log_step(msg, done=False):
    with robot_status_lock:
        prefix = "✅" if done else "🔄"
        entry  = f"{prefix} {msg}"
        logs   = robot_status["step_log"]
        logs.append(entry)
        if len(logs) > 20:
            logs.pop(0)
        robot_status["step_log"] = logs
    print(f"[Step] {entry}")


def reset_progress(total):
    with robot_status_lock:
        robot_status["progress"]     = 0
        robot_status["step_index"]   = 0
        robot_status["total_steps"]  = total
        robot_status["current_step"] = ""
        robot_status["step_log"]     = []


# ============================================================================
# 그리퍼 (OnRobot RG2 - WebLogic DO 매핑)
# ============================================================================
def gripper_5mm():
    set_digital_output(1, ON); set_digital_output(2, OFF); set_digital_output(3, OFF)
    wait(2.0); update_status(gripper="5mm"); print("[GRIPPER] 5mm")

def gripper_20mm():
    set_digital_output(1, ON); set_digital_output(3, ON); set_digital_output(2, OFF)
    wait(2.0); update_status(gripper="20mm"); print("[GRIPPER] 20mm")

def gripper_30mm():
    set_digital_output(1, ON); set_digital_output(2, ON); set_digital_output(3, OFF)
    wait(2.0); update_status(gripper="30mm"); print("[GRIPPER] 30mm")

def gripper_50mm():
    set_digital_output(1, OFF); set_digital_output(2, OFF); set_digital_output(3, ON)
    wait(2.0); update_status(gripper="50mm"); print("[GRIPPER] 50mm")

def gripper_100mm():
    set_digital_output(1, OFF); set_digital_output(2, ON); set_digital_output(3, OFF)
    wait(2.0); update_status(gripper="100mm"); print("[GRIPPER] 100mm")


def _stopped():
    return emergency_stop_flag.is_set()


# ============================================================================
# 공통 헬퍼
# ============================================================================
_progress_step  = 0
_progress_total = 1

def _tick(label=None):
    global _progress_step
    _progress_step += 1
    pct = min(int(_progress_step / _progress_total * 100), 99)
    if label:
        log_step(label)
    update_status(progress=pct, step_index=_progress_step, current_step=label or "")

# 예외처리 4: _movej / _movel 내부 예외 전파 방지 및 진행률 보호
def _movej(j, label=None):
    if _stopped():
        return False
    try:
        movej(posj(j), vel=VELOCITY, acc=ACC)
        mwait()
    except Exception as e:
        print(f"[_movej] 오류: {e}")
        return False
    _tick(label)
    return not _stopped()

def _movel(l, label=None):
    if _stopped():
        return False
    try:
        movel(posx(l), vel=VELOCITY, acc=ACC, ref=DR_BASE)
        mwait()
    except Exception as e:
        print(f"[_movel] 오류: {e}")
        return False
    _tick(label)
    return not _stopped()



# ============================================================================
# 🍱 STAGE 1 - 식판 세팅 시퀀스
# ============================================================================
def run_tray_setup():
    try:
        if not _movej(HOME_J, "🍱 [1/5] 홈 이동"): return False
        gripper_50mm(); wait(0.5)
        if not _movej(TRAY_STORAGE_UPPER_J, "🍱 [1/5] 보관소 상단 접근"): return False
        if not _movej(TRAY_STORAGE_LOWER_J, "🍱 [1/5] 보관소 하단 하강"): return False
        gripper_5mm(); wait(1.0)
        log_step("🍱 [1/5] 식판 파지 (5mm)", done=True)
        if not _movej(TRAY_STORAGE_UPPER_J, "🍱 [1/5] 식판 들어올림"): return False
        if not _movej(SETTING_UPPER_J, "🍱 [1/5] 세팅장소 상단 이동"): return False
        if not _movej(SETTING_LOWER_1_J, "🍱 [1/5] 세팅 하단1"): return False
        if not _movej(SETTING_LOWER_2_J, "🍱 [1/5] 세팅 하단2 (놓기 자세)"): return False
        gripper_50mm(); wait(1.0)
        log_step("🍱 [1/5] 식판 안착 (50mm)", done=True)
        if not _movej(SETTING_LOWER_3_J, "🍱 [1/5] 세팅 하단3 (그리퍼 후퇴)"): return False
        gripper_100mm(); wait(1.0)
        _movej(HOME_J, "🍱 [1/5] 홈 복귀")
        return True
    except Exception as e:
        print(f"[식판세팅] 오류: {e}")
        return False


# ============================================================================
# 🥗 STAGE 2 - 서브 반찬 담기
# ============================================================================
def run_sub_dish(dish_name, wp):
    try:
        if not _movej(HOME_J, f"🥗 [{dish_name}] 홈 이동"): return False
        gripper_100mm()
        if not _movej(wp["pre_pick_j"], f"🥗 [{dish_name}] 반찬 상단 이동"): return False
        if not _movel(wp["pick_l"], f"🥗 [{dish_name}] 잡는 위치 하강"): return False
        gripper_50mm(); wait(1.0)
        log_step(f"🥗 [{dish_name}] 반찬 잡기 (50mm)", done=True)
        if not _movel(wp["up_pick_l"], f"🥗 [{dish_name}] 들어올림"): return False
        if not _movej(wp["pre_place_j"], f"🥗 [{dish_name}] 식판 슬롯 상단 이동"): return False
        if not _movel(wp["place_l"], f"🥗 [{dish_name}] 놓기 위치 하강"): return False
        gripper_100mm()
        log_step(f"🥗 [{dish_name}] 반찬 놓기 (100mm)", done=True)
        return True
    except Exception as e:
        print(f"[서브반찬] {dish_name} 오류: {e}")
        return False


# ============================================================================
# 🍖 STAGE 3 - 메인 반찬 담기
# ============================================================================
def run_main_dish():
    try:
        if not _movej(HOME_J, "🍖 [3/5] 홈 이동"): return False
        gripper_100mm()
        if not _movel(MAIN_APPROACH_L, "🍖 [3/5] 집게 상단"): return False
        if not _movel(MAIN_ABOVE_L, "🍖 [3/5] 집게 하단"): return False
        gripper_30mm()
        log_step("🍖 [3/5] 메인반찬 집기 (30mm)", done=True)
        if not _movel(MAIN_UP_L, "🍖 [3/5] 집게 상단2"): return False
        if not _movel(MAIN_TRANSIT_L, "🍖 [3/5] 메인 상단"): return False
        if not _movel(MAIN_PLACE_ABOVE_L, "🍖 [3/5] 메인 하단"): return False
        gripper_20mm()
        log_step("🍖 [3/5] 메인반찬 투하 (20mm)", done=True)
        if not _movel(MAIN_PLACE_UP2_L, "🍖 [3/5] 메인 상단2"): return False
        if not _movel(MAIN_SAUCE_ABOVE_L, "🍖 [3/5] 식판 상단"): return False
        gripper_30mm()
        if not _movel(MAIN_SAUCE_POUR_L, "🍖 [3/5] 살짝 뒤로 빼기"): return False
        if not _movel(MAIN_RET1_L, "🍖 [3/5] 집게꽃이 상단"): return False
        if not _movel(MAIN_RET2_L, "🍖 [3/5] 집게꽃이 하단"): return False
        gripper_100mm()
        _movej(HOME_J, "🍖 [3/5] 홈 복귀")
        log_step("🍖 [3/5] 메인반찬 담기 완료", done=True)
        return True
    except Exception as e:
        print(f"[메인반찬] 오류: {e}")
        return False


# ============================================================================
# 🍚 STAGE 4 - 밥 담기
# ============================================================================
def run_rice():
    try:
        if not _movej(HOME_J, "🍚 [4/5] 홈 이동"): return False
        gripper_50mm()
        if not _movel(RICE_APPROACH_L, "🍚 [4/5] 밥솥 접근"): return False
        if not _movel(RICE_ABOVE_L, "🍚 [4/5] 밥솥 위"): return False
        gripper_5mm()
        log_step("🍚 [4/5] 스쿱 잡기 (5mm)", done=True)
        for label, coord in [
            ("스쿱1", RICE_SCOOP_1_L), ("스쿱2", RICE_SCOOP_2_L),
            ("스쿱3", RICE_SCOOP_3_L), ("스쿱4", RICE_SCOOP_4_L),
            ("스쿱5", RICE_SCOOP_5_L), ("스쿱6", RICE_SCOOP_6_L),
        ]:
            if not _movel(coord, f"🍚 [4/5] {label}"): return False
        if not _movel(RICE_TRANSIT_L,    "🍚 [4/5] 식판으로 이동"): return False
        if not _movel(RICE_PLACE_PRE_L,  "🍚 [4/5] 밥칸 접근"): return False
        if not _movel(RICE_PLACE_DOWN_L, "🍚 [4/5] 밥칸 하강"): return False
        if not _movel(RICE_PLACE_UP_L,   "🍚 [4/5] 스쿱 복귀 상승"): return False
        if not _movel(RICE_BACK_L,       "🍚 [4/5] 밥솥 복귀"): return False
        gripper_100mm()
        log_step("🍚 [4/5] 스쿱 내려놓기 (100mm)", done=True)
        if not _movel(RICE_HOME_READY_L, "🍚 [4/5] 대기 자세"): return False
        log_step("🍚 [4/5] 밥 담기 완료", done=True)
        return True
    except Exception as e:
        print(f"[밥담기] 오류: {e}")
        return False


# ============================================================================
# 📦 STAGE 5 - 식판 배달
# ============================================================================
def run_tray_delivery():
    try:
        if not _movel(DELIVERY_004_L, "📦 [5/5] 접근"): return False
        if not _movej(DELIVERY_005_J, "📦 [5/5] 파지 준비1"): return False
        if not _movej(DELIVERY_006_J, "📦 [5/5] 파지 위치"): return False
        gripper_5mm(); wait(1.0)
        log_step("📦 [5/5] 식판 파지 (5mm)", done=True)
        if not _movel(DELIVERY_007_L, "📦 [5/5] 들어올림"): return False
        if not _movej(DELIVERY_008_J, "📦 [5/5] 이동1"): return False
        if not _movel(DELIVERY_009_L, "📦 [5/5] 픽업장소 접근"): return False
        if not _movej(DELIVERY_010_J, "📦 [5/5] 이동2"): return False
        if not _movel(DELIVERY_011_L, "📦 [5/5] 안착 준비"): return False
        if not _movej(DELIVERY_012_J, "📦 [5/5] 안착 위치"): return False
        gripper_50mm()
        log_step("📦 [5/5] 식판 놓기 (50mm)", done=True)
        
        # 예외처리 8: 마지막 movel 무조건 True가 아닌 실패 여부 기록 유지
        if not _movel(DELIVERY_013_L, "📦 [5/5] 후퇴"):
            print("[식판배달] ⚠️ 후퇴 동작 미완료 (비상정지 가능성)")
            
        return True
    except Exception as e:
        print(f"[식판배달] 오류: {e}")
        return False

# ============================================================================
# 주문 처리 (부분 실행 기능 포함)
# ============================================================================
def process_order(order):
    # 예외처리 5: 키 부재 시 DB 오염 방지 및 무시
    key = order.get("_key")
    if not key:
        print("[Order] ❌ _key 없는 주문 무시")
        return

    sub_dishes = order.get("sub_dishes", [])
    main_dish  = order.get("main_dish", "")
    
    # 부분 실행 파라미터 파싱
    target_stage = order.get("target_stage", 0)  # 0이면 전체 실행
    run_mode     = order.get("run_mode", "from") # "only" 또는 "from"

    print(f"\n[Order] ===== 주문 시작: {key} =====")
    print(f"        sub={sub_dishes}  main={main_dish}")
    if target_stage > 0:
        mode_str = "만 실행" if run_mode == "only" else "부터 실행"
        print(f"        [부분실행 모드] {target_stage}단계 {mode_str}")

    valid_subs = [d for d in sub_dishes[:3] if d in SUB_WAYPOINTS]

    n_sub = len(valid_subs)
    total = 8 + (7 * n_sub) + 11 + 13 + 10

    global _progress_step, _progress_total
    _progress_step  = 0
    _progress_total = total

    reset_progress(total)
    
    if FIREBASE_AVAILABLE:
        db.reference(f"/orders/{key}").update({"status": "processing"})
        
    update_status(state="moving", current_task="주문 처리 시작")

    # 실행 여부 판별 헬퍼 함수
    def should_run(current_stage):
        if target_stage == 0:
            return True
        if run_mode == "only" and current_stage == target_stage:
            return True
        if run_mode == "from" and current_stage >= target_stage:
            return True
        return False

    try:
        # ════════════════════════════════════════════════════════════
        # 🍱 [STAGE 1] 식판 세팅
        # ════════════════════════════════════════════════════════════
        if should_run(1):
            report_order_status(key, "식판 세팅") # 토픽 쏘기!
            update_status(current_task="🍱 [1/5] 식판 세팅")
            if not run_tray_setup(): raise RuntimeError("emergency_stop")
            log_step("🍱 [1/5] 식판 세팅 완료", done=True)
        else:
            log_step("⏭️ [1/5] 식판 세팅 건너뜀", done=True)

        # ════════════════════════════════════════════════════════════
        # 🥗 [STAGE 2] 서브 반찬 담기
        # ════════════════════════════════════════════════════════════
        if should_run(2):
            report_order_status(key, "서브 반찬") # 토픽 쏘기!
            for idx, dish in enumerate(valid_subs):
                update_status(current_task=f"🥗 [2/5] 서브 {idx+1}/{n_sub} - [{dish}]")
                if not run_sub_dish(dish, SUB_WAYPOINTS[dish]): raise RuntimeError("emergency_stop")
                _movej(HOME_J)
                log_step(f"🥗 [2/5] 서브 [{dish}] 완료", done=True)
        else:
            log_step("⏭️ [2/5] 서브 반찬 담기 건너뜀", done=True)

        # ════════════════════════════════════════════════════════════
        # 🍖 [STAGE 3] 메인 반찬 담기
        # ════════════════════════════════════════════════════════════
        if should_run(3):
            report_order_status(key, "메인 반찬") # 토픽 쏘기!
            update_status(current_task=f"🍖 [3/5] 메인 반찬 담기 - [{main_dish}]")
            if not run_main_dish(): raise RuntimeError("emergency_stop")
            log_step("🍖 [3/5] 메인 반찬 완료", done=True)
        else:
            log_step("⏭️ [3/5] 메인 반찬 담기 건너뜀", done=True)

        # ════════════════════════════════════════════════════════════
        # 🍚 [STAGE 4] 밥 담기
        # ════════════════════════════════════════════════════════════
        if should_run(4):
            report_order_status(key, "밥 담기") # 토픽 쏘기
            update_status(current_task="🍚 [4/5] 밥 담기")
            if not run_rice(): raise RuntimeError("emergency_stop")
            log_step("🍚 [4/5] 밥 담기 완료", done=True)
            _movej(HOME_J)
        else:
            log_step("⏭️ [4/5] 밥 담기 건너뜀", done=True)

        # ════════════════════════════════════════════════════════════
        # 📦 [STAGE 5] 식판 배달
        # ════════════════════════════════════════════════════════════
        if should_run(5):
            report_order_status(key, "픽업 장소") # 토픽 쏘기!    
            update_status(current_task="📦 [5/5] 식판 픽업장소로 배달")
            if not run_tray_delivery(): raise RuntimeError("emergency_stop")
            log_step("📦 [5/5] 식판 배달 완료", done=True)
            _movej(HOME_J)
        else:
            log_step("⏭️ [5/5] 식판 배달 건너뜀", done=True)

        # ════════════════════════════════════════════════════════════
        # ✅ 주문 완료
        # ════════════════════════════════════════════════════════════
        update_status(
            state="idle",
            current_task="대기 중",
            progress=100,
            current_step="완료",
        )
        log_step("🎉 주문 완료!", done=True)
        
        report_order_status(key, "completed") # 토픽 쏘기!    


        if FIREBASE_AVAILABLE:
            db.reference(f"/orders/{key}").update({"status": "completed"})
        print(f"[Order] ✅ 완료: {key}")

    except Exception as e:
        print(f"[Order] ❌ 오류: {e}")
        log_step(f"❌ 오류: {e}")

        report_order_status(key, "error") # 토픽 쏘기!
        
        if FIREBASE_AVAILABLE:
            db.reference(f"/orders/{key}").update({"status": "error"})
        update_status(state="error", current_task=f"오류: {e}")


# ============================================================================
# 명령 처리
# ============================================================================
def handle_command(cmd_type):
    print(f"[CMD] {cmd_type}")

    # 예외처리 3: 비상정지 자동해제 삭제 및 수동 Resume 추가
    if cmd_type == "emergency_stop":
        try:
            drl_script_stop(1)
        except Exception as e:
            print(f"[CMD] stop 오류: {e}")
        update_status(state="error", current_task="⛔ 비상정지 - 웹에서 재개 버튼 필요")
        # flag 자동 clear 제거

    elif cmd_type == "resume":
        if emergency_stop_flag.is_set():
            emergency_stop_flag.clear()
            update_status(state="idle", current_task="대기 중")
            print("[CMD] ✅ 비상정지 해제 - 작업 재개 가능")

    elif cmd_type == "move_home":
        update_status(state="moving", current_task="홈 이동 중")
        movej(posj(HOME_J), vel=VELOCITY, acc=ACC)
        mwait()
        update_status(state="idle", current_task="대기 중")

    elif cmd_type == "gripper_open":
        gripper_50mm()

    elif cmd_type == "gripper_close":
        gripper_5mm()

    elif cmd_type == "gripper_full_open":
        gripper_100mm()


# ============================================================================
# 로봇 상태 및 충돌 감시 스레드 (예외처리 7)
# ============================================================================
def robot_state_monitor_loop():
    global is_collision_mode
    from DSR_ROBOT2 import get_robot_state

    while rclpy.ok():
        try:
            state = get_robot_state()
            if state in [3, 5, 6, 7]:
                if not is_collision_mode:
                    print(f"🚨 충돌/비상정지 감지 state={state}")
                    is_collision_mode = True
                    emergency_stop_flag.set()
                    update_status(state="error", current_task="🚨 충돌 감지")
                    if FIREBASE_AVAILABLE:
                        db.reference("/robot_status").update({"collision": True})
            elif state == 1 and is_collision_mode:
                print("✅ 로봇 STANDBY 복귀 - 웹 재개 대기")
                is_collision_mode = False
                if FIREBASE_AVAILABLE:
                    db.reference("/robot_status").update({
                        "collision": False, "resume_available": True
                    })
        except Exception:
            pass
        time.sleep(0.5)


# ============================================================================
# 작업 스레드
# ============================================================================
def perform_task_loop():
    print("[Task] 작업 스레드 시작")
    update_status(state="idle", current_task="대기 중")
    print("[Task] ✅ 주문 대기 중...")

    while rclpy.ok():
        try:
            if command_event.is_set():
                cmd = pending_command["type"]
                command_event.clear()
                if cmd:
                    handle_command(cmd)
                continue

            try:
                order = order_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            process_order(order)

        except Exception as e:
            print(f"[Task] 루프 오류: {e}")
            update_status(state="error", current_task=f"오류: {e}")
            time.sleep(1.0)

    print("[Task] 작업 스레드 종료")


# ============================================================================
# ROS 스핀 스레드
# ============================================================================
def ros_spin_thread():
    global node_
    print("[ROS] 스핀 스레드 시작")
    try:
        executor = MultiThreadedExecutor(num_threads=4)
        executor.add_node(node_)
        executor.spin()
    except Exception as e:
        if rclpy.ok():
            node_.get_logger().error(f"[ROS] spin 오류: {e}")
    finally:
        print("[ROS] 스핀 스레드 종료")

# ============================================================================
# 💡 핵심 추가: ROS 2 토픽 구독(Subscriber) 콜백 함수
# ============================================================================
def ros_order_callback(msg):
    import json
    try:
        order_data = json.loads(msg.data)
        key = order_data.get("_key")
        
        if not key:
            return

        # 예외처리 6: 중복 처리 방지 (이미 큐에 넣었거나 처리한 주문인지 확인)
        if key in processed_order_keys:
            return
        
        processed_order_keys.add(key)
        order_queue.put(order_data)
        print(f"[ROS Topic] 🔔 새 주문 수신 및 큐 추가: {key}")
        
    except Exception as e:
        print(f"[ROS Topic] JSON 파싱 오류: {e}")

def report_order_status(key, status):
    import json
    from std_msgs.msg import String
    global order_status_pub
    
    if order_status_pub and key:
        msg = String()
        msg.data = json.dumps({"_key": key, "status": status})
        order_status_pub.publish(msg)
        print(f"[Topic] 📡 DB에 상태 보고 전송: {key} -> {status}")

# ============================================================================
# main
# ============================================================================
def main(args=None):
    global node_
    global movej, movel, mwait, posj, posx
    global set_tool, set_tcp
    global set_digital_output, get_digital_input, wait
    global drl_script_stop

    rclpy.init(args=args)
    node_ = rclpy.create_node("lunchbox_robot_node", namespace=ROBOT_ID)
    DR_init.__dsr__node = node_
    print(f"[Main] 노드 '{ROBOT_ID}/lunchbox_robot_node' 생성")


    # 💡 팩트 체크 반영: 데이터베이스 노드가 쏘는 'robot_order' 토픽을 구독하기 위해 귀를 엽니다.
    from std_msgs.msg import String
    node_.create_subscription(String, '/robot_order', ros_order_callback, 10)    
    
    # 기존 구독(Subscriber) 코드 바로 아래에 추가합니다.
    global order_status_pub
    order_status_pub = node_.create_publisher(String, '/order_status', 10)

    try:
        from DSR_ROBOT2 import (
            movej, movel, mwait,
            set_tool, set_tcp,
            set_digital_output, get_digital_input,
            wait,
            drl_script_stop,
            DR_BASE,
        )
        from DR_common2 import posj, posx
    except ImportError as e:
        print(f"[Main] DSR_ROBOT2 import 실패: {e}")
        rclpy.shutdown()
        return

    # ROS 스핀 먼저 시작
    t_spin = threading.Thread(target=ros_spin_thread)
    t_spin.start()

    # 예외처리 10: 초기 홈 이동 실패 시 리스너 미구동 예외처리 강화
    print("[Main] 홈 위치로 초기화 이동 중...")
    try:
        set_tool("Tool Weight_2FG")
        set_tcp("2FG_TCP")
        movej(posj(HOME_J), vel=VELOCITY, acc=ACC)
        mwait()
        gripper_100mm()
        print("[Main] ✅ 홈 위치 완료")
    except Exception as e:
        print(f"[Main] ❌ 초기 홈 이동 실패: {e} → 종료")
        rclpy.shutdown()
        return

    # 홈 위치 안착 성공 시에만 Firebase 리스너 및 각종 스레드 시작
    if init_firebase():
        start_firebase_listeners()

    # 충돌 감지 모니터 스레드 (예외처리 7)
    t_monitor = threading.Thread(target=robot_state_monitor_loop, daemon=True)
    t_monitor.start()

    t_status = threading.Thread(target=status_upload_thread, daemon=True)
    t_robot  = threading.Thread(target=perform_task_loop)

    t_status.start()
    t_robot.start()

    try:
        t_robot.join()
        t_spin.join()
    except KeyboardInterrupt:
        print("\n[Main] Ctrl+C 감지")
    finally:
        if rclpy.ok():
            rclpy.shutdown()
        print("[Main] 종료 완료")

if __name__ == "__main__":
    main()