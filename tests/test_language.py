import pytest

from planner.rule_parser import RuleBasedTaskParser


@pytest.fixture
def parser() -> RuleBasedTaskParser:
    return RuleBasedTaskParser()


@pytest.mark.parametrize(
    ("text", "action"),
    [
        ("开始颜色分拣", "sort"),
        ("把三个方块堆起来", "stack"),
        ("机械臂归位", "home"),
        ("急停", "emergency_stop"),
        ("解除急停并恢复运行", "resume"),
        ("取消当前任务", "cancel"),
    ],
)
def test_simple_commands(parser: RuleBasedTaskParser, text: str, action: str):
    intent = parser.parse(text)
    assert intent.valid
    assert intent.action == action


def test_pick_and_place_command(parser: RuleBasedTaskParser):
    intent = parser.parse("请把红色方块放到右边。")
    assert intent.valid
    assert intent.action == "pick_and_place"
    assert intent.object_name == "red_cube"
    assert intent.target_name == "right_zone"
    assert intent.target_xy == (-0.16, 0.05)


@pytest.mark.parametrize("text", ["", "帮我操作一下", "把方块放到左边", "抓取蓝色方块"])
def test_unsafe_or_incomplete_commands_are_rejected(parser: RuleBasedTaskParser, text: str):
    intent = parser.parse(text)
    assert not intent.valid
    assert intent.error
