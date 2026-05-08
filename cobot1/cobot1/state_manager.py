#!/usr/bin/env python3
"""
==============================================================================
[Phase 1] 나만의 도련님 도시락 - 중앙 상태 관리자
==============================================================================
모든 전역 상태를 단일 클래스로 통합.
스레드 안전한 읽기/쓰기, 비상정지 이벤트, 중복주문 방지를 제공.
==============================================================================
"""

import copy
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from rclpy.logging import get_logger

_logger = get_logger('state_manager')

class RobotState(Enum):
    IDLE           = "idle"
    MOVING         = "moving"
    PROCESSING     = "processing"
    ERROR          = "error"
    EMERGENCY_STOP = "emergency_stop"

class GripperWidth(Enum):
    MM5   = "5mm"
    MM20  = "20mm"
    MM30  = "30mm"
    MM50  = "50mm"
    MM100 = "100mm"

@dataclass
class StepLog:
    timestamp: float
    message:   str
    completed: bool

@dataclass
class RobotStatus:
    state:        RobotState  = RobotState.IDLE
    current_task: str         = "대기 중"
    gripper:      GripperWidth = GripperWidth.MM100
    joint_pos:    List[float] = field(default_factory=lambda: [0.0] * 6)
    progress:     int         = 0
    step_index:   int         = 0
    total_steps:  int         = 0
    current_step: str         = ""
    step_log:     List[StepLog] = field(default_factory=list)
    last_update:  float       = field(default_factory=time.time)
    collision_detected: bool  = False

class RobotStateManager:
    MAX_LOG = 20

    def __init__(self):
        self.status                = RobotStatus()
        self._lock                 = threading.RLock()
        self.emergency_stop        = threading.Event()
        self.processed_order_keys: set = set()
        
        # 🚨 [추가됨] 스테이지들이 일시정지 상태를 알 수 있도록 이벤트 추가
        self.pause_event           = threading.Event()
        self.pause_event.set()     # Set 상태가 정상 작동(Not Paused)을 의미

    def update_status(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.status, key):
                    setattr(self.status, key, value)
            self.status.last_update = time.time()

    def add_step_log(self, message: str, completed: bool = False):
        with self._lock:
            prefix = "✅" if completed else "🔄"
            entry  = StepLog(
                timestamp = time.time(),
                message   = f"{prefix} {message}",
                completed = completed,
            )
            logs = self.status.step_log
            logs.append(entry)
            if len(logs) > self.MAX_LOG:
                logs.pop(0)
        _logger.info(entry.message)

    def reset_progress(self, total: int):
        with self._lock:
            self.status.progress     = 0
            self.status.step_index   = 0
            self.status.total_steps  = total
            self.status.current_step = ""
            self.status.step_log     = []

    def tick(self, label: str = ""):
        with self._lock:
            self.status.step_index = min(
                self.status.step_index + 1, self.status.total_steps
            )
            total = max(self.status.total_steps, 1)
            pct   = min(int(self.status.step_index / total * 100), 99)
            self.status.progress     = pct
            self.status.current_step = label

    def get_status_dict(self) -> dict:
        with self._lock:
            s = self.status
            logs = [e.message for e in s.step_log]
            return {
                "state":        s.state.value,
                "current_task": s.current_task,
                "gripper":      s.gripper.value,
                "joint_pos":    list(s.joint_pos),
                "progress":     s.progress,
                "step_index":   s.step_index,
                "total_steps":  s.total_steps,
                "current_step": s.current_step,
                "step_log":     logs,
                "last_update":  s.last_update,
                "collision":    s.collision_detected,
            }

    def trigger_emergency_stop(self):
        self.emergency_stop.set()
        self.update_status(
            state        = RobotState.EMERGENCY_STOP,
            current_task = "⛔ 비상정지 - 웹에서 재개 버튼 필요",
        )

    def clear_emergency_stop(self):
        self.emergency_stop.clear()
        self.update_status(state=RobotState.IDLE, current_task="대기 중")

    def is_stopped(self) -> bool:
        return self.emergency_stop.is_set()

    # 🚨 [추가됨] 일시정지 제어 함수들
    def set_pause(self):
        self.pause_event.clear()

    def clear_pause(self):
        self.pause_event.set()

    def is_paused(self) -> bool:
        return not self.pause_event.is_set()

    def wait_if_paused(self):
        """일시정지 상태라면 풀릴 때까지 스레드를 블로킹(대기)시킴"""
        self.pause_event.wait()

    def mark_order_processed(self, order_key: str):
        with self._lock:
            self.processed_order_keys.add(order_key)

    def is_order_processed(self, order_key: str) -> bool:
        with self._lock:
            return order_key in self.processed_order_keys