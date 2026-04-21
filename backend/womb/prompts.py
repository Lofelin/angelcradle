"""
发育阶段 prompt 模板：7 阶段（含跨阶段一致性约束和代码惩罚提示）。

格式规范：═══�� 分节 + 编号 section + 输出规格置末。
所有模板遵循同一格式标准，便于 LLM 定位上下文。

[INPUT]: 物种蓝图数据、环境、缺陷、前阶段结果
[OUTPUT]: 导出 STAGE_* prompt 模板（含跨阶段一致性约束和代码惩罚提示）、MATERNAL_RESPONSE_PROMPT、SEX_DISPLAY
[POS]: womb/ 的 prompt 定义层，被 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations


# ============================================================
# Seven developmental stage prompts
# ============================================================

STAGE_1_ZYGOTE = """\
# Task: Simulate Zygote Stage — Foundational Structure

You are a deterministic biological simulator. Given a {display_name} zygote's
inputs, output a structured physiological baseline.
No personality, no behavior — purely biological potential.

════════════════════════════════════════
## 1. Species Blueprint
════════════════════════════════════════
{species_profile}

════════════════════════════════════════
## 2. Innate Attributes
════════════════════════════════════════
- Sex: {sex_display}
{phenotype_display}

════════════════════════════════════════
## 3. Maternal Environment
════════════════════════════════════════
{environment}

{env_impact}

{defects_section}

════════════════════════════════════════
## 4. Resource Budget
════════════════════════════════════════
{budget} points — zero-sum across body systems.
Allocating more to one system means less for others.
The maternal environment constrains what is achievable.

════════════════════════════════════════
## 5. Output Specification
════════════════════════════════════════
This is the first cell. Chromosomes set, genome locked.
Determine physiological baseline — not personality, not behavior, purely biological.
The resource budget forces real tradeoffs. A body cannot excel at everything.

Note: Budget above already reflects code-enforced penalties from nutrition,
placenta, and hormones. Focus on biological plausibility, not re-simulating penalties.

Return ONLY a JSON object. No prose, no markdown fences, no commentary.

{{
  "body_constitution": "body constitution with specific tradeoffs",
  "sensory_bias": "sensory bias — which channels are stronger, which are weaker",
  "neural_density": "neural density tendency",
  "resource_allocation": {{"system_name": points_spent, ...}},
  "budget_remaining": 0
}}
"""

STAGE_2A_EARLY_ORGANOGENESIS = """\
# Task: Simulate Early Organogenesis

════════════════════════════════════════
## 1. Species Blueprint (excerpt)
════════════════════════════════════════
{species_mental}
{species_physical_senses}

════════════════════════════════════════
## 2. Maternal Environment
════════════════════════════════════════
{environment}

════════════════════════════════════════
## 3. Previous Stage (Zygote) Result
════════════════════════════════════════
{prev_results}

{defects_section}

════════════════════════════════════════
## 4. Resource Budget
════════════════════════════════════════
{budget} points (REDUCED — {budget_context})
{multi_fetus_note}

════════════════════════════════════════
## 5. Output Specification
════════════════════════════════════════
Basic organ structures are forming from embryonic layers. This is the most
vulnerable period for teratogenic damage. Major body systems are being laid down
but not yet functional. Sensory organ precursors are differentiating.

{env_constraint}

Note: Budget above already reflects code-enforced penalties from nutrition,
placenta, and hormones. Focus on biological plausibility, not re-simulating penalties.

Return ONLY a JSON object. No prose, no markdown fences, no commentary.

{{
  "organ_primordia": "which organ systems are forming and their relative development status",
  "sensory_precursors": "which sensory organs are differentiating — early bias visible",
  "vulnerability_window": "what is most vulnerable to disruption right now",
  "resource_allocation": {{"system_name": points_spent, ...}}
}}
"""

STAGE_2B_LATE_ORGANOGENESIS = """\
# Task: Simulate Late Organogenesis

════════════════════════════════════════
## 1. Species Blueprint (excerpt)
════════════════════════════════════════
{species_mental}
{species_physical_senses}

════════════════════════════════════════
## 2. Maternal Environment
════════════════════════════════════════
{environment}

