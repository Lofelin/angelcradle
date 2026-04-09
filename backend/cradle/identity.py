"""
身份编译器：从 Baby 的 gestation_log 中提取先天约束。

这是子宫→摇篮的桥梁。gestation_log 的深度嵌套数据被编译为
扁平的 Identity 对象，用于约束摇篮中的所有行为。

编译分两步：
1. 规则提取（纯代码，无 LLM）— 从 JSON 结构中提取感官数值、反射、本能等
2. 约束生成（一次 LLM 调用）— 将提取的数据编译为自然语言行为约束

[INPUT]: 依赖 womb/baby.py 的 Baby 数据, cradle/state.py 的 Identity
[OUTPUT]: compile_identity() 函数
[POS]: cradle/ 的入口编译层，只在婴儿入摇篮时运行一次
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from .state import Identity, SensoryProfile

SPECIES_DIR = Path(__file__).parent.parent / "womb" / "species"

# ============================================================
# 感官通道映射：gestation_log 中的关键词 → 感官通道
# ============================================================

SENSE_KEYWORDS = {
    "hearing": ["hearing", "auditory", "sound", "acoustic", "ear", "cochlea"],
    "vision": ["vision", "visual", "sight", "eye", "retina", "optic"],
    "touch": ["touch", "tactile", "somatosensory", "skin", "haptic"],
    "smell": ["smell", "olfactory", "olfaction", "scent", "nose"],
    "proprioception": ["proprioception", "proprioceptive", "vestibular", "balance", "kinesthetic"],
}

AROUSAL_KEYWORDS = {
    "high": ["high arousal", "elevated", "hyperactive", "reactive", "heightened", "excitable",
             "low threshold", "sensitive to stimul"],
    "low": ["low arousal", "calm", "placid", "dampened", "hypoactive", "sluggish",
            "high threshold", "understimulated"],
}


def extract_innate_data(baby_data: dict) -> dict:
    """
    步骤 1: 规则提取（无 LLM，毫秒级）。

    返回 dict 含 sensory, arousal, reflexes, instincts, temperament, tendencies, defects。
    """
    gestation_log = baby_data.get("gestation_log", [])
    genes = baby_data.get("genes", {})
    # complication_names: list[str]，兼容 Baby 的 complications: list[dict]
    defects = baby_data.get("complication_names", [])
    if not defects:
        raw = baby_data.get("complications", [])
        defects = [c["defect"] if isinstance(c, dict) else c for c in raw]

    return {
        "sensory": _extract_sensory_profile(gestation_log),
        "arousal": _extract_arousal_baseline(gestation_log),
        "reflexes": _extract_reflexes(gestation_log),
        "instincts": _extract_instinct_loops(gestation_log),
        "temperament": _extract_temperament(gestation_log),
        "tendencies": genes.get("expression", []),
        "defects": defects,
    }


def generate_constraints(innate: dict, species: str) -> list[str]:
    """步骤 2: 约束生成（一次 LLM 调用，慢）。"""
    return _generate_constraints(
        innate["sensory"], innate["arousal"], innate["reflexes"],
        innate["instincts"], innate["temperament"],
        innate["tendencies"], innate["defects"], species,
    )


def compile_identity(baby_data: dict) -> Identity:
    """一步完成身份编译（同步便捷接口）。"""
    innate = extract_innate_data(baby_data)
    constraints = generate_constraints(innate, baby_data.get("species", "human"))

    return Identity(
        sensory_profile=innate["sensory"],
        arousal_baseline=innate["arousal"],
        reflex_patterns=innate["reflexes"],
        instinct_loops=innate["instincts"],
        temperament=innate["temperament"],
        tendencies=innate["tendencies"],
        defects=innate["defects"],
        constraints=constraints,
    )


def _extract_sensory_profile(log: list[dict]) -> SensoryProfile:
    """从 gestation_log 提取感官画像。"""
    # 收集所有阶段输出中的感官线索
    all_text = ""
    resource_allocations = {}

    for entry in log:
        response = entry.get("response", {})
        if isinstance(response, dict):
            all_text += json.dumps(response, ensure_ascii=False).lower()
            # 收集资源分配数据
            alloc = response.get("resource_allocation", {})
            for k, v in alloc.items():
                if isinstance(v, (int, float)):
                    resource_allocations[k.lower()] = resource_allocations.get(k.lower(), 0) + v
        elif isinstance(response, str):
            all_text += response.lower()

    # 从资源分配推断感官强度
    profile = SensoryProfile()
    sense_scores = {}

    for sense, keywords in SENSE_KEYWORDS.items():
        score = 0.0
        for keyword in keywords:
            # 资源分配中的直接分数
            for alloc_key, alloc_val in resource_allocations.items():
                if keyword in alloc_key:
                    score += alloc_val
            # 文本提及频率
            score += all_text.count(keyword) * 2
        sense_scores[sense] = score

    # 归一化到 0.1-0.9 范围
    if sense_scores:
        max_score = max(sense_scores.values()) or 1
        min_score = min(sense_scores.values())
        spread = max_score - min_score or 1
        for sense, score in sense_scores.items():
            normalized = 0.1 + 0.8 * (score - min_score) / spread
            setattr(profile, sense, round(normalized, 2))

    # 从 late_organogenesis 阶段的 primary/weak sense 直接读取
    for entry in log:
        if entry.get("stage") == "late_organogenesis":
            response = entry.get("response", {})
            if isinstance(response, dict):
                primary = response.get("primary_sense", "")
                weak = response.get("weak_sense", "")
                if primary:
                    for sense in SENSE_KEYWORDS:
                        if sense in primary.lower() or any(kw in primary.lower() for kw in SENSE_KEYWORDS[sense]):
                            profile.dominant = sense
                            setattr(profile, sense, max(getattr(profile, sense), 0.8))
                            break
                if weak:
                    for sense in SENSE_KEYWORDS:
                        if sense in weak.lower() or any(kw in weak.lower() for kw in SENSE_KEYWORDS[sense]):
                            profile.weak = sense
                            setattr(profile, sense, min(getattr(profile, sense), 0.25))
                            break

    return profile


def _extract_arousal_baseline(log: list[dict]) -> str:
    """从 late_neural 和 fetal_movement 阶段提取唤醒基线。"""
    text = ""
    for entry in log:
        if entry.get("stage") in ("late_neural", "fetal_movement"):
            response = entry.get("response", {})
            if isinstance(response, dict):
                text += json.dumps(response, ensure_ascii=False).lower()
                # 直接读取 arousal_baseline 字段
                ab = response.get("arousal_baseline", "")
                if ab:
                    text += " " + ab.lower()
            elif isinstance(response, str):
                text += response.lower()

    high_score = sum(text.count(kw) for kw in AROUSAL_KEYWORDS["high"])
    low_score = sum(text.count(kw) for kw in AROUSAL_KEYWORDS["low"])

    if high_score > low_score + 2:
        return "high"
    elif low_score > high_score + 2:
        return "low"
    return "moderate"


def _extract_reflexes(log: list[dict]) -> list[dict]:
    """从 early_neural 阶段提取原始反射。"""
    for entry in log:
        if entry.get("stage") == "early_neural":
            response = entry.get("response", {})
            if isinstance(response, dict):
                reflexes = response.get("reflexes", [])
                if isinstance(reflexes, list):
                    # 标准化格式
                    result = []
                    for r in reflexes:
                        if isinstance(r, str):
                            result.append({"description": r})
                        elif isinstance(r, dict):
                            result.append(r)
                    return result
    return []


def _extract_instinct_loops(log: list[dict]) -> list[dict]:
    """从 late_neural 阶段提取本能回路。"""
    for entry in log:
        if entry.get("stage") == "late_neural":
            response = entry.get("response", {})
            if isinstance(response, dict):
                loops = response.get("instinct_loops", [])
                if isinstance(loops, list):
                    result = []
                    for loop in loops:
                        if isinstance(loop, str):
                            result.append({"description": loop})
                        elif isinstance(loop, dict):
                            result.append(loop)
                    return result
    return []


def _extract_temperament(log: list[dict]) -> str:
    """从 fetal_movement 阶段提取气质萌芽。"""
    for entry in log:
        if entry.get("stage") == "fetal_movement":
            response = entry.get("response", {})
            if isinstance(response, dict):
                return response.get("temperament_seed", "")
            elif isinstance(response, str):
                return response[:200]
    return ""


def _generate_constraints(
    sensory: SensoryProfile,
    arousal: str,
    reflexes: list[dict],
    instincts: list[dict],
    temperament: str,
    tendencies: list[str],
    defects: list[str],
    species: str,
) -> list[str]:
    """
    用一次 LLM 调用将提取的数据编译为行为约束。

    如果 LLM 不可用，降级为规则生成。
    """
    try:
        return _llm_generate_constraints(
            sensory, arousal, reflexes, instincts,
            temperament, tendencies, defects, species,
        )
    except Exception:
        return _rule_generate_constraints(sensory, arousal, defects)


def _llm_generate_constraints(
    sensory: SensoryProfile,
    arousal: str,
    reflexes: list[dict],
    instincts: list[dict],
    temperament: str,
    tendencies: list[str],
    defects: list[str],
    species: str,
) -> list[str]:
    """LLM 编译行为约束。"""
    from llm import create_client, parse_json, get_model

    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    client = create_client(provider)
    model = get_model(provider)

    prompt = f"""You are compiling a behavioral constraint profile for a newborn {species}.

