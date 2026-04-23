"""
force_emit_need 自检脚本——验证阶段兜底需求发射器的核心不变量。

运行方式:
    python backend/scripts/test_force_emit_need.py

[INPUT]: 无
[OUTPUT]: stdout 打印各 case 结果, 全部通过则 exit 0, 任一失败 exit 1
[POS]: backend/scripts/ 的主动需求兜底自检, 配套 scheduler/needs.py force_emit_need
[PROTOCOL]: 变更时更新此头部, 然后检查 CLAUDE.md
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from scheduler.needs import force_emit_need  # noqa: E402


def _check(cond: bool, msg: str):
    if not cond:
        print(f"  FAIL {msg}")
        raise AssertionError(msg)
    print(f"  OK   {msg}")


def _make_state(phase: int = 3, pending_id: str = "", lang: str = "en"):
    ini = SimpleNamespace(
        pending_initiative_id=pending_id,
        last_initiative_ts=0.0,
    )
    return SimpleNamespace(initiative=ini, current_phase=phase, lang=lang)


def test_pending_returns_none():
    print("[1] pending_initiative_id 占用时返回 None")
    state = _make_state(phase=3, pending_id="n-123")
    result = force_emit_need(state, day=100)
    _check(result is None, "pending 占用 → None (视为已满足)")


def test_normal_phase_emits():
    print("[2] 正常阶段能产出 need")
    state = _make_state(phase=3)
    result = force_emit_need(state, day=50)
    _check(result is not None, "phase=3 产出非空 need")
    _check("trigger" in result, "含 trigger 字段")
    _check("urgency" in result, "含 urgency 字段")
    _check("cause_tags" in result, "含 cause_tags 字段")
    _check(
        "forced:min_one_per_phase" in result["cause_tags"],
        "cause_tags 含 forced:min_one_per_phase 标记",
    )
    _check(
        result["intent_id"].startswith("force-"),
        "intent_id 以 force- 前缀开头",
    )


def test_all_phases_emit():
    print("[3] 0-11 全阶段都能产出 need（场景库或兜底 trigger）")
    for phase in range(12):
        state = _make_state(phase=phase)
        result = force_emit_need(state, day=10)
        _check(
            result is not None,
            f"phase={phase} 产出非空 need (trigger={result.get('trigger') if result else None})",
        )


def test_behavior_type_by_phase():
    print("[4] behavior_type 按 phase 分段 (<=1 cry, >1 verbal)")
    for phase, expected in [(0, "cry"), (1, "cry"), (2, "verbal"), (5, "verbal")]:
        state = _make_state(phase=phase)
        result = force_emit_need(state, day=10)
        _check(
            result["behavior_type"] == expected,
            f"phase={phase} → behavior_type={expected}",
        )


def test_out_of_range_phase_fallback():
    print("[5] 场景库无命中时走 trigger 兜底")
    state = _make_state(phase=99)
    result = force_emit_need(state, day=10)
    _check(result is not None, "phase=99 也能产出（trigger 兜底）")
    _check(
        result["trigger"] in ("hunger", "curious"),
        f"兜底 trigger={result['trigger']} 在 (hunger, curious) 中",
    )


def main():
    print("=" * 60)
    print("force_emit_need 自检")
    print("=" * 60)
    cases = [
        test_pending_returns_none,
        test_normal_phase_emits,
        test_all_phases_emit,
        test_behavior_type_by_phase,
        test_out_of_range_phase_fallback,
    ]
    for fn in cases:
        try:
            fn()
        except AssertionError as e:
            print(f"\n{fn.__name__} 失败: {e}")
            sys.exit(1)
    print("\n全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
