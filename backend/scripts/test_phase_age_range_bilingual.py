"""
phases.py age_range 双字段覆盖自检——验证 12 phase 的 age_range_zh/age_range_en 均非空。

运行方式:
    python backend/scripts/test_phase_age_range_bilingual.py

[INPUT]: 无
[OUTPUT]: stdout 打印各 phase 双字段, 全部通过则 exit 0, 任一失败 exit 1
[POS]: backend/scripts/ 的 i18n-runtime capability 自检, 对应 fix-lifeline-i18n 任务 3.3
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


def test_all_phases_have_both_langs():
    print("[1] All 12 phases have non-empty age_range_zh + age_range_en")
    from cradle.phases import PHASES
    _check(len(PHASES) == 12, f"PHASES count == 12 (got {len(PHASES)})")
    for p in PHASES:
        zh = getattr(p, "age_range_zh", None)
        en = getattr(p, "age_range_en", None)
        _check(isinstance(zh, str) and len(zh) > 0,
               f"phase {p.index} ({p.name}): age_range_zh = {zh!r}")
        _check(isinstance(en, str) and len(en) > 0,
               f"phase {p.index} ({p.name}): age_range_en = {en!r}")
        # 英文字段禁止出现 CJK 字符（防回填漏改）
        has_cjk = any('一' <= ch <= '鿿' for ch in en)
        _check(not has_cjk,
               f"phase {p.index} age_range_en 不含中文 (got {en!r})")


def test_age_range_method_dispatches():
    print("[2] phase.age_range(lang) method dispatches correctly")
    from cradle.phases import PHASES
    p0 = PHASES[0]
    _check(p0.age_range("zh") == p0.age_range_zh,
           f"phase.age_range('zh') == age_range_zh ({p0.age_range_zh!r})")
    _check(p0.age_range("en") == p0.age_range_en,
           f"phase.age_range('en') == age_range_en ({p0.age_range_en!r})")
    # 缺省 / 未知 lang 回退到 en
    _check(p0.age_range() == p0.age_range_en, "phase.age_range() (默认) → en")
    _check(p0.age_range("fr") == p0.age_range_en, "phase.age_range('fr') → en (未知降级)")


def test_sample_values():
    print("[3] Sample values match expected format")
    from cradle.phases import PHASES
    cases = [
        (0, "0-1个月", "0-1 month"),
        (5, "12-18个月", "12-18 months"),
        (7, "2-3岁", "2-3 years"),
        (11, "6-7岁", "6-7 years"),
    ]
    for idx, exp_zh, exp_en in cases:
        p = PHASES[idx]
        _check(p.age_range_zh == exp_zh,
               f"phase {idx} age_range_zh == {exp_zh!r} (got {p.age_range_zh!r})")
        _check(p.age_range_en == exp_en,
               f"phase {idx} age_range_en == {exp_en!r} (got {p.age_range_en!r})")


def main():
    test_all_phases_have_both_langs()
    test_age_range_method_dispatches()
    test_sample_values()
    print("\nAll phases age_range bilingual tests passed.")


if __name__ == "__main__":
    main()
