#!/usr/bin/env python3
"""
ROS2 → WebSocket Bridge for M0609 Robot Motion Dashboard
=========================================================
Setup:
  pip install websockets

Run (source your ROS2 workspace first):
  source /opt/ros/humble/setup.bash
  source ~/cobot_ws/install/setup.bash
  python3 ros2_ws_bridge.py

Then open dashboard.html in your browser.
WebSocket listens on ws://localhost:8765
"""

import asyncio
import json
import math
import threading
import time
from typing import Set

import re

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from sensor_msgs.msg import JointState
from std_msgs.msg import String

try:
    from dsr_msgs2.msg import RobotError
    HAS_DSR_ERROR = True
except ImportError:
    HAS_DSR_ERROR = False

import websockets
from websockets.server import WebSocketServerProtocol

# ── Configuration ──────────────────────────────────────────────────────────
WS_HOST = 'localhost'
WS_PORT = 8765

# Publish rate cap for joint_states forwarding (Hz)
JOINT_PUBLISH_HZ = 20
JOINT_PUBLISH_INTERVAL = 1.0 / JOINT_PUBLISH_HZ

# ── Shared broadcast queue (thread-safe via asyncio queue bridge) ───────────
_loop: asyncio.AbstractEventLoop = None
_clients: Set[WebSocketServerProtocol] = set()
_clients_lock = threading.Lock()


def broadcast_sync(payload: dict) -> None:
    """Called from ROS2 callbacks (non-async thread). Posts to the WS loop."""
    if _loop is None or not _clients:
        return
    msg = json.dumps(payload)
    asyncio.run_coroutine_threadsafe(_broadcast_async(msg), _loop)


async def _broadcast_async(msg: str) -> None:
    with _clients_lock:
        targets = list(_clients)
    if not targets:
        return
    await asyncio.gather(*[c.send(msg) for c in targets], return_exceptions=True)


