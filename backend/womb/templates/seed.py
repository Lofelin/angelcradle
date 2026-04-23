"""
把 rule_engine.py 的硬编码 first_cry 模板作为种子落库到 JSON，作为增量生成的起点。

运行：
  cd backend
  python -m womb.templates.seed

[INPUT]: 无（从 rule_engine._CRY_ONSET / _CRY_QUALITY / _CRY_BODY 读）
[OUTPUT]: templates/birth/first_cry_*.json 9 个文件
[POS]: womb/templates/ 的一次性种子工具
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
from pathlib import Path

from womb.rule_engine import (
    _CRY_ONSET, _CRY_QUALITY, _CRY_BODY,
    _BIRTH_EYES, _BIRTH_POSTURE, _BIRTH_TONE, _BIRTH_COLOR,
)

_ROOT = Path(__file__).parent


def _dump(key: str, filter_key: str, filter_value: str, texts: list[str]) -> None:
    """幂等：若文件已有内容（>=条目数 >= len(texts) 且非空），跳过以保护 LLM 生成结果。"""
    path = _ROOT / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            exist_count = existing.get("count", 0) if isinstance(existing, dict) else 0
            if exist_count >= len(texts) and exist_count > 0:
                print(f"  ⊙ {key}: 已有 {exist_count} 条，跳过种子化")
                return
        except Exception:
            pass
    templates = [
        {"text": t, "vars": {}, "applies_when": {filter_key: filter_value}}
        for t in texts
    ]
    payload = {
        "key": key,
        "count": len(templates),
        "applies_when_default": {filter_key: filter_value},
        "templates": templates,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ {key}: {len(templates)} seed templates")


# 硬编码的 immediate_state 原本不分档，这里按语义粗分 3 档作为种子，
# 后续 LLM 会把每档扩到 30+ 条并严格区分 tone
_EYES_SEED = {
    "high":     ["eyes wide, dark and unfocused", "blinking rapidly, overwhelmed"],
    "moderate": ["eyes squinting against the light", "eyes open but glazed, seeing almost nothing yet"],
    "low":      ["eyes sealed shut", "one eye cracked open, the other shut"],
}
_POSTURE_SEED = {
    "high":     ["splayed briefly open, then curling back inward", "arms reaching outward, legs tucked"],
    "moderate": ["legs drawn up, arms across chest", "one fist pressed against the cheek",
                 "chin tucked, shoulders hunched", "head turned to one side, body curved"],
    "low":      ["limbs tightly flexed in fetal curl", "body limp and heavy with exhaustion"],
}
_TONE_SEED = {
    "high":     ["muscle tone strong — resists extension", "vigorous tone, active movement",
                 "hypertonic — limbs stiff and resistant"],
    "moderate": ["tone moderate, moves when stimulated", "relaxed, pliable, unhurried"],
    "low":      ["slightly floppy, tone building gradually"],
}
_COLOR_SEED = {
    "strong":   ["pink spreading from the trunk outward", "ruddy and flushed, capillaries flooding",
                 "deep pink, healthy perfusion from the start"],
    "moderate": ["dusky at first, clearing with each breath", "blotchy red and white, circulation adjusting"],
    "weak":     ["pale but warming quickly under the lamp"],
}


def main():
    print("种子化 first_cry 模板库...")
    for arousal, texts in _CRY_ONSET.items():
        _dump(f"birth/first_cry_onset_{arousal}", "arousal", arousal, list(texts))
    for arousal, texts in _CRY_QUALITY.items():
        _dump(f"birth/first_cry_quality_{arousal}", "arousal", arousal, list(texts))
    for arousal, texts in _CRY_BODY.items():
        _dump(f"birth/first_cry_body_{arousal}", "arousal", arousal, list(texts))

    print("\n种子化 immediate_state 模板库...")
    for arousal, texts in _EYES_SEED.items():
        _dump(f"birth/immediate_eyes_{arousal}", "arousal", arousal, texts)
    for arousal, texts in _POSTURE_SEED.items():
        _dump(f"birth/immediate_posture_{arousal}", "arousal", arousal, texts)
    for arousal, texts in _TONE_SEED.items():
        _dump(f"birth/immediate_tone_{arousal}", "arousal", arousal, texts)
    for vitality, texts in _COLOR_SEED.items():
        _dump(f"birth/immediate_color_{vitality}", "vitality", vitality, texts)

    print("\n完成。下一步：python -m womb.templates.generate")


if __name__ == "__main__":
    main()
