#!/usr/bin/env python3
"""
==============================================================================
나만의 도련님 도시락 - 통합 관리자 웹 서버
==============================================================================
robot_dashboard.py + camera_stream_server.py 통합본.

단일 aiohttp 서버 (기본 포트 8080):
  GET /                → 로봇 모니터링 대시보드 (3D URDF + 관절/상태 + CCTV)
  GET /admin           → 주문 관리자 페이지 (admin_index.html)
  GET /events          → SSE – 0.2초마다 로봇 상태 JSON push
  GET /state           → 로봇 상태 JSON (디버그용)
  GET /video_feed      → USB 카메라 MJPEG 스트림
  GET /snapshot        → USB 카메라 단일 JPEG 스냅샷
  GET /urdf/...        → URDF 파일 서빙
  GET /urdf/meshes/    → 메시 파일 정적 서빙

실행:
  ros2 run lunchbox_web lunchbox_admin_server
  ros2 run lunchbox_web lunchbox_admin_server -- --camera 0 --fps 20 --port 8080
==============================================================================
"""

import argparse
import asyncio
import json
import math
import os
import threading
import time
from datetime import datetime
from typing import Optional

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from dsr_msgs2.msg import RobotError, RobotDisconnection
from std_msgs.msg import UInt8MultiArray
from dsr_msgs2.srv import (
    GetCurrentPosx, GetRobotMode, GetRobotState,
    GetRobotSpeedMode, GetLastAlarm,
)
from aiohttp import web

# cv2 선택적 import (카메라 없이도 대시보드 동작)
_CV2_OK = False
try:
    import cv2
    _CV2_OK = True
except ImportError:
    pass

# ── 경로 상수 ─────────────────────────────────────────────────────
_COBOT_WS_SRC = os.environ.get(
    'COBOT_WS_SRC',
    os.path.join(os.path.expanduser('~'), 'cobot_ws', 'src'),
)
_HERE      = os.path.dirname(os.path.abspath(__file__))
_URDF_DIR  = os.path.join(_HERE, '..', '..', 'm0609_rg2_combined')
if not os.path.isdir(_URDF_DIR):
    _URDF_DIR = os.path.join(_COBOT_WS_SRC, 'm0609_rg2_combined')
_URDF_FILE = os.path.join(_URDF_DIR, 'm0609_rg2_web.urdf')
_MESH_DIR  = os.path.join(_URDF_DIR, 'meshes')

_ADMIN_HTML = os.path.join(_HERE, '..', '..', 'lunchbox_web', 'admin_index.html')
if not os.path.isfile(_ADMIN_HTML):
    _ADMIN_HTML = os.path.join(_COBOT_WS_SRC, 'lunchbox_web', 'admin_index.html')

# ── 카메라 설정 (main()에서 채워짐) ──────────────────────────────
_cam_fps:     int = 20
_cam_quality: int = 70
_camera: Optional['CameraCapture'] = None


# ── 카메라 캡처 (백그라운드 스레드) ──────────────────────────────
class CameraCapture:
    """백그라운드 스레드에서 항상 최신 프레임을 보관."""

    def __init__(self, cam_index: int, width: int, height: int):
        print(f"[Camera] 카메라 인덱스 {cam_index} 열기...")
        self._cap = cv2.VideoCapture(cam_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"카메라 인덱스 {cam_index} 를 열 수 없습니다.")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[Camera] 실제 해상도: {w}x{h}")
        self._frame   = None
        self._lock    = threading.Lock()
        self._running = True
        threading.Thread(target=self._loop, daemon=True, name="cam_capture").start()

    def _loop(self):
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.5)
                continue
            with self._lock:
                self._frame = frame

    def get_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def release(self):
        self._running = False
        time.sleep(0.2)
        self._cap.release()


# ── 로봇 상태 공유 딕셔너리 (thread-safe) ────────────────────────
_lock = threading.Lock()
robot_state: dict = {
    "connection":       "disconnected",
    "joint_names":      [f"J{i+1}" for i in range(6)],
    "joint_positions":  [0.0] * 6,
    "joint_velocities": [0.0] * 6,
    "joint_efforts":    [0.0] * 6,
    "current_posx":     [0.0] * 6,
    "robot_mode":        -1,
    "robot_state_value": -1,
    "speed_mode":        -1,
    "last_alarm":        None,
    "errors":            [],
    "digital_io":        [0] * 16,
    "last_update":       0.0,
}


