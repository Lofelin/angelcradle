"""
发育阶段编排：7 阶段顺序调用 + 预算执法 + LLM 母体叙事 + 代码 budget delta + 分层约束注入 + 跨阶段校验 + 流式输出。

集成：动态环境、营养素阶段敏感性、致畸时间窗口、胎盘效率、免疫风险、遗传基因型注入。

[INPUT]: 物种蓝图、环境、缺陷、LLM client、可选 genotype
[OUTPUT]: 导出 express(), express_stream(), build_stage_prompts(), STAGE_NAMES, STAGE_DURATIONS, RESOURCE_BUDGET
[POS]: womb/ 的发育引擎核心，被 womb/__init__.py 和 api/conceive.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import os
import time as _time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import logging
import yaml

logger = logging.getLogger(__name__)

from .llm import _create_client, _call_llm, _parse_json, _get_model
from .prompts import (
    STAGE_1_ZYGOTE, STAGE_2A_EARLY_ORGANOGENESIS, STAGE_2B_LATE_ORGANOGENESIS,
    STAGE_3A_EARLY_NEURAL, STAGE_3B_LATE_NEURAL, STAGE_4_FETAL_MOVEMENT,
    STAGE_5_BIRTH, MATERNAL_RESPONSE_PROMPT, SEX_DISPLAY,
)
from .environment import format_environment, environment_impact_text, get_effective_budget
from .fate import validate_resource_semantics, validate_defect_consistency, roll_stage_miscarriage
from .dynamic_env import roll_env_change, apply_maternal_feedback, compute_budget_delta
from .nutrients import get_stage_nutrient_effects, format_nutrients_for_prompt
from .teratogen import get_teratogen_risk, format_teratogen_for_prompt
from .placenta import update_placenta, get_placenta_budget_factor, format_placenta_for_prompt
from .immunity import get_immune_risk_modifiers, format_immunity_for_prompt
from .heredity import format_genetics_for_prompt
from .hormones import compute_hormones, get_hormone_effects, format_hormones_for_prompt
from .vitals import compute_vitals, format_vitals_for_display
from .epigenetics import format_epigenetics_for_prompt
from . import graph_story


SPECIES_DIR = Path(__file__).parent / "species"

# ============================================================
# Resource budget per stage
# ============================================================

RESOURCE_BUDGET = {
    "zygote": 100,
    "early_organogenesis": 50,
    "late_organogenesis": 40,
    "early_neural": 45,
    "late_neural": 35,
    "fetal_movement": 60,
    "birth": 100,
}

# 7-stage durations in days
STAGE_DURATIONS = {
    "human": {"zygote": 7, "early_organogenesis": 28, "late_organogenesis": 21, "early_neural": 35, "late_neural": 35, "fetal_movement": 84, "birth": 70},
    "dog": {"zygote": 3, "early_organogenesis": 7, "late_organogenesis": 7, "early_neural": 7, "late_neural": 7, "fetal_movement": 21, "birth": 11},
    "cat": {"zygote": 3, "early_organogenesis": 7, "late_organogenesis": 7, "early_neural": 7, "late_neural": 7, "fetal_movement": 21, "birth": 13},
}

STAGE_NAMES = [
    "zygote", "early_organogenesis", "late_organogenesis",
    "early_neural", "late_neural", "fetal_movement", "birth",
]

STAGE_DISPLAY = {
    "zygote": "Zygote",
    "early_organogenesis": "Early Organogenesis",
    "late_organogenesis": "Late Organogenesis",
    "early_neural": "Early Neural",
    "late_neural": "Late Neural",
    "fetal_movement": "Fetal Movement",
    "birth": "Birth",
}


# ============================================================
# Blueprint loading & formatting
# ============================================================

def _load_blueprint(species: str) -> dict:
    """Load species blueprint."""
    path = SPECIES_DIR / f"{species}.yaml"
    if not path.is_file():
        raise ValueError(f"Unknown species '{species}': {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _format_section(blueprint: dict, key: str, title: str) -> str:
    """Format a single blueprint section."""
    data = blueprint.get(key)
    if not data:
        return ""
    lines = [f"### {title}"]
    for f, value in data.items():
        lines.append(f"- {f}: {value}")
    return "\n".join(lines)


def _format_blueprint(blueprint: dict) -> str:
    """Format species blueprint for Zygote stage — only sections relevant to
    foundational biological structure. Zygote decides body constitution,
    sensory bias, neural density, and resource allocation; it does not need
    cognition, ecology, migration history, or evolutionary phylogeny."""
    zygote_sections = {
        "physical": "Physical Traits",
        "morphology": "Morphology",
        "reproduction": "Reproduction",
        "development": "Development",
    }
    sections = []
    for key, title in zygote_sections.items():
        s = _format_section(blueprint, key, title)
        if s:
            sections.append(s)
    return "\n\n".join(sections)


def _format_phenotype(phenotype: dict) -> str:
    """Format phenotype information."""
    if not phenotype:
        return ""
    lines = []
    for f, value in phenotype.items():
        label = {"race": "Race", "breed": "Breed"}.get(f, f)
        lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def _format_defects(defects: list[str], stage: str) -> str:
    """Format congenital defects section for prompts."""
    if not defects:
        return ""
    defect_list = ", ".join(defects)
    return (
        f"## Congenital Conditions (determined at conception)\n"
        f"This individual has: {defect_list}.\n"
        f"These conditions MUST affect {stage} development realistically. "
        f"Do not ignore them. They shape what this body can and cannot do."
    )


def _format_complications(defects: list[str], preterm: dict = None) -> str:
    """Format complications summary for birth stage."""
    parts = []
    if defects:
        parts.append(f"Congenital conditions: {', '.join(defects)}")
    if preterm and preterm.get("preterm"):
        parts.append(f"Preterm birth: {preterm.get('severity', 'unknown')} at {preterm.get('weeks', '?')} weeks")
    if not parts:
        return "No known complications."
    return "\n".join(parts)


def _get_stage_duration(species: str, stage: str, env: dict = None) -> int:
    """
    Get duration in days for a stage, with environment-driven variation.

    营养好/压力小 → 略微缩短（发育顺利）；营养差/压力大 → 略微延长。
    总妊娠天数在 ±10% 范围内波动（人类 252-308 天 vs 固定 280 天）。
    """
    base = STAGE_DURATIONS.get(species, STAGE_DURATIONS["human"]).get(stage, 14)
    if not env:
        return base

    # 环境修正：budget_multiplier 高 → 发育快 → 时长略短
    budget_mod = env.get("modifiers", {}).get("budget_multiplier", 1.0)
    # 反转：资源充足时缩短，匮乏时延长
    duration_factor = 1.0 + (1.0 - budget_mod) * 0.3  # ±10% 范围

    # 随机波动 ±5%
    import random
    jitter = random.uniform(0.95, 1.05)

    adjusted = round(base * duration_factor * jitter)
    # 至少 1 天，最多 base × 1.3
    return max(1, min(round(base * 1.3), adjusted))


# ============================================================
# Budget enforcement
# ============================================================

def _enforce_budget(parsed: dict, budget: int) -> dict:
    """
    Enforce resource budget on LLM output.

    If resource_allocation exists and total exceeds budget,
    scale down proportionally. No retries — just cut.
    """
    allocation = parsed.get("resource_allocation")
    if not allocation or not isinstance(allocation, dict):
        return parsed

    numeric = {k: v for k, v in allocation.items() if isinstance(v, (int, float))}
    if not numeric:
        return parsed

    total = sum(numeric.values())
    if total <= budget:
        parsed["budget_enforced"] = False
        return parsed

    scale = budget / total
    enforced = {k: round(v * scale) for k, v in numeric.items()}

    remainder = budget - sum(enforced.values())
    if remainder > 0:
        top_key = max(enforced, key=enforced.get)
        enforced[top_key] += remainder

    parsed["resource_allocation"] = enforced
    parsed["budget_enforced"] = True
    parsed["budget_original_total"] = total
    parsed["budget_scale_factor"] = round(scale, 3)
    return parsed


def _build_env_constraint(env: dict) -> str:
    """Build environment constraint text for stage prompts."""
    impact = environment_impact_text(env)
    if "Favorable" in impact:
        return ""
    return f"Environmental constraint: {impact}"


# ============================================================
# 分层约束注入辅助函数
# ============================================================

def _build_critical_alerts(
    nutrient_effects: dict, placenta_state: dict,
    immune_risks: dict, hormones: dict,
) -> str:
    """提取异常状态，生成 Critical Alerts 区块（置于 Output Spec 之前）。"""
    alerts = []

    # 营养素缺乏
    deficient = nutrient_effects.get("deficient_nutrients", [])
    if deficient:
        alerts.append(f"Nutrient deficiency: {', '.join(deficient)} — budget already penalized by code")

    # 胎盘并发症
    complications = placenta_state.get("complications", [])
    if complications:
        eff = placenta_state.get("efficiency", 1.0)
        alerts.append(f"Placental complication: {', '.join(complications)} (efficiency {eff:.0%})")

    # 免疫风险
    if immune_risks.get("defect_risk_boost", 1.0) > 1.0:
        infections = immune_risks.get("active_infections", [])
        if infections:
            alerts.append(f"Active immune risk: {', '.join(infections)}")

    # 激素异常
    cortisol = hormones.get("cortisol", 0)
    if cortisol > 0.5:
        alerts.append(f"Elevated cortisol ({cortisol:.2f}) — fetal stress response activated")
    t4 = hormones.get("thyroid_t4", 0.5)
    if t4 < 0.3:
        alerts.append(f"Low thyroid T4 ({t4:.2f}) — neural development constrained")

    if not alerts:
        return ""

    lines = ["## ⚠ Critical Constraints (code-enforced, already reflected in budget)"]
    for a in alerts:
        lines.append(f"- {a}")
    lines.append("Your output MUST reflect these constraints in biological narrative.")
    return "\n".join(lines)


def _build_reference_status(
    nutrients: dict, stage_name: str,
    placenta_state: dict, immunity: dict,
    hormones: dict, stage_idx: int,
    methylation: dict = None, env: dict = None,
) -> str:
    """生成 Reference Status 区块（正常范围数据，置于 prompt 末尾）。"""
    sections = []

    # 营养素
    nutrients_text = format_nutrients_for_prompt(nutrients, stage_name)
    if nutrients_text:
        sections.append(nutrients_text)

    # 胎盘
    placenta_text = format_placenta_for_prompt(placenta_state, stage_name)
    if placenta_text:
        sections.append(placenta_text)

    # 免疫
    immunity_text = format_immunity_for_prompt(immunity, stage_name)
    if immunity_text:
        sections.append(immunity_text)

    # 激素
    hormones_text = format_hormones_for_prompt(hormones, stage_name)
    if hormones_text:
        sections.append(hormones_text)

    # 表观遗传（仅 zygote）
    if stage_idx == 0 and methylation:
        epi_text = format_epigenetics_for_prompt(methylation, env or {})
        if epi_text:
            sections.append(epi_text)

    if not sections:
        return ""

    return "\n\n".join(sections)


# ============================================================
# 跨阶段一致性校验
# ============================================================

def _rule_maternal_response(stage_name: str, env: dict) -> dict:
    """规则引擎替代 LLM 母体反馈（fast/turbo 模式）。

    优先从 templates/maternal/*.json 采样 4 个字段；模板库缺失时降级到硬编码档位句。
    budget 调整仍由 compute_budget_delta 独立计算。
    """
    stress = env.get("stress_level", 0.3)
    nutrition = env.get("nutrition_access", 0.7)

    # 分档
    if stress > 0.6:
        stress_tier = "high"
    elif stress > 0.3:
        stress_tier = "moderate"
    else:
        stress_tier = "low"

    if nutrition < 0.4:
        nutrition_tier = "poor"
    elif nutrition < 0.7:
        nutrition_tier = "moderate"
    else:
        nutrition_tier = "good"

    # 降级句（模板库缺失时用）
    FALLBACK = {
        "hormonal_shift": {
            "high": "elevated cortisol, reduced progesterone",
            "moderate": "mildly elevated cortisol",
            "low": "stable hormonal balance",
        },
        "physical_adaptation": {
            "high": "increased uterine tension, reduced blood flow",
            "moderate": "normal progression with occasional tension",
            "low": "normal uterine environment",
        },
        "stress_response": {
            "high": "fight-or-flight activated, fetal exposure elevated",
            "moderate": "managed but present",
            "low": "well-managed, minimal fetal exposure",
        },
        "nutrient_redistribution": {
            "poor": "compromised — deficiencies affecting fetal supply",
            "moderate": "adequate with minor gaps",
            "good": "well-supplied, optimal distribution",
        },
    }

    # 模板库采样（通过 rule_engine._sample_template 复用）
    try:
        from .rule_engine import _sample_template as _st
    except Exception:
        _st = None

    def _sample(field: str, tier: str, filter_key: str) -> str:
        if field == "nutrient_redistribution":
            key = f"maternal/nutrient_redistribution_nutrition_{tier}"
            filters = {"nutrition_tier": tier}
        else:
            key = f"maternal/{field}_stress_{tier}"
            filters = {"stress_tier": tier}
        if _st is not None:
            return _st(key, FALLBACK[field][tier], filters=filters)
        return FALLBACK[field][tier]

    return {
        "hormonal_shift": _sample("hormonal_shift", stress_tier, "stress_tier"),
        "physical_adaptation": _sample("physical_adaptation", stress_tier, "stress_tier"),
        "nutrient_redistribution": _sample("nutrient_redistribution", nutrition_tier, "nutrition_tier"),
        "stress_response": _sample("stress_response", stress_tier, "stress_tier"),
    }


def _get_maternal_response(
    species: str, stage_name: str, stage_result: str,
    environment: dict, client, model: str, provider: str,
) -> dict:
    """LLM 生成母体反馈叙事（保留个体差异）。budget 调整由 compute_budget_delta 独立计算。"""
    blueprint = _load_blueprint(species)
    display_name = blueprint.get("display_name", species)
    env_text = format_environment(environment) if environment else "Not specified"

    prompt = MATERNAL_RESPONSE_PROMPT.format(
        display_name=display_name,
        environment=env_text,
        stage_name=stage_name,
        stage_result=stage_result,
    )

    try:
        raw = _call_llm(prompt, client, model, provider)
        return _parse_json(raw)
    except Exception as e:
        import logging
        logging.getLogger("womb").warning("母体反馈 LLM 调用失败 (%s): %s", stage_name, e)
        return {
            "hormonal_shift": "maternal response unavailable",
            "physical_adaptation": "maternal response unavailable",
            "nutrient_redistribution": "maternal response unavailable",
            "stress_response": "maternal response unavailable",
        }


def _validate_cross_stage(stage_name: str, parsed: dict, stage_results: list[str]) -> dict:
    """
    跨阶段一致性校验：检查当前输出是否与前阶段一致。
    不重试 LLM——只在 parsed 中添加 _consistency_warnings 字段。
    """
    import logging
    logger = logging.getLogger("womb")
    warnings = []

    if not isinstance(parsed, dict):
        return parsed

    # Late Organogenesis: primary_sense 应与 Early Organogenesis 的 top sensory resource 一致
    if stage_name == "late_organogenesis" and len(stage_results) >= 2:
        try:
            early_org = _parse_json(stage_results[1])
            if isinstance(early_org, dict):
                precursors = early_org.get("sensory_precursors", "")
                primary = parsed.get("primary_sense", "").lower()
                # 启发式检查：early_org 的 top precursor 是否出现在 late 的 primary_sense 中
                if precursors and primary:
                    for sense in ("visual", "auditory", "tactile", "olfactory"):
                        if sense in precursors.lower()[:50] and sense not in primary[:50]:
                            warnings.append(
                                f"primary_sense '{primary[:30]}...' may not match "
                                f"early organogenesis top precursor (starts with '{precursors[:30]}...')"
                            )
                            break
        except Exception:
            pass

    # Late Neural: myelination 应与 Early Neural 的 synapse density 一致
    if stage_name == "late_neural" and len(stage_results) >= 4:
        try:
            early_neural = _parse_json(stage_results[3])
            if isinstance(early_neural, dict):
                synapses = early_neural.get("synapse_density_pattern", "").lower()
                myelin = parsed.get("myelination_priority", "").lower()
                if synapses and myelin:
                    # 检查 synapse 的 "highest density" 区域是否出现在 myelination 中
                    for sense in ("visual", "auditory", "tactile", "somatosensory", "motor"):
                        if "highest" in synapses and sense in synapses.split("highest")[0][-50:]:
                            if sense not in myelin[:80]:
                                warnings.append(
                                    f"myelination_priority may not match early neural "
                                    f"highest synapse density area (expected '{sense}')"
                                )
                            break
        except Exception:
            pass

    if warnings:
        parsed["_consistency_warnings"] = warnings
        for w in warnings:
            logger.warning("跨阶段一致性: %s — %s", stage_name, w)

    return parsed


# ============================================================
# Prompt building
# ============================================================

def build_stage_prompts(
    species: str, sex: str, phenotype: dict,
    stage_results: list[str],
    environment: dict = None,
    defects: list[str] = None,
    preterm: dict = None,
    offspring_count: int = 1,
    birth_order: int = 0,
    genotype: dict = None,
) -> list[tuple[str, str, int]]:
    """Build prompts for 7-stage development. Returns (stage_name, prompt, budget)."""
    blueprint = _load_blueprint(species)
    display_name = blueprint.get("display_name", species)
    sex_display = SEX_DISPLAY.get(sex, sex)
    phenotype_display = _format_phenotype(phenotype)
    env = environment or {}
    env_text = format_environment(env) if env else "Not specified"
    env_impact = environment_impact_text(env) if env else ""
    env_constraint = _build_env_constraint(env) if env else ""
    defects = defects or []

    multi_note = ""
    if offspring_count > 1:
        multi_note = (f"This is offspring #{birth_order + 1} of {offspring_count}. "
                      f"Resources are shared — budget is reduced. "
                      f"Earlier-developing siblings consumed resources first.")

    def _budget(stage: str) -> int:
        return get_effective_budget(RESOURCE_BUDGET[stage], env, offspring_count)

    def _budget_ctx(stage: str) -> str:
        base = RESOURCE_BUDGET[stage]
        effective = _budget(stage)
        if effective == base:
            return "full allocation"
        return f"reduced from {base} base — environment {env.get('modifiers', {}).get('budget_multiplier', 1.0):.0%}, offspring share"

    def _prev(n: int) -> str:
        parts = []
        for j in range(min(n, len(stage_results))):
            parts.append(f"### {STAGE_NAMES[j]}\n{stage_results[j]}")
        return "\n\n".join(parts)

    # 遗传基因型注入
    genetics_text = ""
    if genotype:
        from .heredity import genotype_to_phenotype as _gtp
        _pheno = _gtp(genotype, species)
        genetics_text = format_genetics_for_prompt(genotype, _pheno)

    prompts = []

    # Stage 1: Zygote
    b = _budget("zygote")
    p = STAGE_1_ZYGOTE.format(
        display_name=display_name,
        species_profile=_format_blueprint(blueprint),
        sex_display=sex_display, phenotype_display=phenotype_display,
        environment=env_text, env_impact=env_impact,
        defects_section=_format_defects(defects, "foundational"),
        budget=b,
    )
    if genetics_text:
        p += "\n\n" + genetics_text
    prompts.append(("zygote", p, b))
    if len(stage_results) < 1: return prompts

    # Stage 2: Early Organogenesis
    b = _budget("early_organogenesis")
    p = STAGE_2A_EARLY_ORGANOGENESIS.format(
        display_name=display_name,
        species_mental=_format_section(blueprint, "mental", "Mental Traits"),
        species_physical_senses=_format_section(blueprint, "physical", "Physical Traits"),
        prev_results=_prev(1), environment=env_text,
        defects_section=_format_defects(defects, "early organ"),
        budget=b, budget_context=_budget_ctx("early_organogenesis"),
        multi_fetus_note=multi_note, env_constraint=env_constraint,
    )
    prompts.append(("early_organogenesis", p, b))
    if len(stage_results) < 2: return prompts

    # Stage 3: Late Organogenesis
    b = _budget("late_organogenesis")
    p = STAGE_2B_LATE_ORGANOGENESIS.format(
        display_name=display_name,
        species_mental=_format_section(blueprint, "mental", "Mental Traits"),
        species_physical_senses=_format_section(blueprint, "physical", "Physical Traits"),
        prev_results=_prev(2), environment=env_text,
        defects_section=_format_defects(defects, "organ maturation"),
        budget=b, budget_context=_budget_ctx("late_organogenesis"),
        env_constraint=env_constraint,
    )
    prompts.append(("late_organogenesis", p, b))
    if len(stage_results) < 3: return prompts

    # Stage 4: Early Neural
    b = _budget("early_neural")
    p = STAGE_3A_EARLY_NEURAL.format(
        display_name=display_name,
        species_behavior=_format_section(blueprint, "behavior", "Behavior"),
        species_development=_format_section(blueprint, "development", "Development"),
        prev_results=_prev(3), environment=env_text,
        defects_section=_format_defects(defects, "early neural"),
        budget=b, budget_context=_budget_ctx("early_neural"),
        env_constraint=env_constraint,
    )
    prompts.append(("early_neural", p, b))
    if len(stage_results) < 4: return prompts

    # Stage 5: Late Neural
    b = _budget("late_neural")
    p = STAGE_3B_LATE_NEURAL.format(
        display_name=display_name,
        species_behavior=_format_section(blueprint, "behavior", "Behavior"),
        species_development=_format_section(blueprint, "development", "Development"),
        prev_results=_prev(4), environment=env_text,
        defects_section=_format_defects(defects, "late neural"),
        budget=b, budget_context=_budget_ctx("late_neural"),
        env_constraint=env_constraint,
    )
    prompts.append(("late_neural", p, b))
    if len(stage_results) < 5: return prompts

    # Stage 6: Fetal Movement
    b = _budget("fetal_movement")
    p = STAGE_4_FETAL_MOVEMENT.format(
        display_name=display_name,
        species_ecology=_format_section(blueprint, "ecology", "Ecology"),
        species_physiology=_format_section(blueprint, "physiology", "Physiology & Biochemistry"),
        stage1_result=stage_results[0], stage2_result=stage_results[2],
        stage3_result=stage_results[4],
        environment=env_text,
        defects_section=_format_defects(defects, "behavioral"),
        budget=b, env_constraint=env_constraint,
    )
    prompts.append(("fetal_movement", p, b))
    if len(stage_results) < 6: return prompts

    # Stage 7: Birth — 只注入 race/breed 摘要，详细基因型已被前 4 阶段消化
    cry = blueprint["womb"]["cry"]
    birth_summary = ""
    for f in ("race", "breed"):
        if f in phenotype:
            label = {"race": "Race", "breed": "Breed"}[f]
            birth_summary += f"- {label}: {phenotype[f]}\n"
    p = STAGE_5_BIRTH.format(
        display_name=display_name,
        stage1_result=stage_results[0], stage2_result=stage_results[2],
        stage3_result=stage_results[4], stage4_result=stage_results[5],
        sex_display=sex_display, phenotype_summary=birth_summary.rstrip(),
        environment=env_text,
        complications_summary=_format_complications(defects, preterm),
        cry=cry,
    )
    prompts.append(("birth", p, RESOURCE_BUDGET["birth"]))

    return prompts


# ============================================================
# Seven-stage development
# ============================================================

def express(
    species: str, sex: str, phenotype: dict,
    environment: dict = None, defects: list[str] = None,
    offspring_count: int = 1, birth_order: int = 0,
    provider: str = "deepseek", model: str | None = None,
    genotype: dict = None,
    defects_full: list[dict] = None,
) -> dict:
    """
    7 阶段发育表达，集成：
    1. 资源预算执法（代码层）
    2. 母体反馈环（数值化，真正修改 budget_multiplier）
    3. 动态环境（阶段间概率触发变化事件）
    4. 营养素阶段敏感性（缺乏营养素在敏感阶段额外惩罚 budget）
    5. 致畸时间窗口（毒素在不同阶段风险倍数不同）

    No retries. Parse failure = development failure.
    """
    client = _create_client(provider)
    if model is None:
        model = _get_model(provider)

    stage_results: list[str] = []
    gestation_log: list[dict] = []
    maternal_states: list[dict] = []
    gestation_day = 0
    env = dict(environment) if environment else {}
    _defects_full = defects_full or []

    for i in range(7):
        stage_name = STAGE_NAMES[i]
        duration = _get_stage_duration(species, stage_name, env)

        # --- 动态环境（概率按速率调整）---
        env_event = None
        if i > 0:
            from config import get_time_scale as _gts
            _env_prob = {"slow": 0.20, "normal": 0.20, "fast": 0.10, "turbo": 0.0}.get(_gts(), 0.20)
            if _env_prob > 0:
                env, env_event = roll_env_change(env, probability=_env_prob)

        # --- 胎盘更新 ---
        placenta_state = env.get("placenta", {})
        defect_risk_mod = env.get("modifiers", {}).get("defect_risk_multiplier", 1.0)
        placenta_state = update_placenta(placenta_state, stage_name, env_risk_modifier=defect_risk_mod)
        env["placenta"] = placenta_state
        placenta_factor = get_placenta_budget_factor(placenta_state)

        # --- 免疫风险 ---
        immune_risks = get_immune_risk_modifiers(env.get("immunity", {}), stage_name)

        # --- 营养素阶段效应 ---
        nutrient_effects = get_stage_nutrient_effects(env.get("nutrients", {}), stage_name)

        # --- 致畸时间窗口 ---
        teratogen_risk = get_teratogen_risk(env.get("toxin_types", []), stage_name)

        # --- 激素计算 ---
        hormones = compute_hormones(stage_name, env, sex=sex, complications=defects)
        hormone_effects = get_hormone_effects(hormones)

        # --- 生命体征 ---
        vitals = compute_vitals(stage_name, env, hormones=hormones, complications=defects)

        # --- 逐阶段流产检查（Stage 1-6，birth 由 stillbirth 处理）---
        if i < 6:
            miscarriage_result = roll_stage_miscarriage(
                species, stage_name, env, _defects_full,
                placenta_state, hormones, immune_risks,
                nutrient_effects, teratogen_risk,
            )
            if miscarriage_result["miscarriage"]:
                gestation_day += duration
                gestation_log.append({
                    "stage": stage_name, "gestation_day": gestation_day,
                    "duration_days": duration, "response": None,
                    "miscarriage": miscarriage_result,
                })
                return {
                    "miscarriage": True,
                    "miscarriage_stage": stage_name,
                    "miscarriage_cause": miscarriage_result.get("cause", "unknown"),
                    "gestation_log": gestation_log,
                    "total_gestation_days": gestation_day,
                }

        # 构建 prompt
        prompts = build_stage_prompts(
            species, sex, phenotype, stage_results,
            environment=env, defects=defects,
            offspring_count=offspring_count, birth_order=birth_order,
            genotype=genotype,
        )
        _, prompt, budget = prompts[i]

        # 胎盘效率 budget 修正
        budget = max(1, round(budget * placenta_factor))

        # 营养素 budget 惩罚
        if nutrient_effects["budget_penalty"] > 0:
            budget = max(1, round(budget * (1.0 - nutrient_effects["budget_penalty"])))

        # 激素 budget 惩罚
        if hormone_effects["budget_penalty"] > 0:
            budget = max(1, round(budget * (1.0 - hormone_effects["budget_penalty"])))

        # 分层约束注入：Critical Alerts 在 Output Spec 之前
        critical = _build_critical_alerts(nutrient_effects, placenta_state, immune_risks, hormones)
        if critical:
            # 在 "Return ONLY" 之前插入 critical alerts
            return_idx = prompt.rfind("Return ONLY")
            if return_idx > 0:
                # 找到 Return ONLY 前面的 Note: 行，在 Note 之前插入
                note_idx = prompt.rfind("Note: Budget above", 0, return_idx)
                insert_idx = note_idx if note_idx > 0 else return_idx
                prompt = prompt[:insert_idx] + critical + "\n\n" + prompt[insert_idx:]

        # 致畸信息（仍然平铺，因为致畸本身就是 critical）
        teratogen_text = format_teratogen_for_prompt(env.get("toxin_types", []), stage_name)
        if teratogen_text:
            prompt += "\n\n" + teratogen_text

        # Reference Status（正常范围数据，置于末尾）
        methylation = phenotype.get("_methylation_profile", {})
        ref_status = _build_reference_status(
            env.get("nutrients", {}), stage_name,
            placenta_state, env.get("immunity", {}),
            hormones, i, methylation if i == 0 else None, env,
        )
        if ref_status:
            prompt += "\n\n" + ref_status

        # 母体反馈文本注入
        if maternal_states:
            prompt += "\n\n## Latest Maternal Feedback\n"
            prompt += json.dumps(maternal_states[-1], ensure_ascii=False, indent=2) + "\n"

        # 规则引擎：按速率决定是否跳过 LLM
        # turbo: 7 阶段全规则（template-based, 零 LLM）
        from config import get_time_scale as _gts_sync
        _RULE_STAGES_SYNC: dict[str, set[str]] = {
            "slow":   set(),
            "normal": set(),
            "fast":   {"zygote", "early_organogenesis", "birth"},
            "turbo":  {"zygote", "early_organogenesis", "late_organogenesis",
                       "early_neural", "late_neural", "fetal_movement", "birth"},
        }
        _use_rule = stage_name in _RULE_STAGES_SYNC.get(_gts_sync(), set())

        if _use_rule:
            from .rule_engine import (
                rule_zygote, rule_early_organogenesis, rule_late_organogenesis,
                rule_early_neural, rule_late_neural, rule_fetal_movement, rule_birth,
            )
            if stage_name == "zygote":
                parsed = rule_zygote(budget, env, genotype or {})
            elif stage_name == "early_organogenesis":
                prev_resp = _parse_json(stage_results[-1]) if stage_results else {}
                if not isinstance(prev_resp, dict):
                    prev_resp = {}
                parsed = rule_early_organogenesis(budget, prev_resp, env)
            elif stage_name == "late_organogenesis":
                parsed = rule_late_organogenesis(budget, stage_results, env, defects or [])
            elif stage_name == "early_neural":
                parsed = rule_early_neural(budget, stage_results, env, defects or [])
            elif stage_name == "late_neural":
                parsed = rule_late_neural(budget, stage_results, env, defects or [])
            elif stage_name == "fetal_movement":
                _arousal = "moderate"
                for sr in stage_results:
                    try:
                        _p = _parse_json(sr) if isinstance(sr, str) else sr
                        if isinstance(_p, dict) and "arousal_baseline" in _p:
                            _arousal = _p["arousal_baseline"]
                    except Exception:
                        pass
                parsed = rule_fetal_movement(budget, stage_results, env, _arousal)
            elif stage_name == "birth":
                parsed = rule_birth(stage_results, genotype or {})
            raw = json.dumps(parsed, ensure_ascii=False)
            stage_results.append(raw)
            logger.info("规则引擎(sync): stage=%s, time_scale=%s", stage_name, _gts_sync())
        else:
            try:
                raw = _call_llm(prompt, client, model, provider)
            except Exception as e:
                raise RuntimeError(f"Stage {i+1} ({stage_name}) LLM call failed: {e}") from e
            stage_results.append(raw)
            try:
                parsed = _parse_json(raw)
            except (json.JSONDecodeError, IndexError):
                parsed = raw

        # 代码层执法
        if isinstance(parsed, dict):
            if stage_name in RESOURCE_BUDGET:
                parsed = _enforce_budget(parsed, budget)
                parsed = validate_resource_semantics(parsed, budget)
            parsed = validate_defect_consistency(parsed, defects or [])
            if not _use_rule:
                parsed = _validate_cross_stage(stage_name, parsed, stage_results)

        gestation_day += duration
        gestation_log.append({
            "stage": stage_name,
            "gestation_day": gestation_day,
            "duration_days": duration,
            "response": parsed,
            "maternal_feedback": maternal_states[-1] if maternal_states else None,
            "env_snapshot": {k: v for k, v in env.items() if k != "env_history"},
            "env_event": env_event,
            "nutrient_effects": nutrient_effects,
            "teratogen_risk": teratogen_risk,
            "placenta": dict(placenta_state),
            "immune_risks": immune_risks,
            "hormones": hormones,
            "hormone_effects": hormone_effects,
            "vitals": vitals,
        })

        # 母体反馈——出生阶段跳过；按速率分级决定 LLM 还是规则
        if i < 6:
            from config import get_time_scale as _gts
            _ts_sync = _gts()
            _MATERNAL_RULE_SYNC: dict[str, set[str]] = {
                "slow":   set(),
                "normal": set(),
                "fast":   {"early_organogenesis", "early_neural", "fetal_movement"},
                "turbo":  {"zygote", "early_organogenesis", "early_neural",
                           "late_organogenesis", "late_neural", "fetal_movement"},
            }
            if stage_name in _MATERNAL_RULE_SYNC.get(_ts_sync, set()):
                maternal_response = _rule_maternal_response(stage_name, env)
            else:
                maternal_response = _get_maternal_response(
                    species, stage_name, raw, env, client, model, provider,
                )
            maternal_states.append(maternal_response)

            budget_delta = compute_budget_delta(
                hormones, placenta_state, nutrient_effects, immune_risks, env,
            )
            env, feedback_record = apply_maternal_feedback(env, budget_delta)
            if feedback_record:
                gestation_log[-1]["feedback_applied"] = feedback_record

    # 解析最终阶段
    final_raw = stage_results[-1]
    try:
        result = _parse_json(final_raw)
    except (json.JSONDecodeError, IndexError) as e:
        raise RuntimeError(f"Birth stage parse failed: {final_raw}") from e

    if "tendencies" not in result or "first_cry" not in result:
        raise RuntimeError(f"Birth stage missing fields: {result}")

    result["gestation_log"] = gestation_log
    result["total_gestation_days"] = gestation_day
    return result


def express_stream(
    species: str, sex: str, phenotype: dict,
    environment: dict = None, defects: list[str] = None,
    offspring_count: int = 1, birth_order: int = 0,
    provider: str = "deepseek", model: str | None = None,
    genotype: dict = None,
    defects_full: list[dict] = None,
):
    """7 阶段发育 SSE 生成器，集成动态环境/营养素/致畸窗口/母体反馈数值化。"""
    client = _create_client(provider)
    if model is None:
        model = _get_model(provider)

    stage_results: list[str] = []
    gestation_log: list[dict] = []
    maternal_states: list[dict] = []
    gestation_day = 0
    env = dict(environment) if environment else {}
    _defects_full = defects_full or []

    for i in range(7):
        stage_name = STAGE_NAMES[i]
        duration = _get_stage_duration(species, stage_name, env)
        gestation_day += duration

        # --- 动态环境（概率按速率调整）---
        env_event = None
        if i > 0:
            from config import get_time_scale as _gts
            _env_prob = {"slow": 0.20, "normal": 0.20, "fast": 0.10, "turbo": 0.0}.get(_gts(), 0.20)
            if _env_prob > 0:
                env, env_event = roll_env_change(env, probability=_env_prob)
            if env_event:
                yield {"stage": stage_name, "status": "env_change", "stage_num": i + 1, "event": env_event}

        # --- 胎盘更新 ---
        placenta_state = env.get("placenta", {})
        defect_risk_mod = env.get("modifiers", {}).get("defect_risk_multiplier", 1.0)
        placenta_state = update_placenta(placenta_state, stage_name, env_risk_modifier=defect_risk_mod)
        env["placenta"] = placenta_state
        placenta_factor = get_placenta_budget_factor(placenta_state)

        # --- 免疫风险 ---
        immune_risks = get_immune_risk_modifiers(env.get("immunity", {}), stage_name)

        # --- 营养素 + 致畸 ---
        nutrient_effects = get_stage_nutrient_effects(env.get("nutrients", {}), stage_name)
        teratogen_risk = get_teratogen_risk(env.get("toxin_types", []), stage_name)

        # --- 激素 ---
        hormones = compute_hormones(stage_name, env, sex=sex, complications=defects)
        hormone_effects = get_hormone_effects(hormones)

        # --- 生命体征 ---
        vitals = compute_vitals(stage_name, env, hormones=hormones, complications=defects)
        vitals_display = format_vitals_for_display(vitals, stage_name)

        # --- 逐阶段流产检查（Stage 1-6）---
        if i < 6:
            miscarriage_result = roll_stage_miscarriage(
                species, stage_name, env, _defects_full,
                placenta_state, hormones, immune_risks,
                nutrient_effects, teratogen_risk,
            )
            if miscarriage_result["miscarriage"]:
                yield {
                    "stage": stage_name, "status": "miscarriage",
                    "stage_num": i + 1,
                    "cause": miscarriage_result.get("cause", "unknown"),
                    "base_rate": miscarriage_result.get("base_rate"),
                    "adjusted_rate": miscarriage_result.get("adjusted_rate"),
                    "gestation_day": gestation_day,
                }
                # 图谱流产 delta：终止边 + baby status 更新
                yield {
                    "stage": stage_name, "status": "graph_delta", "stage_num": i + 1,
                    "phase": "miscarriage",
                    "graph_delta": graph_story.build_miscarriage_delta(
                        stage_num=i + 1,
                        cause=miscarriage_result.get("cause", "unknown"),
                    ),
                }
                return

        # 逐个推送阶段计算数据（LLM 调用前，让前端有内容展示）
        yield {
            "stage": stage_name, "status": "in_progress", "stage_num": i + 1,
            "gestation_day": gestation_day, "duration_days": duration,
            "total_stages": 7,
        }
        yield {
            "stage": stage_name, "status": "vitals", "stage_num": i + 1,
            "vitals": vitals_display,
        }
        yield {
            "stage": stage_name, "status": "hormones", "stage_num": i + 1,
            "hormones": hormones,
            "hormone_effects": hormone_effects,
        }
        yield {
            "stage": stage_name, "status": "nutrients", "stage_num": i + 1,
            "nutrient_effects": nutrient_effects,
            "teratogen_risk": teratogen_risk,
        }
        yield {
            "stage": stage_name, "status": "placenta", "stage_num": i + 1,
            "placenta_efficiency": placenta_state.get("efficiency"),
            "placenta_state": {k: v for k, v in placenta_state.items()
                               if k != "history"},
        }
        if immune_risks:
            yield {
                "stage": stage_name, "status": "immunity", "stage_num": i + 1,
                "immune_risks": immune_risks,
            }
        yield {
            "stage": stage_name, "status": "developing", "stage_num": i + 1,
            "message": f"Developing ({STAGE_DISPLAY.get(stage_name, stage_name)})...",
        }

        # 图谱阶段 delta：激素/营养/毒素/体征/器官发育/反射/气质
        # 兜底 try/except：图谱 emit 失败不能拖死整个 SSE 流
        try:
            stage_delta = graph_story.build_stage_delta(
                stage_name=stage_name, stage_num=i + 1,
                hormones=hormones, hormone_effects=hormone_effects,
                nutrient_effects=nutrient_effects,
                env_nutrients=env.get("nutrients") or {},
                teratogen_risk=teratogen_risk,
                toxin_types=env.get("toxin_types") or [],
                vitals=vitals,
            )
            yield {
                "stage": stage_name, "status": "graph_delta", "stage_num": i + 1,
                "phase": "stage", "graph_delta": stage_delta,
            }
        except Exception as gerr:
            logger.error(f"graph_delta build failed for stage {stage_name}: {gerr}", exc_info=True)
            yield {
                "stage": stage_name, "status": "graph_delta", "stage_num": i + 1,
                "phase": "stage", "graph_delta": {}, "error": str(gerr),
            }

        prompts = build_stage_prompts(
            species, sex, phenotype, stage_results,
            environment=env, defects=defects,
            offspring_count=offspring_count, birth_order=birth_order,
            genotype=genotype,
        )
        _, prompt, budget = prompts[i]

        # 胎盘效率 budget 修正
        budget = max(1, round(budget * placenta_factor))

        # 营养素 budget 惩罚
        if nutrient_effects["budget_penalty"] > 0:
            budget = max(1, round(budget * (1.0 - nutrient_effects["budget_penalty"])))

        # 激素 budget 惩罚
        if hormone_effects["budget_penalty"] > 0:
            budget = max(1, round(budget * (1.0 - hormone_effects["budget_penalty"])))

        # 分层约束注入：Critical Alerts 在 Output Spec 之前
        critical = _build_critical_alerts(nutrient_effects, placenta_state, immune_risks, hormones)
        if critical:
            # 在 "Return ONLY" 之前插入 critical alerts
            return_idx = prompt.rfind("Return ONLY")
            if return_idx > 0:
                note_idx = prompt.rfind("Note: Budget above", 0, return_idx)
                insert_idx = note_idx if note_idx > 0 else return_idx
                prompt = prompt[:insert_idx] + critical + "\n\n" + prompt[insert_idx:]

        # 致畸信息（仍然平铺，因为致畸本身就是 critical）
        teratogen_text = format_teratogen_for_prompt(env.get("toxin_types", []), stage_name)
        if teratogen_text:
            prompt += "\n\n" + teratogen_text

        # Reference Status（正常范围数据，置于末尾）
        methylation = phenotype.get("_methylation_profile", {})
        ref_status = _build_reference_status(
            env.get("nutrients", {}), stage_name,
            placenta_state, env.get("immunity", {}),
            hormones, i, methylation if i == 0 else None, env,
        )
        if ref_status:
            prompt += "\n\n" + ref_status

        # 母体反馈文本注入
        if maternal_states:
            prompt += "\n\n## Latest Maternal Feedback\n"
            prompt += json.dumps(maternal_states[-1], ensure_ascii=False, indent=2) + "\n"

        # ── 子宫规则引擎：按速率决定哪些阶段用规则替代 LLM ──
        #   slow/normal：全部 LLM（完整体验）
        #   fast：跳过 3 个纯资源分配/叙事阶段（Stage 1, 2A, 5）
        #   turbo：7 阶段全规则（template-based，零 LLM）
        from config import get_time_scale as _gts_stage
        _RULE_STAGES_BY_SPEED: dict[str, set[str]] = {
            "slow":   set(),
            "normal": set(),
            "fast":   {"zygote", "early_organogenesis", "birth"},
            "turbo":  {"zygote", "early_organogenesis", "late_organogenesis",
                       "early_neural", "late_neural", "fetal_movement", "birth"},
        }
        _use_rule_engine = stage_name in _RULE_STAGES_BY_SPEED.get(_gts_stage(), set())

        if _use_rule_engine:
            from .rule_engine import (
                rule_zygote, rule_early_organogenesis, rule_late_organogenesis,
                rule_early_neural, rule_late_neural, rule_fetal_movement, rule_birth,
            )
            if stage_name == "zygote":
                parsed = rule_zygote(budget, env, genotype or {})
            elif stage_name == "early_organogenesis":
                prev_resp = _parse_json(stage_results[-1]) if stage_results else {}
                if not isinstance(prev_resp, dict):
                    prev_resp = {}
                parsed = rule_early_organogenesis(budget, prev_resp, env)
            elif stage_name == "late_organogenesis":
                parsed = rule_late_organogenesis(budget, stage_results, env, defects or [])
            elif stage_name == "early_neural":
                parsed = rule_early_neural(budget, stage_results, env, defects or [])
            elif stage_name == "late_neural":
                parsed = rule_late_neural(budget, stage_results, env, defects or [])
            elif stage_name == "fetal_movement":
                # 从 late_neural 结果提取 arousal_baseline
                _arousal = "moderate"
                for sr in stage_results:
                    try:
                        _p = _parse_json(sr) if isinstance(sr, str) else sr
                        if isinstance(_p, dict) and "arousal_baseline" in _p:
                            _arousal = _p["arousal_baseline"]
                    except Exception:
                        pass
                parsed = rule_fetal_movement(budget, stage_results, env, _arousal)
            elif stage_name == "birth":
                parsed = rule_birth(stage_results, genotype or {})

            raw = json.dumps(parsed, ensure_ascii=False)
            stage_results.append(raw)
            logger.info("规则引擎: stage=%s, time_scale=%s (跳过 LLM)", stage_name, _gts_stage())
            yield {
                "stage": stage_name, "status": "rule_engine",
                "stage_num": i + 1,
            }
        else:
            # LLM 调用放到线程，主线程每秒 yield 进度心跳；失败时指数退避重试，
            # 仅在全部重试都失败后才终止 gestation。
            raw = None
            _last_error: Exception | None = None
            _max_attempts = 3
            for _attempt in range(1, _max_attempts + 1):
                _executor = ThreadPoolExecutor(max_workers=1)
                _future = _executor.submit(_call_llm, prompt, client, model, provider)
                _elapsed = 0
                try:
                    while not _future.done():
                        _time.sleep(1)
                        _elapsed += 1
                        yield {
                            "stage": stage_name, "status": "thinking",
                            "stage_num": i + 1, "elapsed": _elapsed,
                            "attempt": _attempt,
                        }
                    raw = _future.result()
                    _last_error = None
                    break
                except Exception as e:
                    _last_error = e
                    yield {
                        "stage": stage_name, "status": "retrying",
                        "stage_num": i + 1, "attempt": _attempt,
                        "max_attempts": _max_attempts, "error": str(e),
                    }
                finally:
                    _executor.shutdown(wait=False)
                if _attempt < _max_attempts:
                    _time.sleep(2 ** (_attempt - 1))  # 1s, 2s 指数退避

            if _last_error is not None or raw is None:
                yield {
                    "stage": stage_name, "status": "failed",
                    "error": f"LLM failed after {_max_attempts} attempts: {_last_error}",
                }
                return

            stage_results.append(raw)

        # 规则引擎已经产出 dict，跳过 JSON 解析
        if not _use_rule_engine:
            try:
                parsed = _parse_json(raw)
            except (json.JSONDecodeError, IndexError):
                parsed = raw

        budget_enforced = False
        if isinstance(parsed, dict):
            if stage_name in RESOURCE_BUDGET:
                parsed = _enforce_budget(parsed, budget)
                parsed = validate_resource_semantics(parsed, budget)
                budget_enforced = parsed.get("budget_enforced", False)
            parsed = validate_defect_consistency(parsed, defects or [])
            if not _use_rule_engine:
                parsed = _validate_cross_stage(stage_name, parsed, stage_results)

        gestation_log.append({
            "stage": stage_name,
            "gestation_day": gestation_day,
            "duration_days": duration,
            "response": parsed,
            "maternal_feedback": maternal_states[-1] if maternal_states else None,
            "env_snapshot": {k: v for k, v in env.items() if k != "env_history"},
            "env_event": env_event,
            "nutrient_effects": nutrient_effects,
            "teratogen_risk": teratogen_risk,
            "placenta": dict(placenta_state),
            "immune_risks": immune_risks,
            "hormones": hormones,
            "hormone_effects": hormone_effects,
            "vitals": vitals,
        })

        yield {
            "stage": stage_name, "status": "done", "stage_num": i + 1,
            "gestation_day": gestation_day,
            "response": parsed,
            "budget_enforced": budget_enforced,
        }

        # 补一条 narrative graph_delta: LLM 产出的叙事摘要作为 fate_birth 组节点
        try:
            narrative_text = None
            if isinstance(parsed, dict):
                # 候选字段：按优先级尝试
                for key in ("prose", "narrative", "maternal_prose", "description",
                            "first_cry", "summary"):
                    v = parsed.get(key)
                    if isinstance(v, str) and len(v.strip()) >= 15:
                        narrative_text = v.strip()
                        break
                # 回退：取第一个长字符串值
                if not narrative_text:
                    for v in parsed.values():
                        if isinstance(v, str) and len(v.strip()) >= 30:
                            narrative_text = v.strip()
                            break
            if narrative_text:
                narr_delta = graph_story.build_narrative_delta(i + 1, narrative_text)
                if narr_delta:
                    yield {
                        "stage": stage_name, "status": "graph_delta", "stage_num": i + 1,
                        "phase": "narrative", "graph_delta": narr_delta,
                    }
        except Exception as gerr:
            logger.error(f"narrative graph_delta failed for stage {stage_name}: {gerr}")

        # 母体反馈——fast/turbo 用规则引擎替代 LLM（省 6 次 LLM 调用）
        if i < 6:
            from config import get_time_scale as _gts
            _ts = _gts()
            logger.info("母体反馈决策: stage=%s, time_scale=%s", stage_name, _ts)
            # 母体反馈按速率分级：
            #   slow/normal: 全部 6 次 LLM
            #   fast: 3 LLM (zygote + late_org + late_neural) + 3 规则
            #   turbo: 全部 6 次规则
            _MATERNAL_RULE_STAGES: dict[str, set[str]] = {
                "slow":   set(),
                "normal": set(),
                "fast":   {"early_organogenesis", "early_neural", "fetal_movement"},
                "turbo":  {"zygote", "early_organogenesis", "early_neural",
                           "late_organogenesis", "late_neural", "fetal_movement"},
            }
            _maternal_use_rule = stage_name in _MATERNAL_RULE_STAGES.get(_ts, set())

            if _maternal_use_rule:
                maternal_response = _rule_maternal_response(stage_name, env)
                logger.info("母体反馈走规则引擎: stage=%s, time_scale=%s", stage_name, _ts)
                yield {
                    "stage": stage_name, "status": "maternal_response_rule",
                    "stage_num": i + 1,
                }
            else:
                yield {"stage": stage_name, "status": "maternal_response", "stage_num": i + 1}
                _executor2 = ThreadPoolExecutor(max_workers=1)
                _future2 = _executor2.submit(
                    _get_maternal_response, species, stage_name, raw, env, client, model, provider,
                )
                _elapsed2 = 0
                while not _future2.done():
                    _time.sleep(1)
                    _elapsed2 += 1
                    yield {
                        "stage": stage_name, "status": "maternal_thinking",
                        "stage_num": i + 1, "elapsed": _elapsed2,
                    }
                maternal_response = _future2.result()
                _executor2.shutdown(wait=False)
            maternal_states.append(maternal_response)

            # budget delta 由代码从子系统数值确定性计算
            budget_delta = compute_budget_delta(
                hormones, placenta_state, nutrient_effects, immune_risks, env,
            )
            env, feedback_record = apply_maternal_feedback(env, budget_delta)
            yield {
                "stage": stage_name, "status": "maternal_response_done",
                "stage_num": i + 1, "maternal_response": maternal_response,
                "feedback_applied": feedback_record,
            }
            if feedback_record:
                gestation_log[-1]["feedback_applied"] = feedback_record

    final_raw = stage_results[-1]
    try:
        result = _parse_json(final_raw)
    except (json.JSONDecodeError, IndexError):
        yield {"stage": "birth", "status": "failed", "error": f"JSON parse failed: {final_raw}"}
        return

    if "tendencies" not in result or "first_cry" not in result:
        yield {"stage": "birth", "status": "failed", "error": f"Missing fields: {result}"}
        return

    result["gestation_log"] = gestation_log
    result["total_gestation_days"] = gestation_day
    yield {"stage": "complete", "status": "done", "result": result}