## Innate Data (from gestational development)

### Sensory Profile
- Hearing: {sensory.hearing} ({"dominant" if sensory.dominant == "hearing" else "weak" if sensory.weak == "hearing" else "normal"})
- Vision: {sensory.vision} ({"dominant" if sensory.dominant == "vision" else "weak" if sensory.weak == "vision" else "normal"})
- Touch: {sensory.touch} ({"dominant" if sensory.dominant == "touch" else "weak" if sensory.weak == "touch" else "normal"})
- Smell: {sensory.smell} ({"dominant" if sensory.dominant == "smell" else "weak" if sensory.weak == "smell" else "normal"})
- Proprioception: {sensory.proprioception}

### Arousal Baseline: {arousal}

### Primitive Reflexes
{json.dumps(reflexes, ensure_ascii=False, indent=2)}

### Instinct Loops
{json.dumps(instincts, ensure_ascii=False, indent=2)}

### Temperament Seed
{temperament}

### Innate Tendencies
{json.dumps(tendencies, ensure_ascii=False, indent=2)}

### Congenital Defects
{json.dumps(defects, ensure_ascii=False) if defects else "None"}

## Task

Compile 5-8 behavioral constraints that this individual MUST follow throughout growth.
Each constraint should be:
1. Specific and actionable (not "tends to be sensitive" but "reacts to sudden loud sounds with full-body startle and 30+ seconds of distress")
2. Traceable to the innate data above
3. Expressed as a behavioral rule, not a personality label

