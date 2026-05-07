#!/usr/bin/env python3
import asyncio
import json
import os
import threading
import time
from datetime import datetime

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

# ── URDF / Mesh file paths ────────────────────────────────────────
_URDF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '..', '..', 'm0609_rg2_combined')
if not os.path.isdir(_URDF_DIR):
    _URDF_DIR = '/home/yoon/cobot_ws/src/m0609_rg2_combined'
_URDF_FILE = os.path.join(_URDF_DIR, 'm0609_rg2.urdf')
_MESH_DIR  = os.path.join(_URDF_DIR, 'meshes')

# ── Global state (thread-safe) ────────────────────────────────────
_lock = threading.Lock()
robot_state = {
    "connection": "connected",
    "joint_names": [f"J{i+1}" for i in range(6)],
    "joint_positions": [0.0] * 6,
    "joint_velocities": [0.0] * 6,
    "joint_efforts": [0.0] * 6,
    "current_posx": [0.0] * 6,
    "robot_mode": -1,
    "robot_state_value": -1,
    "speed_mode": -1,
    "last_alarm": None,
    "errors": [],
    "digital_io": [0] * 16,
    "last_update": 0.0,
}


# ── ROS2 Node ─────────────────────────────────────────────────────
class RobotDashboardNode(Node):
    def __init__(self):
        super().__init__("robot_dashboard", namespace="dsr01")

        self.create_subscription(
            JointState, "/dsr01/joint_states", self._cb_joints, 10)
        self.create_subscription(
            RobotError, "/dsr01/error", self._cb_error, 10)
        self.create_subscription(
            RobotDisconnection, "/dsr01/robot_disconnection", self._cb_disconn, 10)
        self.create_subscription(
            UInt8MultiArray, "/dsr01/io/ctrl_box_digital_input_state", self._cb_io, 10)

        self._posx_cli  = self.create_client(GetCurrentPosx,    "/dsr01/aux_control/get_current_posx")
        self._mode_cli  = self.create_client(GetRobotMode,      "/dsr01/system/get_robot_mode")
        self._state_cli = self.create_client(GetRobotState,     "/dsr01/system/get_robot_state")
        self._speed_cli = self.create_client(GetRobotSpeedMode, "/dsr01/system/get_robot_speed_mode")
        self._alarm_cli = self.create_client(GetLastAlarm,      "/dsr01/system/get_last_alarm")

        self.create_timer(2.0, self._poll)

    def _cb_joints(self, msg):
        import math
        # Map joint names like 'joint_1', 'joint_2' to index 0-5
        # Default arrays
        pos = [0.0] * 6
        vel = [0.0] * 6
        eff = [0.0] * 6
        for i, name in enumerate(msg.name):
            if name.startswith('joint_') and name[6:].isdigit():
                idx = int(name[6:]) - 1
                if 0 <= idx < 6:
                    # Convert radians to degrees for UI
                    pos[idx] = math.degrees(msg.position[i]) if i < len(msg.position) else 0.0
                    vel[idx] = math.degrees(msg.velocity[i]) if i < len(msg.velocity) else 0.0
                    eff[idx] = msg.effort[i] if i < len(msg.effort) and not math.isnan(msg.effort[i]) else 0.0
        
        with _lock:
            robot_state["joint_names"]      = [f"J{i+1}" for i in range(6)]
            robot_state["joint_positions"]  = pos
            robot_state["joint_velocities"] = vel
            robot_state["joint_efforts"]    = eff
            robot_state["last_update"]      = time.time()
            robot_state["connection"]       = "connected"

    def _cb_error(self, msg):
        levels = {1: "INFO", 2: "WARN", 3: "ERROR"}
        entry = {
            "time":  datetime.now().strftime("%H:%M:%S"),
            "level": levels.get(msg.level, "UNK"),
            "code":  msg.code,
            "msg":   " ".join(filter(None, [msg.msg1, msg.msg2, msg.msg3])),
        }
        with _lock:
            robot_state["errors"] = ([entry] + robot_state["errors"])[:20]

    def _cb_disconn(self, _msg):
        with _lock:
            robot_state["connection"] = "disconnected"

    def _cb_io(self, msg):
        data = (list(msg.data) + [0] * 16)[:16]
        with _lock:
            robot_state["digital_io"] = data

    def _poll(self):
        self._fire(self._posx_cli,  GetCurrentPosx.Request(),    self._done_posx,  ref=0)
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

    def _done_posx(self, future):
        try:
            res = future.result()
            if res.success and res.task_pos_info:
                data = res.task_pos_info[0].data
                with _lock:
                    robot_state["current_posx"] = (list(data) + [0.0] * 6)[:6]
        except Exception:
            pass

    def _done_mode(self, future):
        try:
            res = future.result()
            if res.success:
                with _lock:
                    robot_state["robot_mode"] = int(res.robot_mode)
        except Exception:
            pass

    def _done_state(self, future):
        try:
            res = future.result()
            if res.success:
                with _lock:
                    robot_state["robot_state_value"] = int(res.robot_state)
        except Exception:
            pass

    def _done_speed(self, future):
        try:
            res = future.result()
            if res.success:
                with _lock:
                    robot_state["speed_mode"] = int(res.speed_mode)
        except Exception:
            pass

    def _done_alarm(self, future):
        try:
            res = future.result()
            if res.success and res.log_alarm:
                a = res.log_alarm
                with _lock:
                    robot_state["last_alarm"] = {
                        "level": a.level, "group": a.group,
                        "index": a.index, "param": list(a.param),
                    }
        except Exception:
            pass


