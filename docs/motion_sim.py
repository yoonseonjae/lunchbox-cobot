#!/usr/bin/env python3
"""
서브반찬 Pick & Place 동기 vs 비동기 모션 시뮬레이터
실제 robot_coordinates.yaml 좌표 사용
"""

import asyncio
import json
import math
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import threading
import time

import websockets
from websockets.server import WebSocketServerProtocol

try:
    import rclpy
    from sensor_msgs.msg import JointState
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
# COBOT_WS_SRC 환경변수를 설정하면 어떤 PC에서도 동작합니다.
# 예) export COBOT_WS_SRC=/home/<user>/cobot_ws/src
_COBOT_WS_SRC = Path(os.environ.get(
    'COBOT_WS_SRC',
    str(Path(__file__).parent.parent),
))
URDF_DIR  = _COBOT_WS_SRC / 'm0609_rg2_combined'
URDF_FILE = 'm0609_rg2_web.urdf'

HTTP_HOST = 'localhost'
HTTP_PORT = 8080
WS_HOST   = 'localhost'
WS_PORT   = 8765

ROS_JOINT_TOPIC = '/dsr01/joint_states_combined'
ROS_JOINT_NAMES = ['joint_1','joint_2','joint_3','joint_4','joint_5','joint_6']

# ── 실제 프로젝트 좌표 (robot_coordinates.yaml) ───────────────────────────────
HOME_J = [0.002, -0.043, 90.041, 0.001, 89.997, 0.004]

DISHES = {
    '피클': {
        'pre_pick_j': [-8.340,  56.090,  29.960, -4.980,  93.790,  -7.070],
        'pick_l':     [697.470,-123.777,  15.479, 81.446,-175.702,  82.563],
        'up_pick_l':  [697.546,-123.664,  79.440, 86.210,-175.680,  -2.570],
    },
    '단무지': {
        'pre_pick_j': [-1.170,  54.394,  33.207, -4.953,  92.804,  -0.987],
        'pick_l':     [697.415, -35.009,  15.485, 81.387,-175.701,  82.547],
        'up_pick_l':  [697.576, -34.942,  79.564, 81.785,-175.704,  82.944],
    },
    '김치': {
        'pre_pick_j': [ 5.198,  55.341,  31.445, -4.888,  94.157,   5.287],
        'pick_l':     [697.571,  42.818,  15.515, 83.579,-175.347,  83.802],
        'up_pick_l':  [697.593,  42.839,  79.590, 83.629,-175.347,  83.847],
    },
}

SLOTS = {
    0: {
        'pre_place_j': [-6.830,   4.070, 104.590, -4.530,  71.120, -93.860],
        'place_l':     [374.034, -62.496,  35.810, 87.670,-175.940,  -1.240],
    },
    1: {
        'pre_place_j': [ 4.960,   4.095, 104.571, -4.469,  71.995, -82.152],
        'place_l':     [373.967,  15.158,  35.716, 87.480,-175.942,  -1.435],
    },
    2: {
        'pre_place_j': [16.505,   6.288, 104.167, -4.238,  73.054, -70.755],
        'place_l':     [375.281,  89.973,  35.635, 86.700,-175.761,  -2.159],
    },
}

# 서브반찬 3개 순서
DISH_ORDER = [('피클', 0), ('단무지', 1), ('김치', 2)]

# ── 시뮬레이션 파라미터 ────────────────────────────────────────────────────────
VEL_DEG = 50.0
ACC_DEG = 50.0
DT      = 0.05
RADIUS  = 40.0

# ── M0609 DH 파라미터 ─────────────────────────────────────────────────────────
DH = [
    (0.0,    0.1555,  math.pi/2,  0),
    (0.409,  0.0,     0,          0),
    (0.0,    0.0,     math.pi/2,  0),
    (0.0,    0.3625, -math.pi/2,  0),
    (0.0,    0.0,     math.pi/2,  0),
    (0.0,    0.1160,  0,          0),
]

def fk_tcp(q_deg):
    T = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
    def mm(A, B):
        C = [[0]*4 for _ in range(4)]
        for i in range(4):
            for j in range(4):
                C[i][j] = sum(A[i][k]*B[k][j] for k in range(4))
        return C
    for i, (a, d, alpha, off) in enumerate(DH):
        t = math.radians(q_deg[i]) + off
        ca, sa = math.cos(alpha), math.sin(alpha)
        ct, st = math.cos(t), math.sin(t)
        T = mm(T, [[ct,-st,0,a],[st*ca,ct*ca,-sa,-sa*d],[st*sa,ct*sa,ca,ca*d],[0,0,0,1]])
    return [T[0][3]*1000, T[1][3]*1000, T[2][3]*1000]