Output as JSON array of strings. Each string is one constraint.
"""

    from llm import call_llm
    raw = call_llm(prompt, client, model, provider)
    parsed = parse_json(raw)

    if isinstance(parsed, list):
        return [str(c) for c in parsed]
    elif isinstance(parsed, dict) and "constraints" in parsed:
        return [str(c) for c in parsed["constraints"]]
    return [str(parsed)]


def _rule_generate_constraints(
    sensory: SensoryProfile,
    arousal: str,
    defects: list[str],
) -> list[str]:
    """降级方案：纯规则生成约束。"""
    constraints = []

    # 感官约束
    if sensory.dominant:
        constraints.append(
            f"Dominant sense is {sensory.dominant}. Reacts most strongly to {sensory.dominant} channel stimuli. "
            f"Tends to understand and describe experiences through {sensory.dominant}."
        )
    if sensory.weak:
        constraints.append(
            f"Weak sense is {sensory.weak}. Responds poorly to {sensory.weak} channel stimuli. "
            f"Visibly struggles with tasks requiring {sensory.weak} perception."
        )

    # 唤醒基线
    if arousal == "high":
        constraints.append(
            "High arousal baseline — overreacts to stimuli, slow recovery, easily over-activated. "
            "More prone to meltdowns in noisy or high-stimulation environments."
        )
    elif arousal == "low":
        constraints.append(
            "Low arousal baseline — under-reacts to stimuli, needs stronger input to be activated. "
            "More comfortable in quiet environments, but may respond slowly to social signals."
        )

    # 缺陷约束
    for defect in defects:
        constraints.append(
            f"Congenital condition: {defect.replace('_', ' ')}. This condition persistently affects physical abilities and developmental ceiling. Cannot be ignored."
        )

    return constraints
