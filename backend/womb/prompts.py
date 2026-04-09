"""
发育阶段 prompt 模板：7 阶段 + 母体反馈。

[INPUT]: 物种蓝图数据、环境、缺陷、前阶段结果
[OUTPUT]: 导出 STAGE_* prompt 模板、SEX_DISPLAY、MATERNAL_RESPONSE_PROMPT
[POS]: womb/ 的 prompt 定义层，被 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations


# ============================================================
# Seven developmental stage prompts
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