# ── 트라페조이달 속도 프로필 ───────────────────────────────────────────────────

def trapezoid_joint(q_start, q_end, vmax, amax, dt, blend=0.0):
    """q_start → q_end joint 보간. 절대각 반환."""
    delta = [q_end[j] - q_start[j] for j in range(6)]
    max_d = max(abs(d) for d in delta)
    if max_d < 1e-4:
        return [0.0], [q_start[:]], [[0.0]*6]

    d_acc = vmax**2 / (2 * amax)
    if 2*d_acc >= max_d:
        vp = math.sqrt(max_d * amax); ta = vp/amax; tf = 0.0
    else:
        vp = vmax; ta = vmax/amax; tf = (max_d - 2*d_acc)/vmax

    T_full = 2*ta + tf
    T_end  = T_full - (blend/vmax) if blend > 0 else T_full
    T_end  = max(T_end, T_full*0.4)

    steps = max(2, int(T_end/dt)+1)
    ts, pos, vel = [], [], []
    q = q_start[:]

    for k in range(steps):
        t = k*dt
        if   t < ta:          vs = amax*t
        elif t < ta+tf:       vs = vp
        else:                 vs = max(0.0, vp - amax*(t-ta-tf))
        v = [vs*delta[j]/max_d for j in range(6)]
        q = [q[j] + v[j]*dt for j in range(6)]
        ts.append(round(t*1000, 1))
        pos.append([round(x,3) for x in q])
        vel.append([round(x,4) for x in v])

    return ts, pos, vel


def simulate_subdish_sync(dish_name, slot_idx):
    """
    동기 구간: HOME → pre_pick_j → (pick_l은 TCP 공간이므로 joint 근사 생략,
    대신 pick_l 자세를 pre_pick_j에서 약간 내려가는 것으로 근사)
    실제 좌표 기반.
    """
    d = DISHES[dish_name]
    # joint 보간만 사용 (movel은 joint 근사: pick_l ≈ pre_pick_j + Z 하강)
    waypoints = [
        HOME_J,
        d['pre_pick_j'],
        # pick_l: pre_pick_j에서 J2 +5deg (아래로 내려가는 근사)
        [d['pre_pick_j'][0], d['pre_pick_j'][1]+5, d['pre_pick_j'][2],
         d['pre_pick_j'][3], d['pre_pick_j'][4], d['pre_pick_j'][5]],
    ]

    ts_all, pos_all, vel_all = [], [], []
    t_off = 0.0
    for i in range(len(waypoints)-1):
        ts, pos, vel = trapezoid_joint(waypoints[i], waypoints[i+1], VEL_DEG, ACC_DEG, DT)
        # 완전 정지: 3프레임 유지
        for _ in range(3):
            ts.append(round(ts[-1]/1000*1000 + DT*1000, 1))
            pos.append(pos[-1][:])
            vel.append([0.0]*6)
        for k, t in enumerate(ts):
            ts_all.append(round(t + t_off*1000, 1))
            pos_all.append(pos[k])
            vel_all.append(vel[k])
        t_off += ts[-1]/1000

    return ts_all, pos_all, vel_all, round(t_off*1000, 1)


def simulate_subdish_async(dish_name, slot_idx):
    """
    비동기 구간: up_pick_l(근사) → pre_place_j → place_l(근사)
    radius=40 블렌딩으로 연속 이동.
    """
    d = DISHES[dish_name]
    s = SLOTS[slot_idx]
    pick_end = [d['pre_pick_j'][0], d['pre_pick_j'][1]+5, d['pre_pick_j'][2],
                d['pre_pick_j'][3], d['pre_pick_j'][4], d['pre_pick_j'][5]]
    # up_pick_l ≈ pre_pick_j (들어올림: J2 -5 복귀)
    up_j = d['pre_pick_j'][:]
    waypoints = [pick_end, up_j, s['pre_place_j']]

    ts_all, pos_all, vel_all = [], [], []
    t_off = 0.0
    for i in range(len(waypoints)-1):
        is_last = (i == len(waypoints)-2)
        blend = 0.0 if is_last else RADIUS
        ts, pos, vel = trapezoid_joint(waypoints[i], waypoints[i+1], VEL_DEG, ACC_DEG, DT, blend=blend)
        # 블렌딩: 이전 구간과 겹침
        overlap = (RADIUS/VEL_DEG)*0.6 if i > 0 else 0.0
        t_off = max(0.0, t_off - overlap)
        for k, t in enumerate(ts):
            ts_all.append(round(t + t_off*1000, 1))
            pos_all.append(pos[k])
            vel_all.append(vel[k])
        t_off += ts[-1]/1000

    return ts_all, pos_all, vel_all, round(t_off*1000, 1)