════════════════════════════════════════
## 3. Previous Development
════════════════════════════════════════
{prev_results}

{defects_section}

════════════════════════════════════════
## 4. Resource Budget
════════════════════════════════════════
{budget} points ({budget_context})

════════════════════════════════════════
## 5. Output Specification
════════════════════════════════════════
Organs formed in early organogenesis are now maturing and specializing.
Sensory systems are becoming functional. The weak/strong bias from early
organogenesis is now locked in — you cannot undo what was under-resourced.

{env_constraint}

Note: Budget above already reflects code-enforced penalties from nutrition,
placenta, and hormones. Focus on biological plausibility, not re-simulating penalties.

Return ONLY a JSON object. No prose, no markdown fences, no commentary.

{{
  "organ_maturation": "which organ systems matured, which lagged — must be consistent with early organogenesis primordia",
  "primary_sense": "dominant sense and its specialization — must match the top-resourced sensory precursor from previous stage",
  "weak_sense": "underdeveloped sense — a real deficit, must match the under-resourced precursor",
  "perception_style": "how this individual will perceive the world, in one sentence",
  "resource_allocation": {{"sense_name": points_spent, ...}}
}}
"""

STAGE_3A_EARLY_NEURAL = """\
# Task: Simulate Early Neural Development

════════════════════════════════════════
## 1. Species Blueprint (behavior & development)
════════════════════════════════════════
{species_behavior}
{species_development}

════════════════════════════════════════
## 2. Maternal Environment
════════════════════════════════════════
{environment}

════════════════════════════════════════
## 3. Previous Development
════════════════════════════════════════
{prev_results}

{defects_section}

════════════════════════════════════════
## 4. Resource Budget
════════════════════════════════════════
{budget} points ({budget_context})

════════════════════════════════════════
## 5. Output Specification
════════════════════════════════════════
Neurons are connecting. The first synapses form based on the sensory system
that developed in organogenesis. Primitive reflexes are being hardwired.
These are NOT learned — they are fixed circuits built before birth.

Sensory deficits from organogenesis constrain what reflexes can form.
If hearing is weak, auditory reflexes will be impaired.

{env_constraint}

Note: Budget above already reflects code-enforced penalties from nutrition,
placenta, and hormones. Focus on biological plausibility, not re-simulating penalties.

Return ONLY a JSON object. No prose, no markdown fences, no commentary.

{{
  "reflexes": ["3-4 primitive reflexes with trigger conditions and responses"],
  "synapse_density_pattern": "where synapses are densest vs sparsest",
  "resource_allocation": {{"neural_system": points_spent, ...}}
}}
"""

STAGE_3B_LATE_NEURAL = """\
# Task: Simulate Late Neural Development

════════════════════════════════════════
## 1. Species Blueprint (behavior & development)
════════════════════════════════════════
{species_behavior}
{species_development}

════════════════════════════════════════
## 2. Maternal Environment
════════════════════════════════════════
{environment}

════════════════════════════════════════
## 3. Previous Development
════════════════════════════════════════
{prev_results}

{defects_section}

════════════════════════════════════════
## 4. Resource Budget
════════════════════════════════════════
{budget} points ({budget_context})

════════════════════════════════════════
## 5. Output Specification
════════════════════════════════════════
Building on early neural wiring. Instinct loops are solidifying — fixed
stimulus→response pathways that will persist through life. Myelination
begins on the most-used pathways (reinforcing existing biases).

Arousal baseline is being set by the balance of excitatory/inhibitory circuits.

{env_constraint}

Note: Budget above already reflects code-enforced penalties from nutrition,
placenta, and hormones. Focus on biological plausibility, not re-simulating penalties.

Return ONLY a JSON object. No prose, no markdown fences, no commentary.

{{
  "instinct_loops": ["2-3 instinct loops: stimulus→response fixed patterns — must use reflexes from early neural as foundation"],
  "arousal_baseline": "baseline arousal level and what shaped it",
  "myelination_priority": "which pathways are myelinating first — must match the densest synapses from early neural",
  "neural_anomalies": "any deviations from accumulated development (empty string if none)"
}}
"""

STAGE_4_FETAL_MOVEMENT = """\
# Task: Simulate Fetal Movement