# ── ROS2 Node ─────────────────────────────────────────────────────
class RobotDashboardNode(Node):
    def __init__(self):
        super().__init__("robot_dashboard", namespace="dsr01")

        self.create_subscription(
            JointState,        "/dsr01/joint_states",                     self._cb_joints, 10)
        self.create_subscription(
            RobotError,        "/dsr01/error",                            self._cb_error,  10)
        self.create_subscription(
            RobotDisconnection,"/dsr01/robot_disconnection",               self._cb_disconn,10)
        self.create_subscription(
            UInt8MultiArray,   "/dsr01/io/ctrl_box_digital_input_state",   self._cb_io,     10)

        self._posx_cli  = self.create_client(GetCurrentPosx,    "/dsr01/aux_control/get_current_posx")
        self._mode_cli  = self.create_client(GetRobotMode,      "/dsr01/system/get_robot_mode")
        self._state_cli = self.create_client(GetRobotState,     "/dsr01/system/get_robot_state")
        self._speed_cli = self.create_client(GetRobotSpeedMode, "/dsr01/system/get_robot_speed_mode")
        self._alarm_cli = self.create_client(GetLastAlarm,      "/dsr01/system/get_last_alarm")

        self.create_timer(2.0, self._poll)
        self.create_timer(3.0, self._check_connection)

    def _check_connection(self):
        with _lock:
            age = time.time() - robot_state["last_update"]
            if robot_state["last_update"] == 0.0 or age > 5.0:
                robot_state["connection"] = "disconnected"

    def _cb_joints(self, msg):
        pos, vel, eff = [0.0]*6, [0.0]*6, [0.0]*6
        for i, name in enumerate(msg.name):
            if name.startswith('joint_') and name[6:].isdigit():
                idx = int(name[6:]) - 1
                if 0 <= idx < 6:
                    pos[idx] = math.degrees(msg.position[i]) if i < len(msg.position) else 0.0
                    vel[idx] = math.degrees(msg.velocity[i]) if i < len(msg.velocity) else 0.0
                    eff[idx] = (msg.effort[i]
                                if i < len(msg.effort) and not math.isnan(msg.effort[i])
                                else 0.0)
        with _lock:
            robot_state["joint_positions"]  = pos
            robot_state["joint_velocities"] = vel
            robot_state["joint_efforts"]    = eff
            robot_state["last_update"]      = time.time()
            robot_state["connection"]       = "connected"

    def _cb_error(self, msg):
        entry = {
            "time":  datetime.now().strftime("%H:%M:%S"),
            "level": {1: "INFO", 2: "WARN", 3: "ERROR"}.get(msg.level, "UNK"),
            "code":  msg.code,
            "msg":   " ".join(filter(None, [msg.msg1, msg.msg2, msg.msg3])),
        }
        with _lock:
            robot_state["errors"] = ([entry] + robot_state["errors"])[:20]

    def _cb_disconn(self, _msg):
        with _lock:
            robot_state["connection"] = "disconnected"

    def _cb_io(self, msg):
        with _lock:
            robot_state["digital_io"] = (list(msg.data) + [0]*16)[:16]

    def _poll(self):
        self._fire(self._posx_cli,  GetCurrentPosx.Request(),    self._done_posx, ref=0)
        self._fire(self._mode_cli,  GetRobotMode.Request(),      self._done_mode)
        self._fire(self._state_cli, GetRobotState.Request(),     self._done_state)
        self._fire(self._speed_cli, GetRobotSpeedMode.Request(), self._done_speed)
        self._fire(self._alarm_cli, GetLastAlarm.Request(),      self._done_alarm)

    def _fire(self, client, req, cb, **kwargs):
        if not client.service_is_ready():
            return
        for k, v in kwargs.items():
            setattr(req, k, v)
        client.call_async(req).add_done_callback(cb)

    def _done_posx(self, f):
        try:
            res = f.result()
            if res.success and res.task_pos_info:
                with _lock:
                    robot_state["current_posx"] = (list(res.task_pos_info[0].data) + [0.0]*6)[:6]
        except Exception:
            pass

    def _done_mode(self, f):
        try:
            res = f.result()
            if res.success:
                with _lock:
                    robot_state["robot_mode"] = int(res.robot_mode)
        except Exception:
            pass

    def _done_state(self, f):
        try:
            res = f.result()
            if res.success:
                with _lock:
                    robot_state["robot_state_value"] = int(res.robot_state)
        except Exception:
            pass

    def _done_speed(self, f):
        try:
            res = f.result()
            if res.success:
                with _lock:
                    robot_state["speed_mode"] = int(res.speed_mode)
        except Exception:
            pass

    def _done_alarm(self, f):
        try:
            res = f.result()
            if res.success and res.log_alarm:
                a = res.log_alarm
                with _lock:
                    robot_state["last_alarm"] = {
                        "level": a.level, "group": a.group,
                        "index": a.index, "param": list(a.param),
                    }
        except Exception:
            pass


# ── HTTP 핸들러 ───────────────────────────────────────────────────
async def handle_index(request):
    return web.Response(text=_HTML, content_type="text/html", charset="utf-8")


async def handle_admin(request):
    if os.path.isfile(_ADMIN_HTML):
        return web.FileResponse(_ADMIN_HTML, headers={"Access-Control-Allow-Origin": "*"})
    return web.Response(status=404, text="admin_index.html not found")