# ── HTTP / SSE handlers ───────────────────────────────────────────
async def handle_index(request):
    return web.Response(text=_HTML, content_type="text/html", charset="utf-8")


async def handle_sse(request):
    """Server-Sent Events: 브라우저로 0.2초마다 JSON push"""
    response = web.StreamResponse(headers={
        "Content-Type":                "text/event-stream",
        "Cache-Control":               "no-cache",
        "Connection":                  "keep-alive",
        "X-Accel-Buffering":           "no",
        "Access-Control-Allow-Origin": "*",
    })
    await response.prepare(request)
    try:
        while True:
            with _lock:
                payload = json.dumps(robot_state)
            await response.write(f"data: {payload}\n\n".encode())
            await asyncio.sleep(0.2)
    except (ConnectionResetError, asyncio.CancelledError, Exception):
        pass
    return response


async def handle_state(request):
    """단순 JSON GET – 브라우저 개발자도구로 데이터 직접 확인용"""
    with _lock:
        data = dict(robot_state)
    return web.Response(text=json.dumps(data, indent=2),
                        content_type="application/json")


async def handle_urdf(request):
    """URDF 파일 서빙"""
    if os.path.isfile(_URDF_FILE):
        return web.FileResponse(_URDF_FILE, headers={'Access-Control-Allow-Origin': '*'})
    return web.Response(status=404, text='URDF not found')


@web.middleware
async def cors_middleware(request, handler):
    try:
        response = await handler(request)
        if response is not None:
            response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except web.HTTPException as ex:
        if ex.headers is None:
            ex.headers = {}
        ex.headers['Access-Control-Allow-Origin'] = '*'
        raise

def make_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/",       handle_index)
    app.router.add_get("/events", handle_sse)
    app.router.add_get("/state",  handle_state)
    app.router.add_get("/urdf/m0609_rg2.urdf", handle_urdf)
    if os.path.isdir(_MESH_DIR):
        app.router.add_static("/urdf/meshes", _MESH_DIR)
        app.router.add_static("/m0609_rg2_combined/meshes", _MESH_DIR)
    return app