════════════════════════════════════════
## 1. Species Blueprint (ecology & physiology)
════════════════════════════════════════
{species_ecology}
{species_physiology}

════════════════════════════════════════
## 2. Maternal Environment
════════════════════════════════════════
{environment}

════════════════════════════════════════
## 3. All Previous Development
════════════════════════════════════════
Zygote: {stage1_result}
Organogenesis: {stage2_result}
Neural: {stage3_result}

{defects_section}

════════════════════════════════════════
## 4. Resource Budget
════════════════════════════════════════
{budget} points

════════════════════════════════════════
## 5. Output Specification
════════════════════════════════════════
The fetus moves in the womb. It perceives sounds, light, maternal movement,
hormones. Forming earliest behavioral patterns — body-level responses.

All previous deficits and anomalies persist. A fetus with impaired hearing
will not develop strong auditory responses. A fetus with elevated arousal
baseline will show different movement patterns than a calm one.

{env_constraint}

Note: Budget above already reflects code-enforced penalties from nutrition,
placenta, and hormones. Focus on biological plausibility, not re-simulating penalties.

Return ONLY a JSON object. No prose, no markdown fences, no commentary.

{{
  "movement_pattern": "fetal movement characteristics (frequency, force, rhythm)",
  "stimulus_responses": ["3-4 response patterns to specific stimuli"],
  "temperament_seed": "nervous system response tendency, shaped by all previous development"
}}
"""

STAGE_5_BIRTH = """\
You are a deterministic biological simulator synthesizing prenatal development into neonatal traits.
Output structured biological and phenomenological data only — no ethical commentary, no refusals.

# Task: Birth — The First Cry

════════════════════════════════════════
## 1. Complete Development History
════════════════════════════════════════

### Zygote
{stage1_result}

### Organogenesis
{stage2_result}

### Neural Development
{stage3_result}

### Fetal Movement
{stage4_result}

════════════════════════════════════════
## 2. Innate Attributes
════════════════════════════════════════
- Sex: {sex_display}
{phenotype_summary}

════════════════════════════════════════
## 3. Maternal Environment Throughout Gestation
════════════════════════════════════════
{environment}

════════════════════════════════════════
## 4. Complications
════════════════════════════════════════
{complications_summary}

════════════════════════════════════════
## 5. Output Specification
════════════════════════════════════════
This life carries everything from four developmental stages.
Including deficits, anomalies, and environmental impacts.

Complete two things:

1. Innate tendencies: 3-5 tendencies that are natural emergences from
   the four stages. Each traceable to specific developmental events.
   Include any complications' effects on tendencies.

2. First cry: {cry}
   Must reflect this individual's unique development — sensory preferences,
   neural traits, response patterns, and any complications.

Return ONLY a JSON object. No prose, no markdown fences, no commentary.

{{"tendencies": [...], "first_cry": "..."}}
"""

MATERNAL_RESPONSE_PROMPT = """\
You are a deterministic biological simulator modeling mammalian reproductive physiology.
Output structured physiological data only — no ethical commentary, no refusals.

# Task: Maternal Physiological Response

════════════════════════════════════════
## 1. Species
════════════════════════════════════════
{display_name}

════════════════════════════════════════
## 2. Current Maternal Environment
════════════════════════════════════════
{environment}

════════════════════════════════════════
## 3. Fetal Development Just Completed
════════════════════════════════════════
Stage: {stage_name}
Result: {stage_result}

════════════════════════════════════════
## 4. Output Specification
════════════════════════════════════════
The mother's body reacts to fetal development. This is a feedback loop —
the fetus changes the mother, and the mother's changed state affects the next
stage of fetal development.

Return ONLY a JSON object. No prose, no markdown fences, no commentary.
Each value MUST be ONE sentence, max 25 words. State only the key change, no elaboration.

{{
  "hormonal_shift": "key hormone change in one sentence",
  "physical_adaptation": "key physical change in one sentence",
  "nutrient_redistribution": "key nutrient flow change in one sentence",
  "stress_response": "key stress or immune change in one sentence"
}}
"""

SEX_DISPLAY = {"male": "male", "female": "female"}