# ── ROS2 publish ──────────────────────────────────────────────────────────────
_ros_node = None
_ros_pub  = None

def init_ros():
    global _ros_node, _ros_pub
    if not ROS_AVAILABLE: return
    rclpy.init()
    _ros_node = rclpy.create_node('motion_sim')
    _ros_pub  = _ros_node.create_publisher(JointState, ROS_JOINT_TOPIC, 10)
    print(f"[ROS2] → {ROS_JOINT_TOPIC}")
    rclpy.spin(_ros_node)

def publish_joint_states(q_deg):
    if not ROS_AVAILABLE or _ros_pub is None: return
    msg = JointState()
    msg.header.stamp = _ros_node.get_clock().now().to_msg()
    msg.name     = ROS_JOINT_NAMES
    msg.position = [math.radians(v) for v in q_deg]
    msg.velocity = [0.0]*6
    msg.effort   = [0.0]*6
    _ros_pub.publish(msg)

# ── WebSocket ─────────────────────────────────────────────────────────────────
clients: set = set()

async def stream_frames(ws, pos_list, vel_list, mode_label):
    for i in range(len(pos_list)):
        q = pos_list[i]
        tcp = fk_tcp(q)
        publish_joint_states(q)
        await ws.send(json.dumps({'type':'joint_states','pos':q,'vel':vel_list[i],'mode':mode_label}))
        await ws.send(json.dumps({'type':'posx','data':tcp+[0,0,0]}))
        await ws.send(json.dumps({
            'type':'urdf_joints',
            'joints':{f'joint_{j+1}': math.radians(q[j]) for j in range(6)},
        }))
        await asyncio.sleep(DT * 0.5)

async def run_simulation(ws):
    await asyncio.sleep(0.5)
    URDF_URL = f'http://{HTTP_HOST}:{HTTP_PORT}/urdf/{URDF_FILE}'
    await ws.send(json.dumps({'type':'urdf_url','url':URDF_URL}))
    await asyncio.sleep(0.3)

    # ══ PHASE 1 : 동기 모션 전체 3종 ══════════════════════════════════
    sync_results = {}   # dish_name → (ts, pos, vel, dur)

    await ws.send(json.dumps({'type':'sim_status','text':'▶ PHASE 1 : 동기 모션 3종 (movej → movel)'}))
    print("[SIM] ══ PHASE 1 : 동기 모션 3종 ══")

    for dish_name, slot_idx in DISH_ORDER:
        d = DISHES[dish_name]
        s = SLOTS[slot_idx]
        sync_id = f'sub_sync_{dish_name}'

        status = f'SYNC [{dish_name}] HOME→pre_pick_j→pick_l→place→HOME'
        print(f"[SIM] {status}")
        await ws.send(json.dumps({'type':'sim_status','text':status}))

        # HOME → pre_pick_j → pick_down (동기)
        ts_s, pos_s, vel_s, dur_s = simulate_subdish_sync(dish_name, slot_idx)
        await stream_frames(ws, pos_s, vel_s, 'SIM·SYNC')

        # 그리퍼 파지 대기
        await asyncio.sleep(0.4)

        # pick_down → pre_place_j → place_down → HOME (동기 방식: 완전 정지)
        q_cur = pos_s[-1]
        place_j   = s['pre_place_j']
        place_down = [place_j[0], place_j[1]+3, place_j[2], place_j[3], place_j[4], place_j[5]]
        for wpt in [place_j, place_down, HOME_J]:
            ts_r, pos_r, vel_r = trapezoid_joint(q_cur, wpt, VEL_DEG, ACC_DEG, DT)
            await stream_frames(ws, pos_r, vel_r, 'SIM·SYNC')
            q_cur = pos_r[-1]
            await asyncio.sleep(0.15)   # 완전 정지

        # 총 소요시간 = SYNC pick 구간 + return 구간 (단순화: dur_s + 추가 이동)
        await ws.send(json.dumps({'type':'motion_segment','seg':{
            'seg_id':sync_id,'motion':'sync',
            'label':f'{dish_name} 전체 (동기: movej→movel, 완전정지)',
            'duration_ms':dur_s,'n_samples':len(ts_s),
            'ts':ts_s,'pos':pos_s,'vel':vel_s,
        }}))
        sync_results[dish_name] = (ts_s, pos_s, vel_s, dur_s)
        print(f"[SIM]   SYNC {dish_name}: {dur_s} ms")
        await asyncio.sleep(0.5)

    # ══ PHASE 2 : 비동기 모션 전체 3종 ════════════════════════════════
    await ws.send(json.dumps({'type':'sim_status','text':'▶ PHASE 2 : 비동기 모션 3종 (amovel → amovej, r=40°)'}))
    print("[SIM] ══ PHASE 2 : 비동기 모션 3종 ══")

    for dish_name, slot_idx in DISH_ORDER:
        d = DISHES[dish_name]
        s = SLOTS[slot_idx]
        sync_id  = f'sub_sync_{dish_name}'
        async_id = f'sub_async_{dish_name}'

        status = f'ASYNC [{dish_name}] HOME→pick→(blend)up_pick→pre_place→place→HOME'
        print(f"[SIM] {status}")
        await ws.send(json.dumps({'type':'sim_status','text':status}))

        # HOME → pre_pick_j → pick_down (동기 진입, 짧게)
        ts_s, pos_s, vel_s, dur_s = simulate_subdish_sync(dish_name, slot_idx)
        await stream_frames(ws, pos_s, vel_s, 'SIM·SYNC')
        await asyncio.sleep(0.4)

        # up_pick → pre_place_j (비동기, radius=40 블렌딩)
        ts_a, pos_a, vel_a, dur_a = simulate_subdish_async(dish_name, slot_idx)
        await stream_frames(ws, pos_a, vel_a, 'SIM·ASYNC')

        # pre_place → place_down → HOME (비동기 이후 마무리)
        q_cur = pos_a[-1]
        place_j    = s['pre_place_j']
        place_down = [place_j[0], place_j[1]+3, place_j[2], place_j[3], place_j[4], place_j[5]]
        for wpt in [place_down, HOME_J]:
            ts_r, pos_r, vel_r = trapezoid_joint(q_cur, wpt, VEL_DEG, ACC_DEG, DT)
            await stream_frames(ws, pos_r, vel_r, 'SIM·ASYNC')
            q_cur = pos_r[-1]

        await ws.send(json.dumps({'type':'motion_segment','seg':{
            'seg_id':async_id,'motion':'async',
            'label':f'{dish_name} 전체 (비동기: amovel→amovej, r=40°)',
            'duration_ms':dur_a,'n_samples':len(ts_a),
            'ts':ts_a,'pos':pos_a,'vel':vel_a,
        }}))
        dur_s = sync_results[dish_name][3]
        print(f"[SIM]   ASYNC {dish_name}: {dur_a} ms  (-{dur_s-dur_a:.0f} ms, {(dur_s-dur_a)/dur_s*100:.1f}%↑)")

        await asyncio.sleep(0.3)
        await ws.send(json.dumps({
            'type':'auto_compare',
            'sync_seg_id':sync_id,
            'async_seg_id':async_id,
        }))
        await asyncio.sleep(0.5)

    await ws.send(json.dumps({'type':'sim_status','text':'✅ 완료 — ⚡ 클릭하면 비교 그래프'}))
    print("[SIM] 완료")

