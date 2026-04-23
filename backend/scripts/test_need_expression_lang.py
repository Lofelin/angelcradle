"""
验证 scheduler.needs.rule_based_need / force_emit_need 的主字段按
BabyState.lang 选择语种——避免英文 baby 的 DM 聊天气泡泄漏中文对白。

[INPUT]: scheduler.needs, cradle.state, scenes
[OUTPUT]: exit 0 on success
[POS]: backend/scripts/ 的回归测试
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cradle.state import BabyState
from scheduler.needs import rule_based_need, force_emit_need


CJK = re.compile(r"[一-鿿]")


def _make_state(lang: str, phase: int) -> BabyState:
    s = BabyState(
        baby_id=f"AC-TEST-{lang}-P{phase}",
        species="human",
        current_phase=phase,
        lang=lang,
    )
    return s


def _has_cjk(*texts: str) -> bool:
    return any(t and CJK.search(t) for t in texts)


def test_force_emit_english_no_cjk():
    failures: list[str] = []
    for phase in range(12):
        state = _make_state("en", phase)
        need = force_emit_need(state, day=0)
        if need is None:
            failures.append(f"phase {phase}: force_emit_need returned None")
            continue
        leaked = []
        for key in ("expression", "signal", "facial", "body", "parent_hint"):
            v = need.get(key) or ""
            if CJK.search(v):
                leaked.append(f"{key}={v!r}")
        if leaked:
            failures.append(
                f"phase {phase}: EN force_emit leaked CJK: " + ", ".join(leaked)
            )
    assert not failures, "\n".join(failures)
    print("  [OK] force_emit_need(lang=en) 无中文主字段（phase 0-11）")


def test_force_emit_zh_sidecar_still_present():
    state = _make_state("zh", 4)
    need = force_emit_need(state, day=0)
    assert need is not None, "force_emit_need returned None for lang=zh phase=4"
    assert need.get("expression_zh") or need.get("expression"), (
        "zh sidecar or main expression missing"
    )
    assert need.get("expression_en"), (
        "expression_en sidecar missing for phase 4 (补齐的数据应有)"
    )
    print("  [OK] force_emit_need(lang=zh phase=4) 副字段 _zh/_en 皆可用")


def test_rule_based_english_scene_triggered():
    # 制造高压力 + 冷却到位，尽量触发 rule_based_need；跑 200 次任意成功 1 次即可。
    import random
    state = _make_state("en", 5)
    state.stress.stress_level = 0.6
    state.initiative.last_initiative_ts = -100  # 保证冷却过
    success = False
    for _ in range(200):
        random.seed()
        need = rule_based_need(state, day=100)
        if need is None:
            continue
        success = True
        for key in ("expression", "signal", "facial", "body", "parent_hint"):
            v = need.get(key) or ""
            assert not CJK.search(v), (
                f"rule_based_need(lang=en phase=5) 主字段泄漏中文: {key}={v!r}"
            )
        # reset pending 以便下次调用
        state.initiative.pending_initiative_id = ""
    assert success, "rule_based_need never fired in 200 attempts"
    print("  [OK] rule_based_need(lang=en phase=5) 主字段无中文")


if __name__ == "__main__":
    test_force_emit_english_no_cjk()
    test_force_emit_zh_sidecar_still_present()
    test_rule_based_english_scene_triggered()
    print("\nAll need-expression-lang tests passed.")
