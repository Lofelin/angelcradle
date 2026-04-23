"""
i18n-runtime 集成反向断言——构造 lang='en' 的 baby，验证关键调用点输出纯英文。

运行方式:
    python backend/scripts/test_lifeline_i18n_integration.py

[INPUT]: 无（模拟 BabyState + 调用 build_snapshot_prompt / phase.age_range / handlers 事件构造）
[OUTPUT]: stdout 打印各 case 结果, 全部通过则 exit 0, 任一失败 exit 1
[POS]: backend/scripts/ 的 i18n-runtime capability 反向断言 (Gate 2/3), 对应 fix-lifeline-i18n 任务 6.2/6.3
[PROTOCOL]: 变更时更新此头部, 然后检查 CLAUDE.md
"""

from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# 用于检测中文字符（CJK Unified Ideographs）的正则
_CJK_RE = re.compile(r'[一-鿿]')


def _check(cond: bool, msg: str):
    if not cond:
        print(f"  [FAIL] {msg}")
        raise AssertionError(msg)
    print(f"  [OK] {msg}")


def _build_mock_state(lang: str, phase_idx: int = 0):
    from cradle.state import BabyState
    return BabyState(
        baby_id="AC-I18N-TEST",
        species="human",
        lang=lang,
        current_phase=phase_idx,
        age_days=1,
        life_tags=set(),
        capabilities=[],
        sim_time=0.0,
    )


def test_en_phase_payload_has_no_chinese():
    print("[1] lang='en' baby phase_start payload contains no CJK characters (in lang-specific fields)")
    from cradle.phases import PHASES
    state = _build_mock_state("en", phase_idx=0)
    phase = PHASES[0]
    # 构造 handlers.py 里的 phase_start 事件（模拟 scheduler.handlers.on_phase_start 的 payload 片段）
    payload = {
        "event": "phase_start",
        "phase_index": phase.index,
        "phase_name": phase.name,
        "phase_display": phase.display_name,
        "age_range": phase.age_range(state.lang),
        "age_range_zh": phase.age_range_zh,
        "age_range_en": phase.age_range_en,
        "description": phase.description,
        "expression_mode": phase.expression_mode,
    }
    # 关键字段：age_range 应为英文，description 由英文 PHASES 数据决定
    _check(payload["age_range"] == "0-1 month",
           f"age_range == '0-1 month' (got {payload['age_range']!r})")
    _check(not _CJK_RE.search(payload["age_range"]),
           f"payload.age_range 无 CJK 字符 (got {payload['age_range']!r})")
    # age_range_en 字段纯英文
    _check(not _CJK_RE.search(payload["age_range_en"]),
           f"payload.age_range_en 无 CJK (got {payload['age_range_en']!r})")
    # age_range_zh 字段是中文（保留供前端按需使用）
    _check(_CJK_RE.search(payload["age_range_zh"]) is not None,
           f"payload.age_range_zh 含 CJK (got {payload['age_range_zh']!r})")


def test_zh_phase_payload_is_chinese():
    print("[2] lang='zh' baby phase_start payload age_range is Chinese (regression)")
    from cradle.phases import PHASES
    state = _build_mock_state("zh", phase_idx=0)
    phase = PHASES[0]
    age_range = phase.age_range(state.lang)
    _check(age_range == "0-1个月", f"age_range == '0-1个月' (got {age_range!r})")


def test_en_world_snapshot_prompt_no_chinese_in_rules():
    print("[3] lang='en' world snapshot prompt 'Rules' section has no CJK")
    from world import _build_snapshot_prompt
    state = _build_mock_state("en", phase_idx=0)
    prompt = _build_snapshot_prompt(state, None)
    # prompt 分三段：Profile / Task / Rules + Output JSON
    # Rules 段从 "Rules:" 到 "Output JSON:"
    rules_start = prompt.find("Rules:")
    rules_end = prompt.find("Output JSON:")
    _check(rules_start > 0 and rules_end > rules_start, "prompt 包含 Rules 和 Output JSON 区段")
    rules_block = prompt[rules_start:rules_end]
    cjk_found = _CJK_RE.findall(rules_block)
    _check(not cjk_found,
           f"Rules block 无 CJK (found: {cjk_found[:5]})")
    # Output JSON 区段也应无中文 placeholder
    output_block = prompt[rules_end:]
    _check("weather description" in output_block, "Output JSON 含英文 'weather description'")
    # 允许 Rule 11 里不含「」（已改为单引号）
    _check("「" not in output_block, "EN Output JSON 不含中文双引号 '「'")


def test_zh_world_snapshot_prompt_chinese_rules():
    print("[4] lang='zh' world snapshot prompt Rule 10 is Chinese (regression)")
    from world import _build_snapshot_prompt
    state = _build_mock_state("zh", phase_idx=0)
    prompt = _build_snapshot_prompt(state, None)
    _check("MUST be in Chinese" in prompt, "ZH prompt 含 Chinese 规则")
    _check("天气描述" in prompt, "ZH prompt 含中文 placeholder '天气描述'")


def test_archive_state_json_roundtrip_preserves_lang():
    print("[5] Archive state.json roundtrip preserves lang='en'")
    import tempfile
    from pathlib import Path
    import cradle.state as st
    from cradle.state import BabyState

    with tempfile.TemporaryDirectory() as tmp:
        original = st.ARCHIVE_DIR
        st.ARCHIVE_DIR = Path(tmp)
        try:
            state = BabyState(baby_id="AC-I18N-ROUNDTRIP", lang="en")
            st.save_state(state)
            # 直接读原始 JSON，确认 lang 字段存在
            import json
            raw = json.loads((Path(tmp) / "AC-I18N-ROUNDTRIP" / "state.json").read_text())
            _check(raw.get("lang") == "en",
                   f"state.json raw contains 'lang': 'en' (got {raw.get('lang')!r})")
            reloaded = st.load_state("AC-I18N-ROUNDTRIP")
            _check(reloaded.lang == "en", f"Reloaded state.lang == 'en' (got {reloaded.lang!r})")
        finally:
            st.ARCHIVE_DIR = original


def main():
    test_en_phase_payload_has_no_chinese()
    test_zh_phase_payload_is_chinese()
    test_en_world_snapshot_prompt_no_chinese_in_rules()
    test_zh_world_snapshot_prompt_chinese_rules()
    test_archive_state_json_roundtrip_preserves_lang()
    print("\nAll lifeline i18n integration tests passed.")


if __name__ == "__main__":
    main()