async def ws_handler(ws: WebSocketServerProtocol):
    clients.add(ws)
    print(f"[WS] 연결 ({len(clients)}개)")
    try:
        await run_simulation(ws)
        async for _ in ws: pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        clients.discard(ws)

# ── HTTP ─────────────────────────────────────────────────────────────────────
class MeshHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(URDF_DIR), **kwargs)
    def translate_path(self, path):
        if path.startswith('/urdf/'): path = path[6:]
        elif path.startswith('/urdf'): path = path[5:]
        return str(URDF_DIR / path.lstrip('/'))
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','*')
        super().end_headers()
    def do_OPTIONS(self):
        self.send_response(200); self.end_headers()
    def log_message(self, *a): pass

def start_http():
    HTTPServer((HTTP_HOST, HTTP_PORT), MeshHandler).serve_forever()

async def ws_main():
    async with websockets.serve(ws_handler, WS_HOST, WS_PORT):
        print(f"[WS] ws://{WS_HOST}:{WS_PORT}")
        await asyncio.Future()

def main():
    print("=" * 55)
    print("  서브반찬 3종 (피클/단무지/김치) 동기 vs 비동기")
    print("  실제 robot_coordinates.yaml 좌표 사용")
    print("=" * 55)
    threading.Thread(target=start_http, daemon=True).start()
    if ROS_AVAILABLE:
        threading.Thread(target=init_ros, daemon=True).start()
        time.sleep(0.5)
    else:
        print("[경고] rclpy 없음 — RViz2 연동 비활성화")
    print(f"[HTTP] http://{HTTP_HOST}:{HTTP_PORT}/urdf/")
    try:
        asyncio.run(ws_main())
    except KeyboardInterrupt:
        print("\n[SIM] 종료")

if __name__ == '__main__':
    main()
