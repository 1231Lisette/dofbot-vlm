from __future__ import annotations

import time
from typing import Any, ClassVar


class GestureController:
    """Debounce browser gesture classifications before they become robot actions."""

    ACTIONS: ClassVar[dict[str, str]] = {
        "Open_Palm": "emergency_stop",
        "Thumb_Up": "execute_pending",
        "Victory": "home",
    }
    LABELS: ClassVar[dict[str, str]] = {
        "Open_Palm": "张开手掌",
        "Thumb_Up": "点赞",
        "Victory": "V 手势",
    }

    def __init__(
        self,
        *,
        confidence_threshold: float = 0.70,
        regular_frames: int = 6,
        emergency_frames: int = 3,
        cooldown_ms: float = 1500.0,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.regular_frames = regular_frames
        self.emergency_frames = emergency_frames
        self.cooldown_ms = cooldown_ms
        self.reset()

    def reset(self) -> None:
        self.current_gesture: str | None = None
        self.confidence = 0.0
        self.streak = 0
        self.source = "idle"
        self.latched_gesture: str | None = None
        self.last_trigger_ms = -self.cooldown_ms
        self.last_action: str | None = None
        self.last_result = "等待手势输入"
        self.trigger_count = 0

    def feed(
        self,
        gesture: str | None,
        confidence: float,
        *,
        timestamp_ms: float | None = None,
        source: str = "camera",
    ) -> dict[str, Any]:
        now_ms = timestamp_ms if timestamp_ms is not None else time.monotonic() * 1000
        recognized = gesture if gesture in self.ACTIONS else None
        if confidence < self.confidence_threshold:
            recognized = None

        self.source = source
        self.confidence = round(float(confidence), 4)
        if recognized is None:
            self.current_gesture = None
            self.streak = 0
            self.latched_gesture = None
            return {"triggered": None, "state": self.snapshot()}

        # A palm must always be able to pre-empt a previously latched ordinary gesture.
        if self.latched_gesture is not None:
            if recognized != "Open_Palm" or self.latched_gesture == "Open_Palm":
                self.current_gesture = recognized
                return {"triggered": None, "state": self.snapshot()}
            self.latched_gesture = None
            self.streak = 0

        if recognized == self.current_gesture:
            self.streak += 1
        else:
            self.current_gesture = recognized
            self.streak = 1

        required = self._required_frames(recognized)
        cooldown_ready = now_ms - self.last_trigger_ms >= self.cooldown_ms
        if self.streak < required or (recognized != "Open_Palm" and not cooldown_ready):
            return {"triggered": None, "state": self.snapshot()}

        action = self.ACTIONS[recognized]
        self.latched_gesture = recognized
        self.last_trigger_ms = now_ms
        self.last_action = action
        self.last_result = f"已识别{self.LABELS[recognized]}，正在分发动作"
        self.trigger_count += 1
        return {"triggered": action, "gesture": recognized, "state": self.snapshot()}

    def record_result(self, message: str) -> None:
        self.last_result = message

    def snapshot(self) -> dict[str, Any]:
        return {
            "allowed": list(self.ACTIONS),
            "current": self.current_gesture,
            "confidence": self.confidence,
            "streak": self.streak,
            "required_frames": self._required_frames(self.current_gesture),
            "latched": self.latched_gesture,
            "source": self.source,
            "last_action": self.last_action,
            "last_result": self.last_result,
            "trigger_count": self.trigger_count,
            "confidence_threshold": self.confidence_threshold,
        }

    def _required_frames(self, gesture: str | None) -> int:
        return self.emergency_frames if gesture == "Open_Palm" else self.regular_frames
