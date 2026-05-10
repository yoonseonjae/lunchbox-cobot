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
        """RobotStatus 필드를 키워드 인수로 업데이트한다.

        Args:
            **kwargs: state, current_task, gripper, joint_pos, progress 등
                      RobotStatus 에 정의된 필드명 = 값.
        Returns:
            None
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.status, key):
                    setattr(self.status, key, value)
            self.status.last_update = time.time()

    def add_step_log(self, message: str, completed: bool = False):
        """step_log 리스트에 로그를 추가한다. MAX_LOG(20개) 초과 시 가장 오래된 항목을 제거한다.

        Args:
            message (str): 로그에 기록할 작업 설명문.
            completed (bool): True면 ✅ 접두어, False면 🔄 접두어.
        Returns:
            None
        """
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
        """progress, step_index, step_log를 초기화하고 total_steps를 설정한다. 새 주문 시작 시 호출.

        Args:
            total (int): 전체 작업 단계 수 (progress % 계산 기준).
        Returns:
            None
        """
        with self._lock:
            self.status.progress     = 0
            self.status.step_index   = 0
            self.status.total_steps  = total
            self.status.current_step = ""
            self.status.step_log     = []

    def tick(self, label: str = ""):
        """step_index를 1 증가하고 progress(%) 를 갱신한다. 최대 99%로 켜핑.

        Args:
            label (str): 현재 단계 설명문 (current_step에 반영).
        Returns:
            None
        """
        with self._lock:
            self.status.step_index = min(
                self.status.step_index + 1, self.status.total_steps
            )
            total = max(self.status.total_steps, 1)
            pct   = min(int(self.status.step_index / total * 100), 99)
            self.status.progress     = pct
            self.status.current_step = label

    def get_status_dict(self) -> dict:
        """Firebase 업로드 및 웹 전달에 사용할 로봇 상태 dict를 반환한다.

        Returns:
            dict: state, current_task, gripper, joint_pos, progress,
                  step_index, total_steps, current_step, step_log,
                  last_update, collision 등 11개 필드.
        """
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
        """emergency_stop 이벤트를 set하고 상태를 EMERGENCY_STOP으로 변경한다.

        Returns:
            None
        """
        self.emergency_stop.set()
        self.update_status(
            state        = RobotState.EMERGENCY_STOP,
            current_task = "⛔ 비상정지 - 웹에서 재개 버튼 필요",
        )

    def clear_emergency_stop(self):
        """emergency_stop 이벤트를 clear하고 상태를 IDLE로 복원한다.

        Returns:
            None
        """
        self.emergency_stop.clear()
        self.update_status(state=RobotState.IDLE, current_task="대기 중")

    def is_stopped(self) -> bool:
        """emergency_stop 이벤트가 set 상태(충돌/강제정지 중)인지 로반한다.

        Returns:
            bool: 비상정지 중이면 True.
        """
        return self.emergency_stop.is_set()

    # 🚨 [추가됨] 일시정지 제어 함수들
    def set_pause(self):
        """pause_event를 clear하여 일시정지 상태로 진입한다.

        Returns:
            None  (wait_if_paused()를 호출 중인 스레드가 여기서 블로킹됨)
        """
        self.pause_event.clear()

    def clear_pause(self):
        """pause_event를 set하여 일시정지를 해제하고 대기 중인 스레드를 재개한다.

        Returns:
            None
        """
        self.pause_event.set()

    def is_paused(self) -> bool:
        """pause_event가 clear 상태(일시정지 중)인지 반환한다.

        Returns:
            bool: 일시정지 중이면 True.
        """
        return not self.pause_event.is_set()

    def wait_if_paused(self):
        """일시정지 상태라면 풀릴 때까지 스레드를 블로킹(대기)시킴"""
        self.pause_event.wait()

    def mark_order_processed(self, order_key: str):
        """order_key를 처리 완료 세트에 등록해 중복 수신을 막는다.

        Args:
            order_key (str): 등록할 주문 key.
        Returns:
            None
        """
        with self._lock:
            self.processed_order_keys.add(order_key)

    def is_order_processed(self, order_key: str) -> bool:
        """order_key가 이미 처리된 적 있는지 확인한다.

        Args:
            order_key (str): 확인할 주문 key.
        Returns:
            bool: 이미 처리된 key면 True.
        """
        with self._lock:
            return order_key in self.processed_order_keys