# ── ROS2 Node ──────────────────────────────────────────────────────────────
class BridgeNode(Node):
    def __init__(self):
        super().__init__('ros2_ws_bridge')

        self._last_joint_pub = 0.0
        self._target_posj = None

        self.create_subscription(
            JointState,
            '/dsr01/joint_states',
            self._on_joint_states,
            10,
        )

        if HAS_DSR_ERROR:
            self.create_subscription(
                RobotError,
                '/dsr01/error',
                self._on_robot_error,
                10,
            )
        else:
            self.get_logger().warn(
                'dsr_msgs2 not found — /dsr01/error will not be bridged'
            )

        # Timer: forward current TCP position and stage info at 5 Hz
        self.create_timer(0.2, self._publish_extras)

        # Stage tracking — updated from /robot_status topic
        self._stage_times = [0.0] * 5
        self._stage_start_ts = [None] * 5  # when each stage first became active
        self._active_stage = -1

        self.create_subscription(String, '/robot_status',     self._on_robot_status,   10)
        self.create_subscription(String, '/robot_tcp_posx',   self._on_tcp_posx,       10)
        self.create_subscription(String, '/robot_target_posj',self._on_target_posj,    10)
        self.create_subscription(String, '/robot_torque',     self._on_torque,         10)

        # ── 모션 세그먼트 비교 분석용 ─────────────────────────────────────────
        # /robot_motion_segment 토픽:
        #   {"type": "seg_start", "seg_id": str, "motion": "sync"|"async", "label": str}
        #   {"type": "seg_end",   "seg_id": str}
        # 세그먼트 진행 중에는 joint_states를 버퍼에 쌓아두고
        # seg_end 수신 시 완성된 세그먼트를 브로드캐스트.
        self._active_seg: dict | None = None   # 현재 기록 중인 세그먼트
        self._seg_buf_pos: list = []           # 세그먼트 내 위치 스냅샷
        self._seg_buf_vel: list = []           # 세그먼트 내 속도 스냅샷
        self._seg_buf_ts:  list = []           # 상대 타임스탬프(ms)
        self._seg_start_wall: float = 0.0
        self._completed_segments: list = []   # 완료된 세그먼트 목록 (max 20개 보관)

        self.create_subscription(String, '/robot_motion_segment',
                                 self._on_motion_segment, 10)

        self.get_logger().info(
            f'BridgeNode started — broadcasting on ws://{WS_HOST}:{WS_PORT}'
        )

    # ── /dsr01/joint_states ────────────────────────────────────────────────
    def _on_joint_states(self, msg: JointState) -> None:
        now = time.time()

        pos_deg = [math.degrees(v) for v in msg.position]
        vel_deg = [math.degrees(v) for v in msg.velocity]

        # 세그먼트 기록 중이면 버퍼에 적재 (rate 제한 없이 전부 수집)
        if self._active_seg is not None:
            rel_ms = round((now - self._seg_start_wall) * 1000, 1)
            self._seg_buf_ts.append(rel_ms)
            self._seg_buf_pos.append(pos_deg)
            self._seg_buf_vel.append(vel_deg)

        if now - self._last_joint_pub < JOINT_PUBLISH_INTERVAL:
            return
        self._last_joint_pub = now

        # eff는 DSR 드라이버가 NaN을 보내므로 joint_states에서 제외.
        # 토크는 /robot_torque 토픽(_on_torque)에서 별도 수신.
        broadcast_sync({
            'type': 'joint_states',
            'pos':  pos_deg,
            'vel':  vel_deg,
            'mode': 'AUTO',
        })

        # Also forward actual joint positions for tracking error graph
        broadcast_sync({
            'type': 'actual_posj',
            'data': pos_deg,
        })

    # ── /robot_motion_segment ─────────────────────────────────────────────
    def _on_motion_segment(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except Exception:
            return

        evt = data.get('type')

        if evt == 'seg_start':
            self._active_seg = {
                'seg_id': data.get('seg_id', ''),
                'motion': data.get('motion', 'sync'),   # 'sync' | 'async'
                'label':  data.get('label', ''),
            }
            self._seg_buf_ts  = []
            self._seg_buf_pos = []
            self._seg_buf_vel = []
            self._seg_start_wall = time.time()
            self.get_logger().info(
                f"[seg] START {self._active_seg['seg_id']} ({self._active_seg['motion']})"
            )

        elif evt == 'seg_end' and self._active_seg is not None:
            duration_ms = round((time.time() - self._seg_start_wall) * 1000, 1)
            seg = {
                **self._active_seg,
                'duration_ms': duration_ms,
                'n_samples':   len(self._seg_buf_ts),
                'ts':          self._seg_buf_ts,
                'pos':         self._seg_buf_pos,   # list of [j1..j6]
                'vel':         self._seg_buf_vel,   # list of [j1..j6]
            }

            self.get_logger().info(
                f"[seg] END   {seg['seg_id']} → {duration_ms:.0f} ms "
                f"({seg['n_samples']} samples)"
            )

            # 최근 20개 세그먼트만 보관
            self._completed_segments.append(seg)
            if len(self._completed_segments) > 20:
                self._completed_segments.pop(0)

            self._active_seg = None

            # 완성된 세그먼트를 WebSocket으로 즉시 전송
            broadcast_sync({
                'type': 'motion_segment',
                'seg':  seg,
            })

            # 전체 세그먼트 목록도 갱신 브로드캐스트
            broadcast_sync({
                'type':     'segment_list',
                'segments': [
                    {k: v for k, v in s.items() if k not in ('pos', 'vel', 'ts')}
                    for s in self._completed_segments
                ],
            })

    # ── /robot_status ─────────────────────────────────────────────────────
    # current_task 예시: "🥗 [2/5] 서브 반찬 - [김치]", "🍖 [3/5] 메인 반찬"
    _STAGE_RE = re.compile(r'\[(\d)/5\]')

    def _on_robot_status(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except Exception:
            return

        task = payload.get('current_task', '')
        m = self._STAGE_RE.search(task)
        now = time.time()

        if m:
            stage_idx = int(m.group(1)) - 1  # 0-based
            if stage_idx != self._active_stage:
                self._active_stage = stage_idx
                if self._stage_start_ts[stage_idx] is None:
                    self._stage_start_ts[stage_idx] = now

            if self._stage_start_ts[stage_idx] is not None:
                self._stage_times[stage_idx] = round(now - self._stage_start_ts[stage_idx], 1)

        broadcast_sync({
            'type':   'stage_time',
            'stages': list(self._stage_times),
            'active': self._active_stage,
        })

        # joint_pos (deg) from state_manager → actual_posj for tracking error graph
        joint_pos = payload.get('joint_pos')
        if joint_pos and len(joint_pos) == 6:
            broadcast_sync({'type': 'actual_posj', 'data': joint_pos})

    # ── /dsr01/error ───────────────────────────────────────────────────────
    def _on_robot_error(self, msg) -> None:
        # RobotError fields vary by dsr_msgs2 version — broadcast raw code
        broadcast_sync({
            'type':      'collision',
            'timestamp': time.time(),
            'code':      getattr(msg, 'error_code', 0),
        })
        self.get_logger().warn(f'Collision/Error event: {msg}')

    def _on_tcp_posx(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)  # [x,y,z,rx,ry,rz] in mm/deg
            broadcast_sync({'type': 'posx', 'data': data})
        except Exception:
            pass

    def _on_target_posj(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)  # [j1..j6] in deg
            broadcast_sync({'type': 'target_posj', 'data': data})
        except Exception:
            pass

    def _on_torque(self, msg: String) -> None:
        try:
            eff = json.loads(msg.data)   # [j1..j6] external torque Nm
            broadcast_sync({'type': 'torque', 'eff': eff})
        except Exception:
            pass

    # ── Extras timer ──────────────────────────────────────────────────────
    def _publish_extras(self) -> None:
        # stage_time은 _on_robot_status에서 실시간으로 처리됨
        pass


# ── WebSocket server ────────────────────────────────────────────────────────
async def ws_handler(ws: WebSocketServerProtocol) -> None:
    with _clients_lock:
        _clients.add(ws)
    try:
        async for raw in ws:
            # Accept target_posj from dashboard/external sender
            try:
                msg = json.loads(raw)
                if msg.get('type') == 'target_posj':
                    await _broadcast_async(json.dumps(msg))
            except Exception:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        with _clients_lock:
            _clients.discard(ws)


async def ws_main() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    async with websockets.serve(ws_handler, WS_HOST, WS_PORT):
        print(f'[WS] Listening on ws://{WS_HOST}:{WS_PORT}')
        await asyncio.Future()  # run forever


# ── Entry point ─────────────────────────────────────────────────────────────
def main() -> None:
    rclpy.init()
    node = BridgeNode()

    executor = MultiThreadedExecutor()
    executor.add_node(node)

    # ROS2 spins in background thread
    ros_thread = threading.Thread(target=executor.spin, daemon=True)
    ros_thread.start()

    # WebSocket runs in the main thread's asyncio loop
    try:
        asyncio.run(ws_main())
    except KeyboardInterrupt:
        print('\n[Bridge] Shutting down...')
    finally:
        executor.shutdown(wait=False)
        rclpy.shutdown()


if __name__ == '__main__':
    main()