async def handle_sse(request):
    """Server-Sent Events: 0.2초마다 로봇 상태 JSON push"""
    resp = web.StreamResponse(headers={
        "Content-Type":                "text/event-stream",
        "Cache-Control":               "no-cache",
        "Connection":                  "keep-alive",
        "X-Accel-Buffering":           "no",
        "Access-Control-Allow-Origin": "*",
    })
    await resp.prepare(request)
    try:
        while True:
            with _lock:
                payload = json.dumps(robot_state)
            await resp.write(f"data: {payload}\n\n".encode())
            await asyncio.sleep(0.2)
    except (ConnectionResetError, asyncio.CancelledError, Exception):
        pass
    return resp


async def handle_state(request):
    with _lock:
        data = dict(robot_state)
    return web.Response(text=json.dumps(data, indent=2), content_type="application/json")


async def handle_urdf(request):
    if os.path.isfile(_URDF_FILE):
        return web.FileResponse(_URDF_FILE, headers={"Access-Control-Allow-Origin": "*"})
    return web.Response(status=404, text="URDF not found")


async def handle_video_feed(request):
    """MJPEG 스트림 – 브라우저 <img src="/video_feed"> 로 직접 사용"""
    if not _CV2_OK or _camera is None:
        return web.Response(status=503, text="카메라 없음 (--camera 옵션 확인)")

    resp = web.StreamResponse()
    resp.content_type = "multipart/x-mixed-replace; boundary=frame"
    await resp.prepare(request)

    interval = 1.0 / max(_cam_fps, 1)
    try:
        while True:
            frame = _camera.get_frame()
            if frame is None:
                await asyncio.sleep(0.05)
                continue
            ok, buf = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), _cam_quality]
            )
            if not ok:
                await asyncio.sleep(interval)
                continue
            jpeg  = buf.tobytes()
            chunk = (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                b"\r\n" + jpeg + b"\r\n"
            )
            await resp.write(chunk)
            await asyncio.sleep(interval)
    except (asyncio.CancelledError, ConnectionResetError, Exception):
        pass
    return resp


async def handle_snapshot(request):
    """단일 JPEG 스냅샷"""
    if not _CV2_OK or _camera is None:
        return web.Response(status=503, text="카메라 없음")
    frame = _camera.get_frame()
    if frame is None:
        return web.Response(status=503, text="프레임 없음")
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), _cam_quality])
    if not ok:
        return web.Response(status=500, text="인코딩 실패")
    return web.Response(body=buf.tobytes(), content_type="image/jpeg")


@web.middleware
async def cors_middleware(request, handler):
    try:
        resp = await handler(request)
        if resp is not None:
            resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except web.HTTPException as ex:
        if ex.headers is None:
            ex.headers = {}
        ex.headers["Access-Control-Allow-Origin"] = "*"
        raise


def make_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/",                    handle_index)
    app.router.add_get("/admin",               handle_admin)
    app.router.add_get("/admin_index.html",    handle_admin)
    app.router.add_get("/events",              handle_sse)
    app.router.add_get("/state",               handle_state)
    app.router.add_get("/urdf/m0609_rg2.urdf", handle_urdf)
    app.router.add_get("/video_feed",          handle_video_feed)
    app.router.add_get("/snapshot",            handle_snapshot)
    if os.path.isdir(_MESH_DIR):
        app.router.add_static("/urdf/meshes",               _MESH_DIR)
        app.router.add_static("/m0609_rg2_combined/meshes", _MESH_DIR)
    return app


