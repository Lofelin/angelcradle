"""
Womb developmental process: five-stage gestation.

Each stage makes one LLM call. Output of stage N feeds into stage N+1.
Complexity emerges layer by layer, not stamped in one pass.

Resource budget forces tradeoffs. Environment affects development.
Defects persist forward. No retries — what develops, develops.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

import anthropic
from openai import OpenAI

from .environment import format_environment, environment_impact_text, get_effective_budget
from .fate import validate_resource_semantics, validate_defect_consistency


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
    "birth": 100,  # birth stage summarizes, no budget constraint
}

# ============================================================
# Five developmental stage prompts
# ============================================================

STAGE_1_ZYGOTE = """\
You are simulating the foundational structure determination of a {display_name} zygote.

## Species Blueprint
{species_profile}

## Innate Attributes
- Sex: {sex_display}
{phenotype_display}

## Maternal Environment
{environment}

## Environmental Impact
{env_impact}

{defects_section}

## Resource Budget: {budget} points
You have {budget} resource points to allocate across body systems.
Allocating more to one system means less for others — this is a zero-sum budget.
The maternal environment constrains what is achievable.

## Stage Task: Zygote — Foundational Structure

This is the first cell. Chromosomes set, genome locked.
Determine physiological baseline — not personality, not behavior, purely biological.
The resource budget forces real tradeoffs. A body cannot excel at everything.

Output as JSON:
{{
  "body_constitution": "body constitution with specific tradeoffs",
  "sensory_bias": "sensory bias — which channels are stronger, which are weaker",
  "neural_density": "neural density tendency",
  "resource_allocation": {{"system_name": points_spent, ...}},
  "budget_remaining": 0
}}
"""

STAGE_2A_EARLY_ORGANOGENESIS = """\
You are simulating early organogenesis of a {display_name}.

## Species Blueprint (excerpt)
{species_mental}
{species_physical_senses}

## Maternal Environment
{environment}

## Previous Stage (Zygote) Result
{prev_results}

{defects_section}

## Resource Budget: {budget} points (this is a REDUCED budget — {budget_context})
{multi_fetus_note}

## Stage Task: Early Organogenesis — Organ Primordia Formation

Basic organ structures are forming from embryonic layers. This is the most
vulnerable period for teratogenic damage. Major body systems are being laid down
but not yet functional. Sensory organ precursors are differentiating.

{env_constraint}

Output as JSON:
{{
  "organ_primordia": "which organ systems are forming and their relative development status",
  "sensory_precursors": "which sensory organs are differentiating — early bias visible",
  "vulnerability_window": "what is most vulnerable to disruption right now",
  "resource_allocation": {{"system_name": points_spent, ...}}
}}
"""

STAGE_2B_LATE_ORGANOGENESIS = """\
You are simulating late organogenesis of a {display_name}.

## Species Blueprint (excerpt)
{species_mental}
{species_physical_senses}

## Maternal Environment
{environment}

## Previous Development
{prev_results}

{defects_section}

## Resource Budget: {budget} points ({budget_context})

## Stage Task: Late Organogenesis — Sensory System Maturation

Organs formed in early organogenesis are now maturing and specializing.
Sensory systems are becoming functional. The weak/strong bias from early
organogenesis is now locked in — you cannot undo what was under-resourced.

{env_constraint}

Output as JSON:
{{
  "primary_sense": "dominant sense and its specialization",
  "secondary_sense": "secondary sense and traits",
  "weak_sense": "underdeveloped sense — a real deficit from under-resourcing",
  "perception_style": "how this individual perceives the world",
  "resource_allocation": {{"sense_name": points_spent, ...}}
}}
"""

STAGE_3A_EARLY_NEURAL = """\
You are simulating early neural development of a {display_name}.

## Species Blueprint (behavior & development)
{species_behavior}
{species_development}

## Maternal Environment
{environment}

## Previous Development
{prev_results}

{defects_section}

## Resource Budget: {budget} points ({budget_context})

## Stage Task: Early Neural — Synapse Formation & Primitive Reflexes

