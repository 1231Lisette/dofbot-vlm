from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class TaskIntent:
    valid: bool
    action: str | None = None
    object_name: str | None = None
    target_name: str | None = None
    target_xy: tuple[float, float] | None = None
    confidence: float = 0.0
    summary: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuleBasedTaskParser:
    """Deterministic Chinese command parser with a strict action allow-list."""

    OBJECT_TERMS: ClassVar[dict[str, tuple[str, ...]]] = {
        "red_cube": ("红色", "红方块", "红色方块", "red"),
        "blue_cube": ("蓝色", "蓝方块", "蓝色方块", "blue"),
        "green_cube": ("绿色", "绿方块", "绿色方块", "green"),
    }
    OBJECT_LABELS: ClassVar[dict[str, str]] = {
        "red_cube": "红色方块",
        "blue_cube": "蓝色方块",
        "green_cube": "绿色方块",
    }
    TARGETS: ClassVar[dict[str, tuple[tuple[str, ...], tuple[float, float], str]]] = {
        "left_zone": (("左边", "左侧", "左区", "left"), (-0.45, 0.05), "左侧区域"),
        "center_zone": (
            ("中间", "中央", "中心", "目标区", "center"),
            (-0.25, 0.05),
            "中间区域",
        ),
        "right_zone": (("右边", "右侧", "右区", "right"), (-0.16, 0.05), "右侧区域"),
    }
    EXAMPLES: ClassVar[tuple[str, ...]] = (
        "把红色方块放到右边",
        "开始颜色分拣",
        "把三个方块堆起来",
        "机械臂归位",
        "急停",
    )

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[\s，。！？,!.?;；]", "", text.strip().lower())

    def parse(self, text: str) -> TaskIntent:
        normalized = self._normalize(text)
        if not normalized:
            return self._invalid("请输入任务指令")

        if any(term in normalized for term in ("解除急停", "恢复运行", "继续运行", "resume")):
            return self._simple("resume", "解除急停并恢复任务")
        if any(term in normalized for term in ("急停", "紧急停止", "emergencystop")):
            return self._simple("emergency_stop", "立即急停机械臂")
        if any(term in normalized for term in ("归位", "回零", "初始位置", "home")):
            return self._simple("home", "机械臂回到初始位置")
        if any(term in normalized for term in ("取消任务", "停止任务", "取消", "cancel")):
            return self._simple("cancel", "取消当前任务")
        if any(term in normalized for term in ("分拣", "分类", "sort")):
            return self._simple("sort", "按颜色分拣三个方块")
        if any(term in normalized for term in ("堆垛", "堆叠", "叠起来", "堆起来", "stack")):
            return self._simple("stack", "将三个方块堆成三层")

        objects = [
            name
            for name, terms in self.OBJECT_TERMS.items()
            if any(term in normalized for term in terms)
        ]
        targets = [
            name
            for name, (terms, _xy, _label) in self.TARGETS.items()
            if any(term in normalized for term in terms)
        ]
        has_pick_verb = any(
            term in normalized
            for term in ("抓", "拿", "放", "移动", "搬", "pick", "place", "move")
        )

        if len(objects) > 1:
            return self._invalid("一次只能指定一种颜色，请简化指令")
        if len(targets) > 1:
            return self._invalid("检测到多个目标区域，请只保留一个")
        if has_pick_verb or objects or targets:
            if not objects:
                return self._invalid("缺少方块颜色，请指定红色、蓝色或绿色")
            if not targets:
                return self._invalid("缺少目标区域，请指定左边、中间或右边")
            object_name = objects[0]
            target_name = targets[0]
            _terms, target_xy, target_label = self.TARGETS[target_name]
            return TaskIntent(
                valid=True,
                action="pick_and_place",
                object_name=object_name,
                target_name=target_name,
                target_xy=target_xy,
                confidence=1.0,
                summary=f"抓取{self.OBJECT_LABELS[object_name]}并放到{target_label}",
            )
        return self._invalid("暂时无法理解该指令，未执行任何动作")

    @staticmethod
    def _simple(action: str, summary: str) -> TaskIntent:
        return TaskIntent(valid=True, action=action, confidence=1.0, summary=summary)

    @staticmethod
    def _invalid(error: str) -> TaskIntent:
        return TaskIntent(valid=False, error=error, summary="指令未执行")

    def response(self, text: str) -> dict[str, Any]:
        return {
            "text": text,
            "intent": self.parse(text).to_dict(),
            "examples": list(self.EXAMPLES),
        }
