"""Agent 实例的生命周期状态机。

管理状态转换：CREATED → RUNNING ↔ PAUSED → DRAINING → STOPPED → DELETED。
强制执行合法的转换规则并提供转换钩子。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from src.utils.exceptions import AgentStateError
from src.utils.logging import get_logger

logger = get_logger("agent.lifecycle")


class InstanceState(str, Enum):
    """Agent 实例的生命周期状态。"""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    DRAINING = "draining"
    STOPPED = "stopped"
    DELETED = "deleted"


class LifecycleEvent(str, Enum):
    """触发状态转换的事件。"""

    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    DRAIN = "drain"
    STOP = "stop"
    DELETE = "delete"


# 合法的状态转换：{当前状态: {事件: 新状态}}
TRANSITION_TABLE: dict[InstanceState, dict[LifecycleEvent, InstanceState]] = {
    InstanceState.CREATED: {
        LifecycleEvent.START: InstanceState.RUNNING,
        LifecycleEvent.DELETE: InstanceState.DELETED,
    },
    InstanceState.RUNNING: {
        LifecycleEvent.PAUSE: InstanceState.PAUSED,
        LifecycleEvent.DRAIN: InstanceState.DRAINING,
        LifecycleEvent.STOP: InstanceState.STOPPED,
    },
    InstanceState.PAUSED: {
        LifecycleEvent.RESUME: InstanceState.RUNNING,
        LifecycleEvent.STOP: InstanceState.STOPPED,
        LifecycleEvent.DRAIN: InstanceState.DRAINING,
    },
    InstanceState.DRAINING: {
        LifecycleEvent.STOP: InstanceState.STOPPED,
    },
    InstanceState.STOPPED: {
        LifecycleEvent.START: InstanceState.RUNNING,
        LifecycleEvent.DELETE: InstanceState.DELETED,
    },
    InstanceState.DELETED: {},
}


class LifecycleStateMachine:
    """
    管理 Agent 实例的状态转换。

    强制执行合法的转换表，并提供转换前后的钩子支持。
    """

    def __init__(self, initial_state: InstanceState = InstanceState.CREATED) -> None:
        """初始化生命周期状态机。

        Args:
            initial_state: 实例的初始生命周期状态。
        """
        self._current_state: InstanceState = initial_state
        self._hooks: dict[str, list[Callable[[InstanceState, InstanceState], None]]] = {
            "before_transition": [],
            "after_transition": [],
        }

    @property
    def current_state(self) -> InstanceState:
        """返回当前状态。"""
        return self._current_state

    def can_transition(self, from_state: InstanceState, to_state: InstanceState) -> bool:
        """检查两个状态之间的转换是否合法。"""
        for new_state in TRANSITION_TABLE.get(from_state, {}).values():
            if new_state == to_state:
                return True
        return False

    def transition(self, event: LifecycleEvent) -> InstanceState:
        """
        尝试通过事件触发一次状态转换。

        Args:
            event: 要处理的生命周期事件。

        Returns:
            转换后的新状态。

        Raises:
            如果从当前状态出发该转换不合法，抛出 AgentStateError。
        """
        valid_transitions: Skill | None = TRANSITION_TABLE.get(self._current_state, {})
        new_state: Skill | None = valid_transitions.get(event)

        if new_state is None:
            raise AgentStateError(
                f"Invalid transition: {event.value} from state {self._current_state.value}"
            )

        # 执行前置钩子
        for hook in self._hooks["before_transition"]:
            hook(self._current_state, new_state)

        old_state: Any = self._current_state
        self._current_state = new_state

        logger.info(
            "State transition",
            old_state=old_state.value,
            new_state=new_state.value,
            transition_event=event.value,
        )

        # 执行后置钩子
        for hook in self._hooks["after_transition"]:
            hook(old_state, new_state)

        return new_state

    def add_hook(
        self,
        hook_type: str,
        callback: Callable[[InstanceState, InstanceState], None],
    ) -> None:
        """注册一个转换前或转换后的钩子。"""
        if hook_type not in self._hooks:
            raise ValueError(f"Invalid hook type: {hook_type}. Use 'before_transition' or 'after_transition'")
        self._hooks[hook_type].append(callback)

    def is_active(self) -> bool:
        """检查实例是否处于活跃状态（RUNNING 或 PAUSED）。"""
        return self._current_state in (InstanceState.RUNNING, InstanceState.PAUSED)

    def is_accepting_sessions(self) -> bool:
        """检查实例是否可以接受新会话。"""
        return self._current_state == InstanceState.RUNNING