Neurons are connecting. The first synapses form based on the sensory system
that developed in organogenesis. Primitive reflexes are being hardwired.
These are NOT learned — they are fixed circuits built before birth.

Sensory deficits from organogenesis constrain what reflexes can form.
If hearing is weak, auditory reflexes will be impaired.

{env_constraint}

Output as JSON:
{{
  "reflexes": ["3-4 primitive reflexes with trigger conditions and responses"],
  "synapse_density_pattern": "where synapses are densest vs sparsest",
  "resource_allocation": {{"neural_system": points_spent, ...}}
}}
"""

STAGE_3B_LATE_NEURAL = """\
You are simulating late neural development of a {display_name}.

## Species Blueprint (behavior & development)
{species_behavior}
{species_development}

## Maternal Environment
{environment}

## Previous Development
{prev_results}

{defects_section}

## Resource Budget: {budget} points ({budget_context})

## Stage Task: Late Neural — Instinct Loops & Myelination Onset

Building on early neural wiring. Instinct loops are solidifying — fixed
stimulus→response pathways that will persist through life. Myelination
begins on the most-used pathways (reinforcing existing biases).

Arousal baseline is being set by the balance of excitatory/inhibitory circuits.

{env_constraint}

Output as JSON:
{{
  "instinct_loops": ["2-3 instinct loops: stimulus→response fixed patterns"],
  "arousal_baseline": "baseline arousal level and what shaped it",
  "myelination_priority": "which pathways are myelinating first (these become fastest)",
  "neural_anomalies": "any deviations from accumulated development (empty string if none)"
}}
"""

STAGE_4_FETAL_MOVEMENT = """\
You are simulating fetal movement of a {display_name}.

## Species Blueprint (ecology & physiology)
{species_ecology}
{species_physiology}

## Maternal Environment
{environment}

## All Previous Development
Zygote: {stage1_result}
Organogenesis: {stage2_result}
Neural: {stage3_result}

{defects_section}

## Resource Budget: {budget} points

## Stage Task: Fetal Movement — Stimulus Response Patterns

The fetus moves in the womb. It perceives sounds, light, maternal movement,
hormones. Forming earliest behavioral patterns — body-level responses.

All previous deficits and anomalies persist. A fetus with impaired hearing
will not develop strong auditory responses. A fetus with elevated arousal
baseline will show different movement patterns than a calm one.

{env_constraint}

Output as JSON:
{{
  "movement_pattern": "fetal movement characteristics (frequency, force, rhythm)",
  "stimulus_responses": ["3-4 response patterns to specific stimuli"],
  "temperament_seed": "nervous system response tendency, shaped by all previous development"
}}
"""

STAGE_5_BIRTH = """\
You are helping a {display_name} complete birth.

## Complete Development History

### Zygote
{stage1_result}

### Organogenesis
{stage2_result}

### Neural Development
{stage3_result}

### Fetal Movement
{stage4_result}

## Innate Attributes
- Sex: {sex_display}
{phenotype_display}

## Maternal Environment Throughout Gestation
{environment}

## Complications
{complications_summary}

## Stage Task: Birth — The First Cry

This life carries everything from four developmental stages.
Including deficits, anomalies, and environmental impacts.

Complete two things:

1. Innate tendencies: 3-5 tendencies that are natural emergences from
   the four stages. Each traceable to specific developmental events.
   Include any complications' effects on tendencies.

2. First cry: {cry}
   Must reflect this individual's unique development — sensory preferences,
   neural traits, response patterns, and any complications.

Output as JSON:
{{"tendencies": [...], "first_cry": "..."}}
"""

MATERNAL_RESPONSE_PROMPT = """\
You are simulating the maternal body's physiological response after a developmental stage.

## Species: {display_name}

## Current Maternal Environment
{environment}

## Fetal Development Just Completed
Stage: {stage_name}
Result: {stage_result}

## Task: Maternal Response

The mother's body reacts to fetal development. This is a feedback loop —
the fetus changes the mother, and the mother's changed state affects the next
stage of fetal development.