# ── 임베딩 대시보드 HTML ──────────────────────────────────────────
_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>도련님 도시락 - 관리자 대시보드</title>
<style>
:root{--bg:#09091a;--panel:#10102a;--border:#1e1e40;--green:#00e87a;--amber:#ffb300;--red:#ff3355;--blue:#4499ff;--text:#c8d0e8;--muted:#5a6080}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Consolas',monospace;min-height:100vh}
header{background:var(--panel);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;gap:20px}
header h1{font-size:1.15rem;color:var(--green);letter-spacing:3px;white-space:nowrap}
nav{margin-left:auto;display:flex;gap:8px}
nav a{padding:4px 14px;border-radius:20px;font-size:.78rem;border:1px solid var(--border);color:var(--muted);text-decoration:none;transition:all .2s}
nav a:hover{border-color:var(--green);color:var(--green)}
#conn-badge{padding:3px 14px;border-radius:20px;font-size:.78rem;background:#002a18;color:var(--green);border:1px solid var(--green);transition:all .3s}
#conn-badge.disc{background:#2a0010;color:var(--red);border-color:var(--red)}
#upd{color:var(--muted);font-size:.78rem;white-space:nowrap}
main{padding:16px;display:grid;gap:14px;grid-template-columns:220px 1fr;grid-template-rows:420px auto auto auto auto}
#viewer3d{grid-column:1/-1;grid-row:1;position:relative;overflow:hidden;border-radius:8px;background:#0a0a1a;border:1px solid var(--border)}
#viewer3d canvas{width:100%!important;height:100%!important;display:block}
#viewer3d .v-label{position:absolute;top:10px;left:14px;font-size:.7rem;color:var(--muted);letter-spacing:2px;text-transform:uppercase;pointer-events:none;z-index:1}
#viewer3d .v-status{position:absolute;bottom:10px;right:14px;font-size:.7rem;color:var(--green);z-index:1}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px}
.panel h2{font-size:.7rem;color:var(--muted);letter-spacing:2px;text-transform:uppercase;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)}
#status{grid-column:1;grid-row:2/4}
.srow{margin-bottom:12px}
.slabel{font-size:.68rem;color:var(--muted);margin-bottom:3px}
.sval{font-size:.95rem;font-weight:bold}
.g{color:var(--green)}.a{color:var(--amber)}.r{color:var(--red)}.b{color:var(--blue)}.m{color:var(--muted)}
#joints{grid-column:2;grid-row:2}
.jgrid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
.jcard{text-align:center}
.jcard svg{width:100%;max-width:90px}
.jname{font-size:.68rem;color:var(--muted);margin-bottom:3px}
.jdeg{font-size:.88rem;color:var(--green);font-weight:bold;margin-top:3px}
.jv{font-size:.68rem;color:var(--amber)}
#vel{grid-column:2;grid-row:3}
.vrow{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.vname{font-size:.7rem;color:var(--muted);width:22px;flex-shrink:0}
.vbg{flex:1;height:7px;background:#15152e;border-radius:4px;overflow:hidden}
.vbar{height:100%;border-radius:4px;background:var(--amber);transition:width .2s;min-width:2px}
.vval{font-size:.7rem;color:var(--amber);width:58px;text-align:right;flex-shrink:0}
#cart{grid-column:1;grid-row:4}
.cgrid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.citem{background:#0c0c20;border:1px solid var(--border);border-radius:4px;padding:7px 10px}
.clabel{font-size:.68rem;color:var(--muted)}
.cval{font-size:1rem;color:var(--blue);font-weight:bold}
.cunit{font-size:.6rem;color:var(--muted)}
#bottom{grid-column:2;grid-row:4;display:grid;grid-template-columns:1fr 260px;gap:14px}
.elist{max-height:160px;overflow-y:auto;font-size:.75rem}
.elist::-webkit-scrollbar{width:4px}
.elist::-webkit-scrollbar-thumb{background:var(--border)}
.erow{padding:4px 8px;margin-bottom:3px;border-radius:4px;border-left:3px solid}
.eINFO{border-color:var(--blue);background:#0a0a22}
.eWARN{border-color:var(--amber);background:#1a1400}
.eERROR{border-color:var(--red);background:#1a0010}
.etime{color:var(--muted);margin-right:6px}
.ecode{color:var(--amber);margin-right:5px}
.noerr{color:var(--muted);padding:8px;font-size:.78rem}
.iogrid{display:grid;grid-template-columns:repeat(8,1fr);gap:5px}
.ioled{aspect-ratio:1;border-radius:50%;background:#13132a;border:1px solid #2a2a4a;display:flex;align-items:center;justify-content:center;font-size:.58rem;color:var(--muted);transition:all .2s}
.ioled.on{background:radial-gradient(circle,#00e87a 0%,#00a055 60%,#002a18 100%);border-color:var(--green);box-shadow:0 0 7px var(--green);color:#fff}
#alarm-box{font-size:.78rem;color:var(--amber);margin-top:4px;word-break:break-all;line-height:1.5}
#cam{grid-column:1/-1;grid-row:5}
.cam-wrap{display:flex;gap:16px;align-items:flex-start}
.cam-feed-box{flex:1;position:relative;min-height:120px;background:#0a0a1a;border-radius:6px;border:1px solid var(--border);overflow:hidden}
#cam-img{width:100%;display:block;border-radius:6px}
#cam-no{display:none;padding:48px;text-align:center;color:var(--muted);font-size:.9rem;line-height:2}
.cam-info{min-width:180px;flex-shrink:0}
.cam-info .srow:last-child{margin-bottom:0}
.cam-badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:.72rem;border:1px solid var(--border);color:var(--muted)}
.cam-badge.on{border-color:var(--green);color:var(--green);background:#002a18}
.cam-badge.off{border-color:var(--red);color:var(--red);background:#2a0010}
@media(max-width:1000px){
  main{grid-template-columns:1fr;grid-template-rows:350px auto auto auto auto auto auto}
  #viewer3d{grid-row:1}#status{grid-row:2}#joints{grid-column:1;grid-row:3}#vel{grid-column:1;grid-row:4}
  #cart{grid-row:5}#bottom{grid-column:1;grid-row:6;grid-template-columns:1fr}#cam{grid-row:7}
  .cam-wrap{flex-direction:column}.cam-info{min-width:unset;width:100%}
}
</style>
</head>
<body>
<header>
  <h1>&#9881; 도련님 도시락 관리자</h1>
  <span id="conn-badge">● 연결중...</span>
  <span id="upd">업데이트 대기중</span>
  <nav>
    <a href="/admin" target="_blank">주문 관리</a>
    <a href="/state" target="_blank">JSON</a>
    <a href="/snapshot" target="_blank">스냅샷</a>
  </nav>
</header>
<script type="importmap">
{"imports":{
  "three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
  "three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/",
  "three/examples/jsm/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
}}
</script>
<main>
  <!-- Row 1: 3D URDF 뷰어 -->
  <div id="viewer3d">
    <div class="v-label">&#9654; 3D URDF VIEWER</div>
    <div class="v-status" id="v-status">loading...</div>
  </div>

  <!-- Row 2-3 col 1: 로봇 상태 -->
  <div class="panel" id="status">
    <h2>로봇 상태</h2>
    <div class="srow"><div class="slabel">운영 모드</div><div class="sval" id="s-mode"><span class="m">-</span></div></div>
    <div class="srow"><div class="slabel">로봇 상태</div><div class="sval" id="s-state"><span class="m">-</span></div></div>
    <div class="srow"><div class="slabel">속도 모드</div><div class="sval" id="s-speed"><span class="m">-</span></div></div>
    <div class="srow" style="margin-top:16px"><div class="slabel">최근 알람</div><div id="alarm-box">없음</div></div>
  </div>

  <!-- Row 2 col 2: 관절 위치 -->
  <div class="panel" id="joints">
    <h2>관절 위치 (&#xb0;)</h2>
    <div class="jgrid" id="jgrid"></div>
  </div>

  <!-- Row 3 col 2: 관절 속도 -->
  <div class="panel" id="vel">
    <h2>관절 속도 (&#xb0;/s)</h2>
    <div id="vrows"></div>
  </div>

  <!-- Row 4 col 1: 작업공간 위치 -->
  <div class="panel" id="cart">
    <h2>작업 공간 위치</h2>
    <div class="cgrid">
      <div class="citem"><div class="clabel">X</div><div class="cval" id="cx">0.00</div><div class="cunit">mm</div></div>
      <div class="citem"><div class="clabel">Y</div><div class="cval" id="cy">0.00</div><div class="cunit">mm</div></div>
      <div class="citem"><div class="clabel">Z</div><div class="cval" id="cz">0.00</div><div class="cunit">mm</div></div>
      <div class="citem"><div class="clabel">RX</div><div class="cval" id="crx">0.00</div><div class="cunit">deg</div></div>
      <div class="citem"><div class="clabel">RY</div><div class="cval" id="cry">0.00</div><div class="cunit">deg</div></div>
      <div class="citem"><div class="clabel">RZ</div><div class="cval" id="crz">0.00</div><div class="cunit">deg</div></div>
    </div>
  </div>

  <!-- Row 4 col 2: 에러 로그 + 디지털 I/O + 토크 -->
  <div id="bottom">
    <div style="display:grid;grid-template-rows:1fr auto;gap:14px">
      <div class="panel">
        <h2>에러 로그</h2>
        <div class="elist" id="elist"><div class="noerr">에러 없음</div></div>
      </div>
      <div class="panel">
        <h2>디지털 입력 (컨트롤박스)</h2>
        <div class="iogrid" id="iogrid"></div>
      </div>
    </div>
    <div class="panel" style="align-self:start">
      <h2>관절 토크 / 부하</h2>
      <div id="trows"></div>
    </div>
  </div>

  <!-- Row 5: CCTV 카메라 -->
  <div class="panel" id="cam">
    <h2>&#128247; CCTV 라이브 카메라</h2>
    <div class="cam-wrap">
      <div class="cam-feed-box">
        <img id="cam-img" src="/video_feed" alt="카메라 스트림">
        <div id="cam-no">
          &#128247; 카메라 연결 없음<br>
          <span style="font-size:.75rem;color:var(--muted)">서버 실행 시 --camera 옵션을 확인하세요</span>
        </div>
      </div>
      <div class="panel cam-info">
        <h2>카메라 정보</h2>
        <div class="srow">
          <div class="slabel">상태</div>
          <div><span id="cam-badge" class="cam-badge">확인중...</span></div>
        </div>
        <div class="srow">
          <div class="slabel">라이브 스트림</div>
          <div style="font-size:.78rem;color:var(--blue)">/video_feed</div>
        </div>
        <div class="srow">
          <div class="slabel">스냅샷</div>
          <a href="/snapshot" target="_blank" style="font-size:.78rem;color:var(--amber)">/snapshot &#8599;</a>
        </div>
      </div>
    </div>
  </div>
</main>

<script>
var JN=['J1','J2','J3','J4','J5','J6'];
var JLIM=[360,160,160,360,270,360];
var MNAMES={0:'수동(Manual)',1:'자동(Auto)',2:'측정(Measure)'};
var STNAMES={0:'초기화',1:'대기',2:'이동중',3:'안전OFF',4:'교시',5:'안전정지',6:'비상정지',7:'홈이동',8:'복구',9:'안전정지2',10:'안전OFF2',15:'준비안됨'};
var SPNAMES={0:'일반(Normal)',1:'감속(Reduced)'};

// ── 카메라 자동 재연결 ────────────────────────────────────────────
var _camRetryTimer=null,_camOnline=false;
function _camSetOnline(){
  _camOnline=true;
  if(_camRetryTimer){clearTimeout(_camRetryTimer);_camRetryTimer=null;}
  var img=document.getElementById('cam-img'),no=document.getElementById('cam-no'),b=document.getElementById('cam-badge');
  if(img){img.style.display='block';}
  if(no){no.style.display='none';}
  if(b){b.textContent='스트리밍 중';b.className='cam-badge on';}
}
function _camSetOffline(){
  if(_camOnline===false&&_camRetryTimer)return;
  _camOnline=false;
  var img=document.getElementById('cam-img'),no=document.getElementById('cam-no'),b=document.getElementById('cam-badge');
  if(img){img.style.display='none';}
  if(no){no.style.display='block';}
  if(b){b.textContent='오프라인 – 8초 후 재연결';b.className='cam-badge off';}
  if(!_camRetryTimer){_camRetryTimer=setTimeout(_camRetry,8000);}
}
function _camRetry(){
  _camRetryTimer=null;
  var img=document.getElementById('cam-img'),b=document.getElementById('cam-badge');
  if(b){b.textContent='재연결 중...';b.className='cam-badge';}
  if(img){
    img.onload=function(){_camSetOnline();};
    img.onerror=function(){_camSetOffline();};
    img.src='/video_feed?_t='+Date.now();
  }
}
function onCamError(){_camSetOffline();}
(function(){
  var img=document.getElementById('cam-img');
  if(img){img.onload=function(){_camSetOnline();};img.onerror=function(){_camSetOffline();};}
})();

// ── 관절 카드 생성 ────────────────────────────────────────────────
function makeSVG(i){
  return '<svg viewBox="0 0 100 62" xmlns="http://www.w3.org/2000/svg">'
    +'<path d="M10,57 A45,45 0 0,1 90,57" fill="none" stroke="#1e1e40" stroke-width="9" stroke-linecap="round"/>'
    +'<path id="arc'+i+'" d="M10,57 A45,45 0 0,1 90,57" fill="none" stroke="#00e87a" stroke-width="9" stroke-linecap="round"'
    +' stroke-dasharray="141.4" stroke-dashoffset="141.4" style="transition:stroke-dashoffset .2s,stroke .2s"/>'
    +'<text id="dtxt'+i+'" x="50" y="54" text-anchor="middle" fill="#c8d0e8" font-size="12" font-weight="bold">0</text>'
    +'</svg>';
}
var jgrid=document.getElementById('jgrid');
for(var i=0;i<6;i++){
  var d=document.createElement('div');
  d.className='jcard';
  d.innerHTML='<div class="jname">'+JN[i]+'</div>'+makeSVG(i)
    +'<div class="jdeg" id="jd'+i+'">0.00°</div>'
    +'<div class="jv" id="jv'+i+'">0.00°/s</div>';
  jgrid.appendChild(d);
}
var vrows=document.getElementById('vrows');
var trows=document.getElementById('trows');
for(var i=0;i<6;i++){
  var vr=document.createElement('div');vr.className='vrow';
  vr.innerHTML='<span class="vname">'+JN[i]+'</span>'
    +'<div class="vbg"><div class="vbar" id="vbar'+i+'" style="width:0%"></div></div>'
    +'<span class="vval" id="vval'+i+'">0.00°/s</span>';
  vrows.appendChild(vr);
  var tr=document.createElement('div');tr.className='vrow';
  tr.innerHTML='<span class="vname">'+JN[i]+'</span>'
    +'<div class="vbg"><div class="vbar" id="tbar'+i+'" style="width:0%;background:var(--blue)"></div></div>'
    +'<span class="vval" id="tval'+i+'" style="color:var(--blue)">0.00Nm</span>';
  trows.appendChild(tr);
}
var iogrid=document.getElementById('iogrid');
for(var i=0;i<16;i++){
  var l=document.createElement('div');
  l.className='ioled';l.id='io'+i;l.title='DI'+(i+1);l.textContent=i+1;
  iogrid.appendChild(l);
}

// ── 렌더링 함수 ───────────────────────────────────────────────────
function setGauge(i,deg,lim){
  var pct=Math.min(1,Math.abs(deg)/lim);
  var arc=document.getElementById('arc'+i);
  var txt=document.getElementById('dtxt'+i);
  if(!arc||!txt)return;
  arc.setAttribute('stroke-dashoffset',141.4*(1-pct));
  arc.setAttribute('stroke',pct>.85?'#ff3355':pct>.65?'#ffb300':'#00e87a');
  txt.textContent=deg.toFixed(1);
}
function setStat(id,val,names,cls){
  var el=document.getElementById(id);if(!el)return;
  var text=val>=0?(names[val]!==undefined?names[val]:'?('+val+')')  :'-';
  var c=val>=0?(cls||'g'):'m';
  el.innerHTML='<span class="'+c+'">'+text+'</span>';
}
function stateClass(v){
  if(v===1)return 'g';if(v===2)return 'b';
  if(v===5||v===6||v===15)return 'r';return 'a';
}

function render(d){
  var badge=document.getElementById('conn-badge');
  if(d.connection==='connected'){badge.textContent='● 연결됨';badge.className='';}
  else{badge.textContent='● 연결 끊김';badge.className='disc';}

  var age=d.last_update?((Date.now()/1000-d.last_update).toFixed(1)):'?';
  document.getElementById('upd').textContent='업데이트 '+age+'s 전';

  setStat('s-mode', d.robot_mode,        MNAMES,null);
  setStat('s-state',d.robot_state_value, STNAMES,stateClass(d.robot_state_value));
  setStat('s-speed',d.speed_mode,        SPNAMES,d.speed_mode===1?'a':null);

  var ab=document.getElementById('alarm-box');
  if(d.last_alarm){
    var p=(d.last_alarm.param||[]).filter(Boolean).join(' ');
    ab.textContent='Lv'+d.last_alarm.level+' Grp'+d.last_alarm.group+' #'+d.last_alarm.index+(p?' | '+p:'');
  }

  var pos=d.joint_positions||[];
  var vel=d.joint_velocities||[];
  var eff=d.joint_efforts||[];
  for(var i=0;i<6;i++){
    var p=pos[i]||0,v=vel[i]||0,e=eff[i]||0;
    setGauge(i,p,JLIM[i]||360);
    var jd=document.getElementById('jd'+i);if(jd)jd.textContent=p.toFixed(2)+'°';
    var jv=document.getElementById('jv'+i);if(jv)jv.textContent=v.toFixed(2)+'°/s';
    var vpct=Math.min(100,Math.abs(v)/180*100);
    var vbar=document.getElementById('vbar'+i);if(vbar)vbar.style.width=vpct+'%';
    var vval=document.getElementById('vval'+i);if(vval)vval.textContent=v.toFixed(2)+'°/s';
    var tpct=Math.min(100,Math.abs(e)/50*100);
    var tbar=document.getElementById('tbar'+i);if(tbar)tbar.style.width=tpct+'%';
    var tval=document.getElementById('tval'+i);if(tval)tval.textContent=e.toFixed(2)+'Nm';
  }

  var px=d.current_posx||[];
  var ids=['cx','cy','cz','crx','cry','crz'];
  for(var i=0;i<6;i++){var el=document.getElementById(ids[i]);if(el)el.textContent=(px[i]||0).toFixed(2);}

  var elist=document.getElementById('elist');
  if(d.errors&&d.errors.length){
    var html='';
    for(var i=0;i<d.errors.length;i++){
      var er=d.errors[i];
      html+='<div class="erow e'+er.level+'">'
        +'<span class="etime">'+er.time+'</span>'
        +'<span class="ecode">['+er.level+':'+er.code+']</span>'
        +er.msg+'</div>';
    }
    elist.innerHTML=html;
  }else{elist.innerHTML='<div class="noerr">에러 없음</div>';}

  var io=d.digital_io||[];
  for(var i=0;i<16;i++){
    var l=document.getElementById('io'+i);
    if(l){if(io[i])l.classList.add('on');else l.classList.remove('on');}
  }
}

// ── SSE 연결 ─────────────────────────────────────────────────────
var es,_reconnTimer=null;
function connectSSE(){
  if(es){try{es.close();}catch(e){}}
  es=new EventSource('/events');
  es.onopen=function(){if(_reconnTimer){clearTimeout(_reconnTimer);_reconnTimer=null;}};
  es.onmessage=function(e){
    try{
      var d=JSON.parse(e.data);
      render(d);
      if(window._urdfUpdateJoints)window._urdfUpdateJoints(d.joint_positions||[]);
    }catch(ex){console.error('parse error',ex);}
  };
  es.onerror=function(){
    var badge=document.getElementById('conn-badge');
    badge.textContent='● 재연결중...';badge.className='disc';
    if(!_reconnTimer){_reconnTimer=setTimeout(function(){_reconnTimer=null;connectSSE();},3000);}
  };
}
connectSSE();
</script>

<!-- 3D URDF 뷰어 -->
<script type="module">
import*as THREE from'three';
import{OrbitControls}from'three/addons/controls/OrbitControls.js';
import{ColladaLoader}from'three/addons/loaders/ColladaLoader.js';
import{STLLoader}from'three/addons/loaders/STLLoader.js';
import URDFLoader from'https://cdn.jsdelivr.net/npm/urdf-loader@0.12.2/src/URDFLoader.js';

const box=document.getElementById('viewer3d');
const scene=new THREE.Scene();
scene.background=new THREE.Color(0x0a0a1a);
const camera=new THREE.PerspectiveCamera(50,box.clientWidth/box.clientHeight,0.01,100);
camera.position.set(1.2,1.0,1.2);
const renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(box.clientWidth,box.clientHeight);
renderer.outputColorSpace=THREE.SRGBColorSpace;
box.appendChild(renderer.domElement);

const controls=new OrbitControls(camera,renderer.domElement);
controls.target.set(0,0.35,0);controls.update();
controls.enableDamping=true;controls.dampingFactor=0.08;

scene.add(new THREE.AmbientLight(0xffffff,0.6));
const dl=new THREE.DirectionalLight(0xffffff,0.9);dl.position.set(3,5,3);scene.add(dl);
const dl2=new THREE.DirectionalLight(0x4499ff,0.3);dl2.position.set(-2,3,-2);scene.add(dl2);
scene.add(new THREE.GridHelper(2,20,0x1e1e40,0x1e1e40));

const loader=new URDFLoader();
loader.loadMeshCb=function(path,manager,onComplete){
  const ext=path.split('.').pop().toLowerCase();
  if(ext==='dae'){new ColladaLoader(manager).load(path,r=>onComplete(r.scene));}
  else if(ext==='stl'){new STLLoader(manager).load(path,geo=>onComplete(new THREE.Mesh(geo,new THREE.MeshPhongMaterial({color:0x888888}))));}
  else{onComplete(new THREE.Object3D());}
};

let robot=null;
loader.load('/urdf/m0609_rg2.urdf',r=>{
  robot=r;robot.rotation.x=-Math.PI/2;scene.add(robot);
  document.getElementById('v-status').textContent='loaded \u2714';
});

const DEG2RAD=Math.PI/180;
window._urdfUpdateJoints=function(pos){
  if(!robot||!pos||pos.length<6)return;
  for(let i=0;i<6;i++){const jn='joint_'+(i+1);if(robot.joints[jn])robot.joints[jn].setJointValue(pos[i]*DEG2RAD);}
};

function animate(){requestAnimationFrame(animate);controls.update();renderer.render(scene,camera);}
animate();

function onResize(){if(box.clientWidth>0&&box.clientHeight>0){camera.aspect=box.clientWidth/box.clientHeight;camera.updateProjectionMatrix();renderer.setSize(box.clientWidth,box.clientHeight);}}
window.addEventListener('resize',onResize);
new ResizeObserver(onResize).observe(box);
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────
def main(args=None):
    global _camera, _cam_fps, _cam_quality

    parser = argparse.ArgumentParser(description="도련님 도시락 통합 관리자 웹 서버")
    parser.add_argument("--camera",  type=int, default=-1,   help="USB 카메라 인덱스 (-1: 카메라 없음)")
    parser.add_argument("--width",   type=int, default=1280, help="카메라 가로 해상도")
    parser.add_argument("--height",  type=int, default=720,  help="카메라 세로 해상도")
    parser.add_argument("--fps",     type=int, default=20,   help="목표 FPS")
    parser.add_argument("--quality", type=int, default=70,   help="JPEG 품질 1~100")
    parser.add_argument("--port",    type=int, default=8080, help="HTTP 포트")
    cli = parser.parse_args()

    _cam_fps     = cli.fps
    _cam_quality = cli.quality

    # 카메라 초기화 (옵션)
    if cli.camera >= 0 and _CV2_OK:
        try:
            _camera = CameraCapture(cli.camera, cli.width, cli.height)
        except RuntimeError as e:
            print(f"[Camera] 경고: {e} — 카메라 없이 계속합니다.")
    elif cli.camera >= 0 and not _CV2_OK:
        print("[Camera] 경고: opencv-python 미설치 — 카메라 기능 비활성화")

    # ROS2 초기화
    rclpy.init(args=args)
    node = RobotDashboardNode()
    threading.Thread(
        target=lambda: rclpy.spin(node), daemon=True, name="ros_spin"
    ).start()

    # aiohttp 서버
    async def run():
        app = make_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", cli.port)
        await site.start()
        print("=" * 60)
        print("  도련님 도시락 - 통합 관리자 웹 서버")
        print(f"  대시보드   : http://localhost:{cli.port}/")
        print(f"  주문 관리  : http://localhost:{cli.port}/admin")
        print(f"  상태 JSON  : http://localhost:{cli.port}/state")
        if _camera is not None:
            print(f"  카메라     : http://localhost:{cli.port}/video_feed")
            print(f"  스냅샷     : http://localhost:{cli.port}/snapshot")
        print("=" * 60)
        try:
            await asyncio.sleep(float("inf"))
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await runner.cleanup()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        pass
    finally:
        if _camera:
            _camera.release()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