# ── Embedded Dashboard HTML ───────────────────────────────────────
_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>DSR M0609 대시보드</title>
<style>
:root{--bg:#09091a;--panel:#10102a;--border:#1e1e40;--green:#00e87a;--amber:#ffb300;--red:#ff3355;--blue:#4499ff;--text:#c8d0e8;--muted:#5a6080}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Consolas',monospace;min-height:100vh}
header{background:var(--panel);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;gap:20px}
header h1{font-size:1.15rem;color:var(--green);letter-spacing:3px;white-space:nowrap}
#conn-badge{padding:3px 14px;border-radius:20px;font-size:.78rem;background:#002a18;color:var(--green);border:1px solid var(--green);transition:all .3s}
#conn-badge.disc{background:#2a0010;color:var(--red);border-color:var(--red)}
#upd{margin-left:auto;color:var(--muted);font-size:.78rem;white-space:nowrap}
main{padding:16px;display:grid;gap:14px;grid-template-columns:220px 1fr;grid-template-rows:420px auto auto auto}
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
@media(max-width:1000px){
  main{grid-template-columns:1fr;grid-template-rows:350px auto auto auto auto auto}
  #viewer3d{grid-row:1}#status{grid-row:2}#joints{grid-column:1;grid-row:3}#vel{grid-column:1;grid-row:4}
  #cart{grid-row:5}#bottom{grid-column:1;grid-row:6;grid-template-columns:1fr}
}
</style>
</head>
<body>
<header>
  <h1>&#9881; DSR M0609 모니터링</h1>
  <span id="conn-badge">● 연결중...</span>
  <span id="upd">업데이트 대기중</span>
</header>
<script type="importmap">
{"imports":{
  "three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
  "three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/",
  "three/examples/jsm/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
}}
</script>
<main>
  <div id="viewer3d">
    <div class="v-label">&#9654; 3D URDF VIEWER</div>
    <div class="v-status" id="v-status">loading...</div>
  </div>
  <div class="panel" id="status">
    <h2>로봇 상태</h2>
    <div class="srow"><div class="slabel">운영 모드</div><div class="sval" id="s-mode"><span class="m">-</span></div></div>
    <div class="srow"><div class="slabel">로봇 상태</div><div class="sval" id="s-state"><span class="m">-</span></div></div>
    <div class="srow"><div class="slabel">속도 모드</div><div class="sval" id="s-speed"><span class="m">-</span></div></div>
    <div class="srow" style="margin-top:16px"><div class="slabel">최근 알람</div><div id="alarm-box">없음</div></div>
  </div>
  <div class="panel" id="joints">
    <h2>관절 위치 (&#xb0;)</h2>
    <div class="jgrid" id="jgrid"></div>
  </div>
  <div class="panel" id="vel">
    <h2>관절 속도 (&#xb0;/s)</h2>
    <div id="vrows"></div>
  </div>
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
</main>
<script>
var JN=['J1','J2','J3','J4','J5','J6'];
var JLIM=[360,160,160,360,270,360];
var MNAMES={0:'수동(Manual)',1:'자동(Auto)',2:'측정(Measure)'};
var STNAMES={0:'초기화',1:'대기',2:'이동중',3:'안전OFF',4:'교시',5:'안전정지',6:'비상정지',7:'홈이동',8:'복구',9:'안전정지2',10:'안전OFF2',15:'준비안됨'};
var SPNAMES={0:'일반(Normal)',1:'감속(Reduced)'};

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

  setStat('s-mode', d.robot_mode,        MNAMES, null);
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

// ── SSE 연결 (WebSocket 대신) ─────────────────────────────────────
var es;
function connectSSE(){
  es=new EventSource('/events');
  es.onopen=function(){
    console.log('SSE connected');
  };
  es.onmessage=function(e){
    try{
      var d=JSON.parse(e.data);
      render(d);
      if(window._urdfUpdateJoints) window._urdfUpdateJoints(d.joint_positions||[]);
    }catch(ex){console.error('parse error',ex);}
  };
  es.onerror=function(){
    var badge=document.getElementById('conn-badge');
    badge.textContent='● 재연결중...';badge.className='disc';
  };
}
connectSSE();
</script>
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
const dl=new THREE.DirectionalLight(0xffffff,0.9);
dl.position.set(3,5,3);scene.add(dl);
const dl2=new THREE.DirectionalLight(0x4499ff,0.3);
dl2.position.set(-2,3,-2);scene.add(dl2);

const grid=new THREE.GridHelper(2,20,0x1e1e40,0x1e1e40);
scene.add(grid);

const loader=new URDFLoader();
loader.loadMeshCb=function(path,manager,onComplete){
  const ext=path.split('.').pop().toLowerCase();
  if(ext==='dae'){
    new ColladaLoader(manager).load(path,function(r){onComplete(r.scene);});
  }else if(ext==='stl'){
    new STLLoader(manager).load(path,function(geo){
      const mat=new THREE.MeshPhongMaterial({color:0x888888});
      onComplete(new THREE.Mesh(geo,mat));
    });
  }else{onComplete(new THREE.Object3D());}
};

let robot=null;
loader.load('/urdf/m0609_rg2.urdf',function(r){
  robot=r;
  robot.rotation.x=-Math.PI/2;
  scene.add(robot);
  document.getElementById('v-status').textContent='loaded \u2714';
  console.log('URDF loaded, joints:',Object.keys(robot.joints));
});

const DEG2RAD=Math.PI/180;
window._urdfUpdateJoints=function(pos){
  if(!robot||!pos||pos.length<6)return;
  for(let i=0;i<6;i++){
    const jn='joint_'+(i+1);
    if(robot.joints[jn]) robot.joints[jn].setJointValue(pos[i]*DEG2RAD);
  }
};

function animate(){requestAnimationFrame(animate);controls.update();renderer.render(scene,camera);}
animate();

window.addEventListener('resize',function(){
  camera.aspect=box.clientWidth/box.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(box.clientWidth,box.clientHeight);
});
new ResizeObserver(function(){
  camera.aspect=box.clientWidth/box.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(box.clientWidth,box.clientHeight);
}).observe(box);
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────
def main(args=None):
    rclpy.init(args=args)
    node = RobotDashboardNode()

    ros_thread = threading.Thread(
        target=lambda: rclpy.spin(node), daemon=True, name="ros_spin")
    ros_thread.start()

    async def run():
        app = make_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 8080)
        await site.start()
        print("=" * 50)
        print("  DSR M0609 Web Dashboard")
        print("  http://localhost:8080")
        print("  http://localhost:8080/state  (JSON 직접 확인)")
        print("=" * 50)
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
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()