Generate the maternal body's response as JSON:
{{
  "hormonal_shift": "how hormone levels changed (e.g., cortisol, progesterone, hCG)",
  "physical_adaptation": "physical changes in the uterine environment",
  "nutrient_redistribution": "how nutrient flow to the fetus changed",
  "stress_response": "any stress or immune response triggered",
  "updated_environment_modifier": "how this changes the effective environment for the next stage (better/worse/neutral with specifics)"
}}
"""

SEX_DISPLAY = {"male": "male", "female": "female"}


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


# ============================================================
# LLM providers
# ============================================================

PROVIDERS = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    "anthropic": {
        "api_key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-6",
    },
}


def _create_client(provider: str):
    config = PROVIDERS.get(provider)
    if not config:
        raise ValueError(f"Unknown provider '{provider}', available: {', '.join(PROVIDERS)}")
    api_key = os.environ.get(config["api_key_env"], "")
    if not api_key:
        raise ValueError(f"Missing env var {config['api_key_env']}")
    if provider == "anthropic":
        return anthropic.Anthropic(api_key=api_key)
    return OpenAI(api_key=api_key, base_url=config.get("base_url"))


def _call_llm(prompt: str, client, model: str, provider: str) -> str:
    if provider == "anthropic":
        response = client.messages.create(
            model=model, max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    else:
        response = client.chat.completions.create(
            model=model, max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content


def _parse_json(raw: str) -> dict:
    """Parse JSON from LLM output. Attempts repair for common LLM JSON errors."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    # First try: direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Repair attempt: fix missing braces in arrays
    # LLM sometimes writes {"key": "val"} then next item without opening {
    import re
    repaired = re.sub(
        r',\s*"(\w+)":\s*"',
        lambda m: m.group(0) if _is_inside_object(cleaned, m.start()) else ', {"' + m.group(1) + '": "',
        cleaned,
    )
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Repair attempt: balance braces/brackets
    open_braces = cleaned.count('{') - cleaned.count('}')
    open_brackets = cleaned.count('[') - cleaned.count(']')
    if open_braces > 0 or open_brackets > 0:
        repaired = cleaned + '}' * open_braces + ']' * open_brackets
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    # All repairs failed
    raise json.JSONDecodeError("All parse attempts failed", cleaned, 0)


def _is_inside_object(text: str, pos: int) -> bool:
    """Rough check if position is inside a JSON object (not between array items)."""
    depth = 0
    for i in range(pos):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
    return depth > 1  # depth 1 = top-level object, >1 = nested


def _enforce_budget(parsed: dict, budget: int) -> dict:
    """
    Enforce resource budget on LLM output.

    If resource_allocation exists and total exceeds budget,
    scale down proportionally. No retries — just cut.
    """
    allocation = parsed.get("resource_allocation")
    if not allocation or not isinstance(allocation, dict):
        return parsed

    # Filter to numeric values only
    numeric = {k: v for k, v in allocation.items() if isinstance(v, (int, float))}
    if not numeric:
        return parsed

    total = sum(numeric.values())
    if total <= budget:
        parsed["budget_enforced"] = False
        return parsed

    # Over budget — scale down proportionally
    scale = budget / total
    enforced = {k: round(v * scale) for k, v in numeric.items()}

    # Redistribute rounding remainder
    remainder = budget - sum(enforced.values())
    if remainder > 0:
        top_key = max(enforced, key=enforced.get)
        enforced[top_key] += remainder

    parsed["resource_allocation"] = enforced
    parsed["budget_enforced"] = True
    parsed["budget_original_total"] = total
    parsed["budget_scale_factor"] = round(scale, 3)
    return parsed


# ============================================================
# Five-stage development
# ============================================================

def _build_env_constraint(env: dict) -> str:
    """Build environment constraint text for stage prompts."""
    impact = environment_impact_text(env)
    if "Favorable" in impact:
        return ""
    return f"Environmental constraint: {impact}"


