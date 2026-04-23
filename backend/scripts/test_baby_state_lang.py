"""
BabyState.lang 字段自检脚本——验证默认值 / 持久化 / 老 archive 兼容。

运行方式:
    python backend/scripts/test_baby_state_lang.py

[INPUT]: 无（使用临时 archive 目录做 isolation）
[OUTPUT]: stdout 打印各 case 结果, 全部通过则 exit 0, 任一失败 exit 1
[POS]: backend/scripts/ 的 i18n-runtime capability 自检, 对应 fix-lifeline-i18n 任务 1.5/1.6
[PROTOCOL]: 变更时更新此头部, 然后检查 CLAUDE.md
"""

from __future__ import annotations

import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _check(cond: bool, msg: str):
    if not cond:
        print(f"  [FAIL] {msg}")
        raise AssertionError(msg)
    print(f"  [OK] {msg}")


def test_default_lang_is_en():
    print("[1] Default lang is 'en' when not specified")
    from cradle.state import BabyState
    state = BabyState(baby_id="AC-TEST-0001")
    _check(state.lang == "en", f"BabyState() default lang == 'en' (got {state.lang!r})")


def test_explicit_lang_persists_and_reloads():
    print("[2] Explicit lang 'en' persists to state.json and reloads")
    from cradle.state import BabyState
    with tempfile.TemporaryDirectory() as tmp:
        # monkeypatch ARCHIVE_DIR 到临时目录，避免污染真实 archive
        import cradle.state as st
        original = st.ARCHIVE_DIR
        from pathlib import Path
        st.ARCHIVE_DIR = Path(tmp)
        try:
            state = BabyState(baby_id="AC-TEST-0002", lang="en")
            st.save_state(state)
            loaded = st.load_state("AC-TEST-0002")
            _check(loaded is not None, "load_state returns non-None after save")
            _check(loaded.lang == "en", f"Reloaded state.lang == 'en' (got {loaded.lang!r})")
        finally:
            st.ARCHIVE_DIR = original


def test_legacy_archive_without_lang_defaults_to_en():
    print("[3] Legacy archive without 'lang' field loads with lang='en' (new default)")
    from cradle.state import BabyState
    # 模拟老 archive 的 dict（无 lang 字段）
    legacy_dict = {
        "baby_id": "AC-LEGACY-0001",
        "species": "human",
        "name": "",
        # 故意不放 lang
        "identity": {},
        "current_phase": 0,
        "age_days": 0,
        "capabilities": [],
        "expression_mode": "cry_only",
    }
    state = BabyState.from_dict(legacy_dict)
    _check(state.baby_id == "AC-LEGACY-0001", "from_dict preserves baby_id")
    _check(state.lang == "en", f"Legacy dict without lang → state.lang == 'en' (got {state.lang!r})")


def test_baby_dataclass_carries_lang():
    print("[4] Baby (womb output) carries lang to to_dict()")
    from womb.baby import Baby
    b_default = Baby(
        id="AC-TEST-0003", species="human", sex="male", phenotype={},
        born_at="2026-01-01T00:00:00Z", genes={}, first_cry="", gestation_log=[],
        environment={},
    )
    _check(b_default.lang == "en", "Baby default lang == 'en'")
    _check(b_default.to_dict()["lang"] == "en", "Baby.to_dict() contains lang='en'")

    b_en = Baby(
        id="AC-TEST-0004", species="human", sex="female", phenotype={},
        born_at="2026-01-01T00:00:00Z", genes={}, first_cry="", gestation_log=[],
        environment={}, lang="en",
    )
    _check(b_en.to_dict()["lang"] == "en", "Baby(lang='en').to_dict() contains lang='en'")


def main():
    test_default_lang_is_en()
    test_explicit_lang_persists_and_reloads()
    test_legacy_archive_without_lang_defaults_to_en()
    test_baby_dataclass_carries_lang()
    print("\nAll lang-field tests passed.")


if __name__ == "__main__":
    main()
