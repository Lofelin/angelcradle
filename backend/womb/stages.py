"""
发育阶段编排：7 阶段顺序调用 + 预算执法 + 母体反馈 + 流式输出。

集成：动态环境、营养素阶段敏感性、致畸时间窗口、胎盘效率、免疫风险、遗传基因型注入。

[INPUT]: 物种蓝图、环境、缺陷、LLM client、可选 genotype
[OUTPUT]: 导出 express(), express_stream(), build_stage_prompts(), STAGE_NAMES, STAGE_DURATIONS, RESOURCE_BUDGET
[POS]: womb/ 的发育引擎核心，被 womb/__init__.py 和 api/conceive.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from .llm import _create_client, _call_llm, _parse_json, _get_model
from .prompts import (
    STAGE_1_ZYGOTE, STAGE_2A_EARLY_ORGANOGENESIS, STAGE_2B_LATE_ORGANOGENESIS,
    STAGE_3A_EARLY_NEURAL, STAGE_3B_LATE_NEURAL, STAGE_4_FETAL_MOVEMENT,
    STAGE_5_BIRTH, MATERNAL_RESPONSE_PROMPT, SEX_DISPLAY,
)
from .environment import format_environment, environment_impact_text, get_effective_budget
from .fate import validate_resource_semantics, validate_defect_consistency
from .dynamic_env import roll_env_change, apply_maternal_feedback
from .nutrients import get_stage_nutrient_effects, format_nutrients_for_prompt
from .teratogen import get_teratogen_risk, format_teratogen_for_prompt
from .placenta import update_placenta, get_placenta_budget_factor, format_placenta_for_prompt
from .immunity import get_immune_risk_modifiers, format_immunity_for_prompt
from .heredity import format_genetics_for_prompt
from .hormones import compute_hormones, get_hormone_effects, format_hormones_for_prompt
from .vitals import compute_vitals, format_vitals_for_display
from .epigenetics import format_epigenetics_for_prompt


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
    """Format the complete species blueprint."""
    section_names = {
        "physical": "Physical Traits",
        "mental": "Mental Traits",
        "morphology": "Morphology",
        "reproduction": "Reproduction",
        "reproductive_isolation": "Reproductive Isolation",
        "genetics": "Genetics",
        "ecology": "Ecology",
        "physiology": "Physiology & Biochemistry",
        "behavior": "Behavior",
        "distribution": "Geographic Distribution",
        "development": "Development",
        "evolution": "Evolutionary History",
        "domestication": "Domestication",
    }
    sections = []
    for key, title in section_names.items():
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

    # Stage 7: Birth
    cry = blueprint["womb"]["cry"]
    p = STAGE_5_BIRTH.format(
        display_name=display_name,
        stage1_result=stage_results[0], stage2_result=stage_results[2],
        stage3_result=stage_results[4], stage4_result=stage_results[5],
        sex_display=sex_display, phenotype_display=phenotype_display,
        environment=env_text,
        complications_summary=_format_complications(defects, preterm),
        cry=cry,
    )
    prompts.append(("birth", p, RESOURCE_BUDGET["birth"]))

    return prompts


# ============================================================
# Maternal response
# ============================================================

def _get_maternal_response(
    species: str, stage_name: str, stage_result: str,
    environment: dict, client, model: str, provider: str,
) -> dict:
    """
    Generate maternal body's response to fetal development.
    This is the feedback loop: fetus → mother → next stage.
    """
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
    except Exception:
        return {"updated_environment_modifier": "neutral — maternal response unknown"}


# ============================================================
# Seven-stage development
# ============================================================

def express(
    species: str, sex: str, phenotype: dict,
    environment: dict = None, defects: list[str] = None,
    offspring_count: int = 1, birth_order: int = 0,
    provider: str = "deepseek", model: str | None = None,
    genotype: dict = None,
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

    for i in range(7):
        stage_name = STAGE_NAMES[i]
        duration = _get_stage_duration(species, stage_name, env)

        # --- 动态环境：阶段间概率触发变化 ---
        env_event = None
        if i > 0:
            env, env_event = roll_env_change(env, probability=0.20)

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

        # 注入营养素、致畸、胎盘、免疫、激素、表观遗传信息到 prompt
        nutrients_text = format_nutrients_for_prompt(env.get("nutrients", {}), stage_name)
        if nutrients_text:
            prompt += "\n\n" + nutrients_text
        teratogen_text = format_teratogen_for_prompt(env.get("toxin_types", []), stage_name)
        if teratogen_text:
            prompt += "\n\n" + teratogen_text
        placenta_text = format_placenta_for_prompt(placenta_state, stage_name)
        if placenta_text:
            prompt += "\n\n" + placenta_text
        immunity_text = format_immunity_for_prompt(env.get("immunity", {}), stage_name)
        if immunity_text:
            prompt += "\n\n" + immunity_text
        hormones_text = format_hormones_for_prompt(hormones, stage_name)
        if hormones_text:
            prompt += "\n\n" + hormones_text
        # 表观遗传（仅 zygote 阶段注入，后续阶段已在基因型中体现）
        methylation = phenotype.get("_methylation_profile", {})
        if i == 0 and methylation:
            epi_text = format_epigenetics_for_prompt(methylation, env)
            if epi_text:
                prompt += "\n\n" + epi_text

        # 注入累积母体反馈
        if maternal_states:
            prompt += "\n\n## Accumulated Maternal Feedback\n"
            for ms in maternal_states[-2:]:
                prompt += json.dumps(ms, ensure_ascii=False, indent=2) + "\n"

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

        # 母体反馈——出生阶段跳过
        if i < 6:
            maternal_response = _get_maternal_response(
                species, stage_name, raw, env, client, model, provider,
            )
            maternal_states.append(maternal_response)

            # --- 母体反馈数值化：真正修改 budget_multiplier ---
            env, feedback_record = apply_maternal_feedback(env, maternal_response)
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

    for i in range(7):
        stage_name = STAGE_NAMES[i]
        duration = _get_stage_duration(species, stage_name, env)
        gestation_day += duration

        # --- 动态环境 ---
        env_event = None
        if i > 0:
            env, env_event = roll_env_change(env, probability=0.20)
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

        # 注入营养素、致畸、胎盘、免疫、激素信息
        nutrients_text = format_nutrients_for_prompt(env.get("nutrients", {}), stage_name)
        if nutrients_text:
            prompt += "\n\n" + nutrients_text
        teratogen_text = format_teratogen_for_prompt(env.get("toxin_types", []), stage_name)
        if teratogen_text:
            prompt += "\n\n" + teratogen_text
        placenta_text = format_placenta_for_prompt(placenta_state, stage_name)
        if placenta_text:
            prompt += "\n\n" + placenta_text
        immunity_text = format_immunity_for_prompt(env.get("immunity", {}), stage_name)
        if immunity_text:
            prompt += "\n\n" + immunity_text
        hormones_text = format_hormones_for_prompt(hormones, stage_name)
        if hormones_text:
            prompt += "\n\n" + hormones_text
        # 表观遗传（仅 zygote）
        methylation = phenotype.get("_methylation_profile", {})
        if i == 0 and methylation:
            epi_text = format_epigenetics_for_prompt(methylation, env)
            if epi_text:
                prompt += "\n\n" + epi_text

        if maternal_states:
            prompt += "\n\n## Accumulated Maternal Feedback\n"
            for ms in maternal_states[-2:]:
                prompt += json.dumps(ms, ensure_ascii=False, indent=2) + "\n"

        # LLM 调用放到线程，主线程每秒 yield 进度心跳
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        import time as _time
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
                }
            raw = _future.result()
        except Exception as e:
            _executor.shutdown(wait=False)
            yield {"stage": stage_name, "status": "failed", "error": str(e)}
            return
        finally:
            _executor.shutdown(wait=False)

        stage_results.append(raw)

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

        if i < 6:
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

            # --- 母体反馈数值化 ---
            env, feedback_record = apply_maternal_feedback(env, maternal_response)
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