def build_stage_prompts(
    species: str, sex: str, phenotype: dict,
    stage_results: list[str],
    environment: dict = None,
    defects: list[str] = None,
    preterm: dict = None,
    offspring_count: int = 1,
    birth_order: int = 0,
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


def _get_stage_duration(species: str, stage: str) -> int:
    """Get duration in days for a stage."""
    return STAGE_DURATIONS.get(species, STAGE_DURATIONS["human"]).get(stage, 14)


def express(
    species: str, sex: str, phenotype: dict,
    environment: dict = None, defects: list[str] = None,
    offspring_count: int = 1, birth_order: int = 0,
    provider: str = "deepseek", model: str | None = None,
) -> dict:
    """
    Five-stage developmental expression with:
    1. Resource budget enforcement (code-level, not LLM honor system)
    2. Maternal feedback loop (fetus→mother→next stage)
    3. Time dimension (stage durations recorded)

    No retries. Parse failure = development failure.
    """
    client = _create_client(provider)
    if model is None:
        model = PROVIDERS[provider]["default_model"]

    stage_results: list[str] = []
    gestation_log: list[dict] = []
    maternal_states: list[dict] = []  # accumulated, not overwritten
    gestation_day = 0

    for i in range(7):
        stage_name = STAGE_NAMES[i]
        duration = _get_stage_duration(species, stage_name)

        prompts = build_stage_prompts(
            species, sex, phenotype, stage_results,
            environment=environment, defects=defects,
            offspring_count=offspring_count, birth_order=birth_order,
        )
        _, prompt, budget = prompts[i]

        # Inject accumulated maternal feedback
        if maternal_states:
            prompt += "\n\n## Accumulated Maternal Feedback\n"
            for ms in maternal_states[-2:]:  # last 2 to keep prompt reasonable
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

        # Code-level enforcement (改造 1+4+5)
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
        })

        # Maternal feedback loop — skip for birth stage
        if i < 6:
            maternal_response = _get_maternal_response(
                species, stage_name, raw, environment, client, model, provider,
            )
            maternal_states.append(maternal_response)

    # Parse final stage
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
):
    """
    7-stage development as SSE generator with all six improvements.
    """
    client = _create_client(provider)
    if model is None:
        model = PROVIDERS[provider]["default_model"]

    _stage_names = STAGE_NAMES
    stage_results: list[str] = []
    gestation_log: list[dict] = []
    maternal_states: list[dict] = []
    gestation_day = 0

    for i in range(7):
        stage_name = _stage_names[i]
        duration = _get_stage_duration(species, stage_name)
        gestation_day += duration

        yield {
            "stage": stage_name, "status": "in_progress", "stage_num": i + 1,
            "gestation_day": gestation_day, "duration_days": duration,
            "total_stages": 7,
        }

        prompts = build_stage_prompts(
            species, sex, phenotype, stage_results,
            environment=environment, defects=defects,
            offspring_count=offspring_count, birth_order=birth_order,
        )
        _, prompt, budget = prompts[i]

        if maternal_states:
            prompt += "\n\n## Accumulated Maternal Feedback\n"
            for ms in maternal_states[-2:]:
                prompt += json.dumps(ms, ensure_ascii=False, indent=2) + "\n"

        try:
            raw = _call_llm(prompt, client, model, provider)
        except Exception as e:
            yield {"stage": stage_name, "status": "failed", "error": str(e)}
            return

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
        })

        yield {
            "stage": stage_name, "status": "done", "stage_num": i + 1,
            "gestation_day": gestation_day,
            "response": parsed,
            "budget_enforced": budget_enforced,
        }

        if i < 6:
            yield {"stage": stage_name, "status": "maternal_response", "stage_num": i + 1}
            maternal_response = _get_maternal_response(
                species, stage_name, raw, environment, client, model, provider,
            )
            maternal_states.append(maternal_response)
            yield {
                "stage": stage_name, "status": "maternal_response_done",
                "stage_num": i + 1, "maternal_response": maternal_response,
            }

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
