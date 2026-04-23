"""
world.py _build_snapshot_prompt 双语分叉自检——验证中英 prompt 正确分支。

运行方式:
    python backend/scripts/test_world_snapshot_prompt_lang.py

[INPUT]: 无（构造 mock state）
[OUTPUT]: stdout 打印各 case 结果, 全部通过则 exit 0, 任一失败 exit 1
[POS]: backend/scripts/ 的 i18n-runtime capability 自检, 对应 fix-lifeline-i18n 任务 4.5/4.6
[PROTOCOL]: 变更时更新此头部, 然后检查 CLAUDE.md
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _check(cond: bool, msg: str):
    if not cond:
        print(f"  [FAIL] {msg}")
        raise AssertionError(msg)
    print(f"  [OK] {msg}")


def _build_mock_state(lang: str):
    from cradle.state import BabyState
    return BabyState(
        baby_id="AC-TEST-WORLD",
        species="human",
        lang=lang,
        current_phase=0,
        age_days=1,
        life_tags=set(),
        capabilities=[],
        sim_time=0.0,
    )


def test_zh_prompt_contains_chinese_rule():
    print("[1] lang='zh' prompt contains Chinese rule and placeholder")
    from world import _build_snapshot_prompt
    state = _build_mock_state("zh")
    prompt = _build_snapshot_prompt(state, None)
    _check("MUST be in Chinese" in prompt, "prompt 含 'MUST be in Chinese'")
    _check("MUST be in English" not in prompt, "prompt 不含 'MUST be in English'")
    _check("天气描述" in prompt, "JSON placeholder 含中文 '天气描述'")
    _check("家庭事件弧线" in prompt, "JSON placeholder 含中文 '家庭事件弧线'")
    _check("「」" in prompt, "Rule 11 含中文双引号替代 '「」'")


def test_en_prompt_contains_english_rule():
    print("[2] lang='en' prompt contains English rule and placeholder")
    from world import _build_snapshot_prompt
    state = _build_mock_state("en")
    prompt = _build_snapshot_prompt(state, None)
    _check("MUST be in English" in prompt, "prompt 含 'MUST be in English'")
    _check("MUST be in Chinese" not in prompt, "prompt 不含 'MUST be in Chinese'")
    _check("weather description" in prompt, "JSON placeholder 含英文 'weather description'")
    _check("family story arc" in prompt, "JSON placeholder 含英文 'family story arc'")
    # 英文分支不应出现中文 JSON 模板字段
    _check("天气描述" not in prompt, "EN prompt 不含中文 placeholder '天气描述'")
    _check("家庭事件弧线" not in prompt, "EN prompt 不含中文 placeholder '家庭事件弧线'")


def test_default_state_lang_is_en():
    print("[3] Missing lang attribute falls back to 'en' (getattr default)")
    from world import _build_snapshot_prompt
    # 构造一个没有 lang 属性的 mock，使用 types.SimpleNamespace
    from types import SimpleNamespace
    from cradle.state import StressState

    stress = StressState()
    state = SimpleNamespace(
        baby_id="AC-TEST-WORLD-LEGACY",
        species="human",
        current_phase=0,
        age_days=1,
        life_tags=set(),
        capabilities=[],
        sim_time=0.0,
        time_scale="normal",
        stress=stress,
        memories=[],
        triggered_events=set(),
        # 故意不设 lang 属性
    )
    prompt = _build_snapshot_prompt(state, None)
    _check("MUST be in English" in prompt, "无 lang 属性 → 默认英文 prompt")


def main():
    test_zh_prompt_contains_chinese_rule()
    test_en_prompt_contains_english_rule()
    test_default_state_lang_is_en()
    print("\nAll world snapshot prompt bilingual tests passed.")


if __name__ == "__main__":
    main()
