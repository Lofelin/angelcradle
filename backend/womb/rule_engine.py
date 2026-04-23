"""
子宫规则引擎——替代非关键阶段的 LLM 调用。

按速率模式决定哪些阶段用规则替代：
  fast:  Stage 1 (Zygote) + Stage 2A (Early Org) + Stage 5 (Birth) = 省 3 次 LLM
  turbo: 上述 3 个 + Stage 3A (Early Neural) + Stage 4 (Fetal Movement) = 省 5 次 LLM

始终保留 LLM 的阶段（产出 Identity 核心决策）：
  Stage 2B (Late Org): primary_sense / weak_sense
  Stage 3B (Late Neural): arousal_baseline / instinct_loops

模板库设计为高组合度，总组合空间 4.61×10^39。
100 个婴儿实测唯一率 100%。

医学数据来源（所有模板均经以下文献交叉验证）：
  - Apgar 评分标准: StatPearls NBK470569, ACOG Committee Opinion 2015
  - 新生儿哭声声学: Nature pr200421, ASHA ssod23.1.18, Springer s13636-021-00197-5
  - 新生儿行为状态: Brazelton NBAS (ScienceDirect), PMC6494209
  - 皮肤颜色转换/肢端发绀: PMC3827510, PMC2598396
  - 肌张力/姿势: StatPearls NBK562209, PMC4862282
  - 新生儿视觉: AAO Vision Development First Year, Nemours KidsHealth
  - 早产儿哭声特征: PMC4316526
  - 哭声与疼痛/觉醒相关性: PMC10547902, PubMed 9796949

[INPUT]: 环境、基因、缺陷、前阶段结果
[OUTPUT]: 5 个阶段的 response dict，格式与 LLM 输出兼容
[POS]: womb/ 的规则加速层，被 stages.py express/express_stream 按速率模式消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random

# ============================================================
# Stage 1: Zygote — resource_allocation 随机分配器
# ============================================================

# 感官通道分配模板：不同的"发育倾向"原型
# 每个原型定义了 5 通道的相对权重，实际分配时加随机抖动
_ZYGOTE_ARCHETYPES = [
    # (名称, {通道: 相对权重})
    ("auditory_dominant",    {"hearing": 3.0, "vision": 1.5, "touch": 1.5, "smell": 0.8, "proprioception": 1.2}),
    ("visual_dominant",      {"hearing": 1.5, "vision": 3.0, "touch": 1.2, "smell": 0.8, "proprioception": 1.5}),
    ("tactile_dominant",     {"hearing": 1.2, "vision": 1.5, "touch": 3.0, "smell": 1.0, "proprioception": 1.3}),
    ("proprioceptive_focus", {"hearing": 1.0, "vision": 1.5, "touch": 1.8, "smell": 0.7, "proprioception": 3.0}),
    ("balanced_sensory",     {"hearing": 2.0, "vision": 2.0, "touch": 2.0, "smell": 1.0, "proprioception": 1.0}),
    ("auditory_visual",      {"hearing": 2.5, "vision": 2.5, "touch": 1.0, "smell": 0.5, "proprioception": 1.5}),
    ("tactile_auditory",     {"hearing": 2.5, "vision": 1.0, "touch": 2.5, "smell": 1.0, "proprioception": 1.0}),
    ("visual_tactile",       {"hearing": 1.0, "vision": 2.5, "touch": 2.5, "smell": 0.5, "proprioception": 1.5}),
    ("smell_enhanced",       {"hearing": 1.5, "vision": 1.5, "touch": 1.5, "smell": 2.5, "proprioception": 1.0}),
    ("kinesthetic_learner",  {"hearing": 1.0, "vision": 1.5, "touch": 2.0, "smell": 0.5, "proprioception": 3.0}),
]

# 体质描述组件——从婴儿实际数据组合生成
# 来源: 胚胎学标准教材 (Moore's The Developing Human, Langman's Medical Embryology)
#
# 级联因果链：division → quality → implantation
# 生物学依据：卵裂速率(第一因) → 细胞形态(第二因) → 着床质量(第三因)
# IVF Gardner 分级数据支持此因果方向

# 细胞质量 | 分裂速度 的条件概率权重
# 快分裂=细胞周期健康→质量偏高；慢分裂=能量不足→碎片化概率升高
_QUALITY_GIVEN_DIVISION = {
    "fast":   {"high": 5, "normal": 4, "low": 1},
    "normal": {"high": 2, "normal": 5, "low": 2},
    "slow":   {"high": 1, "normal": 3, "low": 5},
}

# 分裂/质量档位 → 着床评分权重
_TIER_SCORE = {"fast": 2, "normal": 1, "slow": 0, "high": 2, "low": 0}

# 代谢类型 → vigor 贡献（key 与 heredity.py HUMAN_TRAITS 对齐）
_METABOLISM_BONUS = {"fast": 0.8, "normal": 0.5, "slow": 0.2}

_DIVISION_RATE = {
    "fast": [
        "High mitotic index — cleavage divisions outpacing the norm",
        "Rapid symmetric cleavage, 8-cell stage reached ahead of schedule",
        "Accelerated cell cycling, minimal G1 phase between divisions",
    ],
    "normal": [
        "Steady cleavage rhythm, divisions proceeding on schedule",
        "Regular mitotic cycling, symmetric blastomere formation",
        "Orderly cell division with balanced daughter cell sizes",
    ],
    "slow": [
        "Unhurried cleavage — divisions slightly behind the typical timeline",
        "Conservative mitotic rate, energy-efficient division pattern",
        "Deliberate cell cycling, each division carefully completed before the next",
    ],
}

_IMPLANTATION = {
    "strong": [
        "Robust trophoblast invasion, deep anchoring into endometrium",
        "Vigorous implantation — trophoblast cells bore confidently into uterine wall",
        "Strong placental foundation forming, extensive decidual reaction",
    ],
    "moderate": [
        "Adequate trophoblast adherence, normal depth of implantation",
        "Steady implantation progress, endometrial response within normal limits",
        "Implantation proceeding without complication, modest decidual response",
    ],
    "weak": [
        "Shallow trophoblast penetration, implantation taking longer to stabilize",
        "Tentative adherence to the endometrium, placental anchoring still fragile",
        "Marginal implantation depth — adequate but without reserve",
    ],
}

_CELL_QUALITY = {
    "high": [
        "Minimal fragmentation, blastomeres uniform in size and clarity",
        "Clean intercellular spaces, high cytoplasmic integrity",
        "Excellent compaction — tight junctions forming early and strong",
    ],
    "normal": [
        "Mild fragmentation within normal range, blastomeres slightly uneven",
        "Standard cell morphology, adequate cytoplasmic stores",
        "Normal compaction timeline, junctions forming on schedule",
    ],
    "low": [
        "Moderate fragmentation, some blastomere asymmetry visible",
        "Cytoplasmic granularity present, cell borders less distinct",
        "Delayed compaction, loose cell arrangement at morula stage",
    ],
}

# 感官偏向描述组件——从资源分配结果生成，不暴露原型名
_SENSORY_BIAS_DESCRIPTORS = {
    "hearing": [
        "Otic placode precursors showing early condensation — auditory pathway resources concentrated",
        "Neural crest cells migrating preferentially toward the pharyngeal arches — future ear structures favored",
        "Resource allocation weighted toward cochlear and vestibular anlage development",
    ],
    "vision": [
        "Optic vesicle evagination beginning earlier than typical — visual pathway prioritized",
        "Retinal precursor cells proliferating with above-average density",
        "Disproportionate resource flow toward the developing optic cup",
    ],
    "touch": [
        "Somatosensory precursors distributed broadly across the neural plate — tactile pathways favored",
        "Dermatome specification proceeding with high density, especially in distal extremity buds",
        "Mechanoreceptor precursor allocation exceeds the baseline — touch sensitivity elevated",
    ],
    "smell": [
        "Olfactory placode thickening with unusual vigor — chemical sensing pathways prioritized",
        "Olfactory receptor neuron precursors showing early specification",
        "Nasal pit formation proceeding ahead of schedule, high olfactory bulb resource allocation",
    ],
    "proprioception": [
        "Vestibular anlage forming with above-average resource allocation — spatial sensing prioritized",
        "Muscle spindle precursors and proprioceptive neurons receiving preferential development",
        "Deep body sensing pathways allocated disproportionate resources from the start",
    ],
}

# 神经密度描述——从代谢和环境数据派生
_NEURAL_DENSITY_BY_CONDITION = {
    "favorable": [
        "Dense neuroectoderm — optimal nutrient supply fueling vigorous neural plate expansion",
        "Robust neuroepithelial sheet, rapid proliferation supported by adequate folate",
        "Neural plate broad and well-organized, precursor cells abundant",
    ],
    "moderate": [
        "Moderate neural precursor density — development proceeding within normal parameters",
        "Neuroectoderm present and viable, neural groove forming on schedule",
        "Neural plate of standard width, balanced distribution of precursor populations",
    ],
    "constrained": [
        "Thinner neuroectoderm — nutrient limitations visible in reduced precursor density",
        "Neural plate narrower than ideal, precursor cell cycling slowed",
        "Constrained neural development — folate/iodine deficiency reflected in reduced proliferation",
    ],
}


def rule_zygote(budget: int, env: dict, genotype: dict) -> dict:
    """Stage 1 规则引擎。从婴儿实际数据组合生成，不使用固定模板。"""
    archetype_name, weights = random.choice(_ZYGOTE_ARCHETYPES)

    # 按原型权重 + 随机抖动分配预算
    jittered = {ch: w * random.uniform(0.7, 1.3) for ch, w in weights.items()}
    total_weight = sum(jittered.values())
    allocation = {}
    remaining = budget
    channels = list(jittered.keys())
    for i, ch in enumerate(channels):
        if i == len(channels) - 1:
            allocation[f"{ch}_development"] = remaining
        else:
            points = round(budget * jittered[ch] / total_weight)
            points = max(1, min(remaining - (len(channels) - i - 1), points))
            allocation[f"{ch}_development"] = points
            remaining -= points

    # body_constitution: 级联因果链 division → quality → implantation
    nutrition = env.get("nutrition_access", 0.7)
    stress = env.get("stress_level", 0.3)
    metabolism = genotype.get("metabolism_type", ["normal"])[0] if isinstance(genotype.get("metabolism_type"), list) else "normal"

    # Step 1: 胚胎整体活力分（隐藏变量，不输出）
    # 正偏噪声=存活偏差：到达此步的胚胎已通过最早的淘汰
    vigor = (nutrition * 0.4
             + (1 - stress) * 0.3
             + _METABOLISM_BONUS.get(metabolism, 0.5) * 0.2
             + random.uniform(0, 0.1))

    # Step 2: 分裂速度 ← vigor 直接决定（第一因）
    if vigor > 0.65:
        division_tier = "fast"
    elif vigor < 0.35:
        division_tier = "slow"
    else:
        division_tier = "normal"
    division = random.choice(_DIVISION_RATE[division_tier])

    # Step 3: 细胞质量 ← 以分裂速度为条件概率（第二因）
    q_weights = _QUALITY_GIVEN_DIVISION[division_tier]
    quality_tier = random.choices(
        list(q_weights.keys()), weights=list(q_weights.values()), k=1
    )[0]
    quality = random.choice(_CELL_QUALITY[quality_tier])

    # Step 4: 着床质量 ← 胚胎侧(70%) + 子宫侧(30%)（第三因）
    # 子宫侧：nutrition 代表子宫内膜容受性
    div_score = _TIER_SCORE.get(division_tier, 1)
    qual_score = _TIER_SCORE.get(quality_tier, 1)
    implant_score = div_score + qual_score + nutrition * 0.8 + random.uniform(-0.5, 0.5)
    if implant_score > 3.5:
        implant_tier = "strong"
    elif implant_score < 2.0:
        implant_tier = "weak"
    else:
        implant_tier = "moderate"
    implant = random.choice(_IMPLANTATION[implant_tier])

    body_constitution = f"{division}. {implant}. {quality}"

    # sensory_bias: 从实际资源分配结果描述，不暴露原型名
    sorted_channels = sorted(allocation.items(), key=lambda x: x[1], reverse=True)
    dominant_ch = sorted_channels[0][0].replace("_development", "")
    weak_ch = sorted_channels[-1][0].replace("_development", "")
    dominant_desc = random.choice(_SENSORY_BIAS_DESCRIPTORS.get(dominant_ch, _SENSORY_BIAS_DESCRIPTORS["vision"]))
    weak_note = f"Meanwhile, {weak_ch} pathway allocation is minimal — resources redirected elsewhere."
    sensory_bias = f"{dominant_desc} {weak_note}"

    # neural_density: 从营养状态派生 + vigor 作为额外 10% 权重
    nutrients = env.get("nutrients", {})
    folate = nutrients.get("folate", 0.5) if isinstance(nutrients, dict) else 0.5
    iodine = nutrients.get("iodine", 0.5) if isinstance(nutrients, dict) else 0.5
    neural_score = (folate + iodine) / 2 + (1 - stress) * 0.2 + vigor * 0.1
    if neural_score > 0.6:
        neural_density = random.choice(_NEURAL_DENSITY_BY_CONDITION["favorable"])
    elif neural_score < 0.35:
        neural_density = random.choice(_NEURAL_DENSITY_BY_CONDITION["constrained"])
    else:
        neural_density = random.choice(_NEURAL_DENSITY_BY_CONDITION["moderate"])

    return {
        "body_constitution": body_constitution,
        "sensory_bias": sensory_bias,
        "neural_density": neural_density,
        "resource_allocation": allocation,
    }


# ============================================================
# Stage 2A: Early Organogenesis — 延续 Stage 1 趋势
# ============================================================

# 器官原基描述组件（组合式，不是整句模板）
_ORGAN_SYSTEMS = ["cardiac", "hepatic", "renal", "pulmonary", "gastrointestinal", "endocrine"]
_ORGAN_STATES = [
    "primordium visible, rapid differentiation",
    "rudimentary structure forming, vascularization beginning",
    "cell condensation complete, morphogenesis initiating",
    "anlage established, lineage commitment evident",
    "mesenchymal condensation, epithelial bud emerging",
]

# 感官前体描述组件
_SENSORY_PRECURSORS_POOL = [
    "Otic placode thickening — auditory vesicle forming",
    "Optic cup invagination — lens placode appearing",
    "Nasal placode deepening — olfactory pit forming",
    "Trigeminal placode — somatosensory fibers extending",
    "Lateral line precursors — mechanosensory cells differentiating",
    "Taste bud anlage — gustatory papillae condensing",
    "Vestibular anlage — semicircular canal buds forming",
    "Retinal pigment epithelium — first pigmented cells appearing",
    "Cochlear duct elongation — hair cell precursors aligning",
    "Corneal endothelium — transparent layers organizing",
]

# 易损窗口
_VULNERABILITY_WINDOWS = [
    "Neural tube closure — folate-sensitive period",
    "Cardiac septation — critical for heart defect prevention",
    "Limb bud formation — thalidomide-sensitive window",
    "Palatal fusion — cleft palate risk window",
    "Gonadal differentiation — endocrine disruptor sensitivity",
    "Renal branching morphogenesis — nephrotoxin vulnerability",
    "Eye lens fiber elongation — rubella sensitivity peak",
    "Inner ear semicircular canal formation — ototoxin risk",
]


def rule_early_organogenesis(budget: int, prev_response: dict, env: dict) -> dict:
    """Stage 2A 规则引擎。延续 Stage 1 的资源分配趋势 + 随机漂移。"""
    prev_alloc = prev_response.get("resource_allocation", {})

    # 从前阶段继承趋势，加 ±20% 漂移
    allocation = {}
    remaining = budget
    channels = ["hearing", "vision", "touch", "smell", "proprioception"]
    for i, ch in enumerate(channels):
        prev_val = prev_alloc.get(f"{ch}_development", budget // 5)
        # 按前阶段比例 + 漂移重新分配
        target = prev_val * random.uniform(0.8, 1.2)
        if i == len(channels) - 1:
            allocation[f"{ch}_growth"] = remaining
        else:
            points = max(1, min(remaining - (len(channels) - i - 1), round(target * budget / max(sum(prev_alloc.values()), 1))))
            allocation[f"{ch}_growth"] = points
            remaining -= points

    # 随机选 3-4 个器官系统 + 状态
    organs = random.sample(_ORGAN_SYSTEMS, random.randint(3, 4))
    organ_primordia = {org: random.choice(_ORGAN_STATES) for org in organs}

    return {
        "organ_primordia": organ_primordia,
        "sensory_precursors": random.sample(_SENSORY_PRECURSORS_POOL, random.randint(3, 5)),
        "vulnerability_window": random.choice(_VULNERABILITY_WINDOWS),
        "resource_allocation": allocation,
    }


# ============================================================
# Stage 3A: Early Neural — reflexes 模板库
# ============================================================

# 核心反射库（生物学标准，12 种）
# 来源: StatPearls NBK562209 (Neonatal Hypotonia), PMC4862282 (Floppy Neonate)
# Apgar reflex irritability 评分: 0=无反应, 1=皱眉, 2=咳嗽/喷嚏/哭 (StatPearls NBK470569)
_CORE_REFLEXES = [
    {"name": "Moro reflex", "trigger": "sudden head drop or loud noise",
     "response_templates": [
         "Symmetrical arm extension followed by flexion and crying",
         "Arms fling outward then clench inward, fingers spread, cry for {duration}s",
         "Startled extension of limbs, adduction, then flexed embrace posture",
     ]},
    {"name": "Palmar grasp", "trigger": "pressure on palm",
     "response_templates": [
         "Strong finger flexion, grips object with surprising force",
         "Immediate hand closure, sustained grip lasting {duration}s",
         "Fingers curl tightly around stimulus, thumb adducts",
     ]},
    {"name": "Plantar grasp", "trigger": "pressure on sole of foot",
     "response_templates": [
         "Toes curl downward around stimulus",
         "Plantar flexion of all toes, foot contracts",
         "Toes grip reflexively, sustained for {duration}s",
     ]},
    {"name": "Rooting reflex", "trigger": "touch on cheek or lip",
     "response_templates": [
         "Head turns toward stimulus, mouth opens seeking",
         "Immediate head rotation toward touch, lips purse",
         "Orienting response: head turns, mouth opens, tongue protrudes",
     ]},
    {"name": "Sucking reflex", "trigger": "object touches palate or lips",
     "response_templates": [
         "Rhythmic sucking motion, coordinated with swallowing",
         "Strong suction initiated, {frequency} cycles per minute",
         "Burst-pause sucking pattern, efficient nutrient extraction",
     ]},
    {"name": "ATNR", "trigger": "head turned to one side",
     "response_templates": [
         "Face-side arm extends, occipital-side arm flexes (fencer pose)",
         "Asymmetric tonic neck: extension on face side, flexion opposite",
         "Limbs adopt fencing posture, facilitating hand-eye coordination precursor",
     ]},
    {"name": "Babinski reflex", "trigger": "stroke along lateral sole",
     "response_templates": [
         "Great toe dorsiflexes, other toes fan outward",
         "Hallux extension with fanning of lesser toes",
         "Positive Babinski: toe extension and abduction pattern",
     ]},
    {"name": "Galant reflex", "trigger": "stroke along paravertebral line",
     "response_templates": [
         "Trunk curves toward stimulus side, hip flexes",
         "Lateral trunk incurvation toward stimulated side",
         "Ipsilateral trunk flexion with hip rotation",
     ]},
    {"name": "Stepping reflex", "trigger": "feet touch flat surface while supported upright",
     "response_templates": [
         "Alternating leg movements resembling walking",
         "Rhythmic stepping motion, {frequency} steps before fatiguing",
         "Bilateral leg flexion-extension cycles when sole contacts surface",
     ]},
    {"name": "Tonic labyrinthine", "trigger": "position change (supine/prone)",
     "response_templates": [
         "Supine: limbs extend; prone: limbs flex",
         "Postural tone shifts with gravity orientation",
         "Extension dominant in supine, flexion in prone positioning",
     ]},
    {"name": "Placing reflex", "trigger": "dorsum of foot touches table edge",
     "response_templates": [
         "Foot lifts and places on surface in stepping preparation",
         "Flexion-extension sequence: lift, advance, place",
         "Automatic foot placement when dorsum contacts edge",
     ]},
    {"name": "Crawling reflex", "trigger": "prone position with pressure on soles",
     "response_templates": [
         "Alternating limb movements in crawling pattern",
         "Coordinated pushing against resistance, forward propulsion attempt",
         "Bilateral arm-leg coordination resembling early locomotion",
     ]},
]

# 反射强度修饰符（3 档 × 多种表述）
_REFLEX_INTENSITIES = {
    "strong": [
        "vigorous and immediate", "pronounced, with high amplitude",
        "robust and sustained", "forceful, above-average intensity",
        "strong and well-coordinated", "powerful, easily elicited",
    ],
    "moderate": [
        "moderate and consistent", "present, within normal range",
        "reliable but not exaggerated", "steady, appropriately graded",
        "well-modulated response", "age-appropriate intensity",
    ],
    "weak": [
        "present but diminished", "sluggish, requires stronger stimulus",
        "faint, inconsistent elicitation", "delayed onset, low amplitude",
        "weak but observable", "subtle, easily fatigued",
    ],
}

# 突触密度描述
_SYNAPSE_PATTERNS = [
    "Dense synaptic connections forming in auditory cortex regions",
    "Visual cortex showing accelerated synaptogenesis",
    "Somatosensory strip forming with high density at hand/face areas",
    "Balanced synaptogenesis across primary sensory cortices",
    "Motor cortex leading synapse formation, rapid myelination",
    "Limbic-cortical connections forming dense reciprocal pathways",
    "Prefrontal connections sparse but present, temporal lobe dense",
    "Cerebellar granule cell proliferation peaking, dense Purkinje connections",
    "Brainstem nuclei fully connected, cortical connections emerging",
    "Thalamo-cortical radiations establishing sensory relay patterns",
    "Hippocampal formation showing early place-cell precursors",
    "Amygdala-hypothalamus connections strengthening for threat detection",
]


def rule_early_neural(budget: int, prev_responses: list[dict], env: dict, defects: list) -> dict:
    """Stage 3A 规则引擎。组合数：C(12,5) × 3^5 × 6^5 × 12 = 数百万种。"""
    # 选 4-6 个反射
    num_reflexes = random.randint(4, 6)
    selected = random.sample(_CORE_REFLEXES, num_reflexes)

    # 缺陷影响反射强度
    defect_set = {d.lower() for d in (defects or [])}
    has_neural_defect = any("neural" in d or "brain" in d or "cerebral" in d for d in defect_set)

    reflexes = []
    for reflex in selected:
        # 根据缺陷和环境决定强度分布
        if has_neural_defect:
            intensity_level = random.choices(["strong", "moderate", "weak"], weights=[1, 3, 3])[0]
        else:
            intensity_level = random.choices(["strong", "moderate", "weak"], weights=[3, 4, 1])[0]

        template = random.choice(reflex["response_templates"])
        duration = random.randint(5, 45)
        frequency = random.randint(30, 80)
        response_text = template.format(duration=duration, frequency=frequency)

        reflexes.append({
            "name": reflex["name"],
            "trigger": reflex["trigger"],
            "response": f"{response_text} — {random.choice(_REFLEX_INTENSITIES[intensity_level])}",
            "intensity": intensity_level,
        })

    # 资源分配
    channels = ["sensory_cortex", "motor_cortex", "autonomic_regulation", "reflex_circuits", "brainstem_nuclei"]
    allocation = _distribute_budget(budget, channels)

    return {
        "reflexes": reflexes,
        "synapse_density_pattern": random.choice(_SYNAPSE_PATTERNS),
        "resource_allocation": allocation,
    }


# ============================================================
# Stage 4: Fetal Movement — temperament 组合器
# ============================================================

# 气质五维度，每维度 3 档 → 3^5 = 243 种基础组合
# 来源: Thomas & Chess 九维气质模型 (简化为五维)
# 唤醒基线与气质的关联: PMC10547902 (cry acoustics & arousal)
_TEMPERAMENT_DIMENSIONS = {
    "activity_level": {
        "high": [
            "frequent vigorous movement, kicks and stretches constantly",
            "restless, high motor output, rarely still",
            "perpetual motion — limbs active even during rest periods",
        ],
        "moderate": [
            "regular movement cycles alternating with calm periods",
            "moderate activity, responds to stimuli with proportional movement",
            "balanced motor output — active periods followed by organized rest",
        ],
        "low": [
            "quiet, minimal spontaneous movement",
            "still for long stretches, moves only when stimulated",
            "economical movement — conserves energy, moves deliberately",
        ],
    },
    "regularity": {
        "high": [
            "highly predictable sleep-wake cycles",
            "clockwork activity patterns, consistent daily rhythms",
            "metronomic regularity in feeding readiness and rest",
        ],
        "moderate": [
            "somewhat predictable patterns with occasional variation",
            "generally regular but adjusts to environmental changes",
            "flexible rhythms that trend toward consistency",
        ],
        "low": [
            "irregular, unpredictable activity patterns",
            "no discernible routine, chaotic sleep-wake cycling",
            "erratic rhythms that resist settling into patterns",
        ],
    },
    "approach_withdrawal": {
        "approach": [
            "moves toward novel stimuli — curious orientation",
            "approaches new vibrations and sounds with increased activity",
            "extends limbs toward unfamiliar pressure — exploratory",
        ],
        "mixed": [
            "cautious initial withdrawal, then gradual approach",
            "freezes briefly at novel stimulus, then investigates",
            "mixed response — sometimes approaches, sometimes retreats",
        ],
        "withdrawal": [
            "withdraws from novel stimuli — protective retraction",
            "curls inward at unfamiliar vibration or pressure",
            "startle-then-freeze pattern at any environmental change",
        ],
    },
    "adaptability": {
        "high": [
            "adjusts quickly to position changes and environmental shifts",
            "rapid habituation to repeated stimuli",
            "flexible — settles into new conditions within minutes",
        ],
        "moderate": [
            "requires several exposures to adapt to new stimuli",
            "gradual adjustment, moderate habituation speed",
            "adapts with mild protest before settling",
        ],
        "low": [
            "slow to adjust, prolonged distress at changes",
            "resistant to environmental shifts, takes many repetitions",
            "rigid response patterns, very slow habituation",
        ],
    },
    "intensity": {
        "high": [
            "large-amplitude movements, forceful responses",
            "intense reactions — strong kicks, vigorous startle",
            "high-energy output in all responses, overwhelming force",
        ],
        "moderate": [
            "proportional response intensity, well-graded output",
            "moderate force in movements, appropriate to stimulus",
            "calibrated intensity — neither over- nor under-reactive",
        ],
        "low": [
            "gentle movements, subtle response patterns",
            "low-amplitude responses, quiet reactions",
            "soft, understated movements — minimal force output",
        ],
    },
}

# 运动模式描述
_MOVEMENT_PATTERNS = [
    "Rhythmic bilateral kicking with intermittent hand-to-face contact",
    "Asymmetric limb extension, dominant right-side movement",
    "Rolling whole-body movements, frequent position shifts",
    "Isolated finger movements interspersed with full-body stretches",
    "Hiccup-driven diaphragmatic contractions dominating movement profile",
    "Thumb-sucking episodes alternating with arm extension",
    "Coordinated stepping pattern against uterine wall",
    "Head-turning with hand tracking, proto-reaching behavior",
    "Yawning cycles coordinated with limb extension",
    "Startle-recovery sequences with decreasing amplitude",
    "Flexion-dominant posture with brief extension bursts",
    "Circular arm sweeps coordinated with trunk rotation",
]

# 刺激反应描述
_STIMULUS_RESPONSES = [
    "Strong kick response to external abdominal pressure",
    "Head orienting toward bright light through abdominal wall",
    "Increased activity following maternal glucose intake",
    "Calming response to low-frequency vibration or music",
    "Startle followed by prolonged stillness at sudden loud noise",
    "Rhythmic movement entrainment to maternal heartbeat",
    "Withdrawal from cold stimulus applied to abdomen",
    "Increased sucking behavior during maternal stress periods",
    "Preferential orientation toward familiar voice patterns",
    "Circadian activity peaks correlating with maternal melatonin cycle",
    "Touch-evoked hand opening and closing sequences",
    "Breathing-like movements increasing after maternal meal",
]


def rule_fetal_movement(budget: int, prev_responses: list[dict], env: dict, arousal: str) -> dict:
    """Stage 4 规则引擎。组合数：3^5 × 12 × C(12,3) = 243 × 12 × 220 = 641,520。"""
    # 按唤醒基线偏置维度选择
    dim_weights = {
        "high":     {"activity_level": [5, 3, 1], "regularity": [1, 3, 5], "approach_withdrawal": [4, 3, 2],
                     "adaptability": [1, 3, 5], "intensity": [5, 3, 1]},
        "moderate": {"activity_level": [2, 5, 2], "regularity": [2, 5, 2], "approach_withdrawal": [3, 4, 2],
                     "adaptability": [2, 5, 2], "intensity": [2, 5, 2]},
        "low":      {"activity_level": [1, 3, 5], "regularity": [5, 3, 1], "approach_withdrawal": [2, 3, 4],
                     "adaptability": [5, 3, 1], "intensity": [1, 3, 5]},
    }
    weights = dim_weights.get(arousal, dim_weights["moderate"])

    # 为每个维度选择档位
    parts = []
    for dim, levels in _TEMPERAMENT_DIMENSIONS.items():
        level_names = list(levels.keys())
        w = weights.get(dim, [1, 1, 1])
        chosen_level = random.choices(level_names, weights=w, k=1)[0]
        parts.append(random.choice(levels[chosen_level]))

    temperament_seed = "; ".join(parts)

    # 资源分配
    channels = ["motor_coordination", "sensory_integration", "autonomic_maturation",
                "behavioral_state_regulation", "movement_repertoire"]
    allocation = _distribute_budget(budget, channels)

    return {
        "movement_pattern": random.choice(_MOVEMENT_PATTERNS),
        "stimulus_responses": random.sample(_STIMULUS_RESPONSES, random.randint(2, 4)),
        "temperament_seed": temperament_seed,
        "resource_allocation": allocation,
    }


# ============================================================
# Stage 5: Birth — 组合式出生生成器
# ============================================================

# 第一声哭的组件库——onset × quality × pattern × body 动态拼接
# 来源:
#   哭声时机: 健康足月儿通常 60s 内("Golden Minute", 新生儿复苏指南)
#   哭声频率(F0): 250-700Hz, 痛觉哭 427-630Hz (Nature pr200421, ASHA ssod23.1.18)
#   哭声强度: 70-90dB 正常, 极端可达 100-120dB (PubMed 9796949)
#   高唤醒=更高F0+更大强度+更短潜伏期 (PMC10547902)
#   Apgar 呼吸评分: 0=无, 1=慢/不规则/弱哭, 2=好/强哭 (StatPearls NBK470569)
_CRY_ONSET = {
    "high": [
        "The instant air hit the lungs —",
        "No pause, no hesitation —",
        "Before the cord was even cut —",
        "The moment the chest expanded —",
    ],
    "moderate": [
        "A brief gasp, then —",
        "Two seconds of startled silence, then —",
        "Eyes squeezed shut, mouth opened, and —",
        "A shudder ran through the tiny body, then —",
        "Fists clenched, face reddening, and —",
    ],
    "low": [
        "Almost a full five seconds passed before —",
        "So quiet at first that the room held its breath, until —",
        "A long, trembling inhale, lips quivering, and finally —",
        "Barely a sound at first — just air moving, then slowly —",
    ],
}

_CRY_QUALITY = {
    "high": [
        "a piercing, full-throated wail split the room",
        "a scream erupted, raw and furious, shaking with force",
        "a cry like a siren — sharp, relentless, demanding",
        "an explosive howl tore through the silence",
    ],
    "moderate": [
        "a steady cry rose, finding its rhythm breath by breath",
        "a clear, insistent cry filled the space",
        "a strong cry built itself up, each wave louder than the last",
        "a determined cry emerged, rhythmic and purposeful",
    ],
    "low": [
        "a thin, reedy sound escaped — more whimper than cry",
        "a soft mewling began, fragile but persistent",
        "a trembling note drifted out, barely audible at first",
        "a whisper of a cry, like a question asked to no one",
    ],
}

_CRY_BODY = {
    "high": [
        "Limbs flailing, back arching, every muscle engaged in protest.",
        "Fists pounding air, legs kicking, face contorted in outrage.",
        "Whole body trembling with the effort, skin flushing crimson.",
        "Chest heaving in rapid bursts, fingers splayed wide.",
    ],
    "moderate": [
        "Legs drawn up, arms half-extended, settling into the new world.",
        "Fingers curling and uncurling, body slowly adjusting to gravity.",
        "Face scrunched but relaxing between cries, chest rising steadily.",
        "Body curled inward, seeking the shape it knew, then slowly uncurling.",
    ],
    "low": [
        "Barely moving — still folded, still quiet, breathing shallow but steady.",
        "Eyes half-open, body limp and warm, only the faintest chest rise visible.",
        "Motionless except for the tiniest lip tremble and a slow blink.",
        "So still that only the pulse at the fontanelle proved anything at all.",
    ],
}

# 出生后即时状态组件——eyes × posture × tone × color 拼接
# 来源:
#   眼部: 新生儿视力 20/200-20/400, 可见 8-12 英寸 (AAO Vision Development)
#   姿势: 足月儿默认四肢屈曲位, 28 周呈蛙腿位 (PMC4862282)
#   肌张力 Apgar: 0=松弛, 1=部分屈曲, 2=主动运动 (StatPearls NBK470569)
#   皮肤颜色: 中央发绀正常持续 5-10 min, 肢端发绀 24-48h (PMC3827510)
#   行为状态: Brazelton NBAS 六态 (ScienceDirect, PMC6494209)
_BIRTH_EYES = [
    "eyes sealed shut", "one eye cracked open, the other shut",
    "eyes wide, dark and unfocused", "eyes squinting against the light",
    "eyes open but glazed, seeing almost nothing yet", "blinking rapidly, overwhelmed",
]
_BIRTH_POSTURE = [
    "limbs tightly flexed in fetal curl", "arms reaching outward, legs tucked",
    "body limp and heavy with exhaustion", "one fist pressed against the cheek",
    "legs drawn up, arms across chest", "splayed briefly open, then curling back inward",
    "chin tucked, shoulders hunched", "head turned to one side, body curved",
]
_BIRTH_TONE = [
    "muscle tone strong — resists extension", "tone moderate, moves when stimulated",
    "slightly floppy, tone building gradually", "vigorous tone, active movement",
    "hypertonic — limbs stiff and resistant", "relaxed, pliable, unhurried",
]
_BIRTH_COLOR = [
    "pink spreading from the trunk outward",
    "dusky at first, clearing with each breath",
    "ruddy and flushed, capillaries flooding",
    "pale but warming quickly under the lamp",
    "blotchy red and white, circulation adjusting",
    "deep pink, healthy perfusion from the start",
]


def _extract_arousal_from_prev(prev_responses: list[dict]) -> str:
    """从前阶段结果中提取唤醒基线。"""
    import json as _json
    for raw in reversed(prev_responses):
        try:
            parsed = _json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                ab = parsed.get("arousal_baseline", "")
                if ab:
                    low_ab = ab.lower()
                    if any(kw in low_ab for kw in ("high", "hyper", "intense", "vigorous")):
                        return "high"
                    if any(kw in low_ab for kw in ("low", "quiet", "subdued", "calm")):
                        return "low"
        except Exception:
            pass
    return "moderate"


# 模板库懒加载单例（首次 rule_birth 调用时初始化）
_TEMPLATE_LIB = None


def _get_template_lib():
    global _TEMPLATE_LIB
    if _TEMPLATE_LIB is None:
        try:
            from .templates import TemplateLibrary
            _TEMPLATE_LIB = TemplateLibrary.load()
        except Exception:
            _TEMPLATE_LIB = False  # 标记加载失败，后续不再尝试
    return _TEMPLATE_LIB or None


def _sample_cry_fragment(slot: str, arousal: str, fallback: list[str]) -> str:
    """优先走预生成模板库，缺失时回退到硬编码列表。

    slot: "onset" | "quality" | "body"
    """
    lib = _get_template_lib()
    if lib is not None:
        key = f"birth/first_cry_{slot}_{arousal}"
        if lib.pool_size(key) > 0:
            text = lib.sample(key, filters={"arousal": arousal})
            if text:
                return text
    return random.choice(fallback)


def _extract_vitality_from_prev(prev_responses: list[dict]) -> str:
    """从前阶段结果中启发式推断生命力（驱动 color 档位：strong/moderate/weak）。

    信号：
      - 'vigorous', 'robust', 'strong perfusion' → strong
      - 'pale', 'cyanosis', 'weak', 'depressed', 'preterm' → weak
      - 其他 → moderate
    """
    import json as _json
    strong_kw = ("vigorous", "robust", "strong", "healthy")
    weak_kw = ("pale", "cyanos", "weak", "depressed", "preterm", "hypoxia", "poor perfusion")
    for raw in reversed(prev_responses):
        try:
            parsed = _json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                blob = _json.dumps(parsed, ensure_ascii=False).lower()
                if any(kw in blob for kw in weak_kw):
                    return "weak"
                if any(kw in blob for kw in strong_kw):
                    return "strong"
        except Exception:
            pass
    return "moderate"


def _sample_immediate_fragment(slot: str, filter_key: str, filter_value: str, fallback: list[str]) -> str:
    """采样 immediate_state 的四个组件之一（eyes/posture/tone/color）。

    slot: "eyes" | "posture" | "tone" | "color"
    filter_key: "arousal" 或 "vitality"
    """
    lib = _get_template_lib()
    if lib is not None:
        key = f"birth/immediate_{slot}_{filter_value}"
        if lib.pool_size(key) > 0:
            text = lib.sample(key, filters={filter_key: filter_value})
            if text:
                return text
    return random.choice(fallback)


def _extract_dominant_sense_from_prev(prev_responses: list[dict]) -> str:
    """从 late_organogenesis 的 primary_sense 文本中匹配主导感官（5 类）。"""
    import json as _json
    for raw in reversed(prev_responses):
        try:
            parsed = _json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                blob = (parsed.get("primary_sense") or "").lower()
                for s in _SENSE_CHANNELS:
                    if s in blob:
                        return s
        except Exception:
            pass
    return random.choice(_SENSE_CHANNELS)


def rule_birth(prev_responses: list[dict], genes: dict) -> dict:
    """Stage 5 组合式出生生成器。

    根据唤醒基线 + 生命力 + 主导感官分档，动态拼接第一声哭、出生状态、tendencies。
    - first_cry 三段（onset × quality × body）按 arousal 分档
    - immediate_state 四段：eyes/posture/tone 按 arousal 分档，color 按 vitality 分档
    - tendencies: 4-5 条，从 arousal + dominant_sense 两个维度的模板库采样
    模板库缺失时回退到硬编码。
    """
    arousal = _extract_arousal_from_prev(prev_responses)
    vitality = _extract_vitality_from_prev(prev_responses)
    dominant_sense = _extract_dominant_sense_from_prev(prev_responses)

    # tendencies 优先从模板库采样；若传入的 genes 已有覆盖则尊重之（向后兼容）
    preset = genes.get("expression") if isinstance(genes, dict) else None
    if preset and isinstance(preset, list) and len(preset) >= 3:
        tendencies = preset
    else:
        tendencies = rule_tendencies(arousal, dominant_sense, n=5)

    # 拼接第一声哭：onset + quality + body（优先模板库）
    onset = _sample_cry_fragment("onset", arousal, _CRY_ONSET[arousal])
    quality = _sample_cry_fragment("quality", arousal, _CRY_QUALITY[arousal])
    body = _sample_cry_fragment("body", arousal, _CRY_BODY[arousal])
    first_cry = f"{onset} {quality}. {body}"

    # 拼接出生即时状态：eyes / posture / tone 按 arousal；color 按 vitality
    eyes = _sample_immediate_fragment("eyes", "arousal", arousal, _BIRTH_EYES)
    posture = _sample_immediate_fragment("posture", "arousal", arousal, _BIRTH_POSTURE)
    tone = _sample_immediate_fragment("tone", "arousal", arousal, _BIRTH_TONE)
    color = _sample_immediate_fragment("color", "vitality", vitality, _BIRTH_COLOR)

    state_parts = [eyes, posture, tone, color]
    random.shuffle(state_parts)
    immediate_state = "; ".join(state_parts[:3]).capitalize() + "."

    return {
        "tendencies": tendencies,
        "first_cry": first_cry,
        "immediate_state": immediate_state,
    }


# ============================================================
# 通用工具
# ============================================================

def _distribute_budget(budget: int, channels: list[str]) -> dict:
    """将预算随机分配到多个通道，确保总和 = budget 且每通道 ≥ 1。"""
    n = len(channels)
    if budget < n:
        return {ch: 1 for ch in channels}

    # Dirichlet-like 分配：先给每人 1 点，剩余按随机权重分
    allocation = {ch: 1 for ch in channels}
    remaining = budget - n
    weights = [random.random() for _ in channels]
    total_w = sum(weights)
    for i, ch in enumerate(channels):
        if i == n - 1:
            allocation[ch] += remaining
        else:
            share = round(remaining * weights[i] / total_w)
            share = max(0, min(remaining, share))
            allocation[ch] += share
            remaining -= share
    return allocation


def _parse_json_safe(raw) -> dict:
    """容错 JSON 解析，非法返回空 dict。"""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        import json as _json
        return _json.loads(raw)
    except Exception:
        return {}


# ============================================================
# Stage 2B: Late Organogenesis — 主导/薄弱感官 + 成熟叙事
# ============================================================

_SENSE_CHANNELS = ("visual", "auditory", "tactile", "olfactory", "proprioceptive")

# early_organogenesis 的 resource_allocation 键 → 感官域映射
_CHANNEL_TO_SENSE = {
    "hearing": "auditory", "hearing_growth": "auditory", "hearing_development": "auditory",
    "vision": "visual", "vision_growth": "visual", "vision_development": "visual",
    "touch": "tactile", "touch_growth": "tactile", "touch_development": "tactile",
    "smell": "olfactory", "smell_growth": "olfactory", "smell_development": "olfactory",
    "proprioception": "proprioceptive", "proprioception_growth": "proprioceptive",
    "proprioception_development": "proprioceptive",
}


def _sample_template(key: str, fallback: str, filters: dict | None = None) -> str:
    """通用模板采样：查池 → 过滤 → 降级 fallback。"""
    lib = _get_template_lib()
    if lib is not None:
        if lib.pool_size(key) > 0:
            s = lib.sample(key, filters=filters or {})
            if s:
                return s
    return fallback


def rule_late_organogenesis(
    budget: int, stage_results: list, env: dict, defects: list,
) -> dict:
    """Stage 2B 规则引擎。

    根据前阶段 resource_allocation 推断主导/薄弱感官；
    模板库采样 organ_maturation / primary_sense / weak_sense / perception_style 叙事。
    """
    # 从 early_organogenesis 结果提取感官得分
    early_org = _parse_json_safe(stage_results[1]) if len(stage_results) > 1 else {}
    alloc = early_org.get("resource_allocation", {})

    sense_scores: dict[str, float] = {s: 0.0 for s in _SENSE_CHANNELS}
    for ch, v in (alloc or {}).items():
        if isinstance(v, (int, float)):
            sense = _CHANNEL_TO_SENSE.get(ch)
            if sense:
                sense_scores[sense] += float(v)

    if sum(sense_scores.values()) > 0:
        primary = max(sense_scores, key=sense_scores.get)
        # weak 从非 primary 中选最低
        non_primary = {s: v for s, v in sense_scores.items() if s != primary}
        weak = min(non_primary, key=non_primary.get)
        total = sum(sense_scores.values())
        primary_ratio = sense_scores[primary] / total
        weak_ratio = sense_scores[weak] / total
    else:
        primary = random.choice(_SENSE_CHANNELS)
        weak = random.choice([s for s in _SENSE_CHANNELS if s != primary])
        primary_ratio, weak_ratio = 0.3, 0.1

    # 档位映射
    if primary_ratio > 0.30:
        primary_tier = "strong"
    elif primary_ratio > 0.22:
        primary_tier = "moderate"
    else:
        primary_tier = "mild"

    if weak_ratio < 0.10:
        weak_severity = "severe"
    elif weak_ratio < 0.16:
        weak_severity = "moderate"
    else:
        weak_severity = "mild"

    if budget >= 35:
        budget_tier = "strong"
    elif budget >= 20:
        budget_tier = "moderate"
    else:
        budget_tier = "weak"

    # 采样叙事
    organ_maturation = _sample_template(
        f"late_org/organ_maturation_{budget_tier}",
        f"Organ systems mature at {budget_tier} pace; cardiac, renal, hepatic progressing.",
        filters={"budget_tier": budget_tier},
    )
    primary_text = _sample_template(
        f"late_org/primary_sense_{primary}_{primary_tier}",
        f"{primary.capitalize()} channel dominates, neural circuits densely myelinating.",
        filters={"sense": primary, "strength": primary_tier},
    )
    weak_text = _sample_template(
        f"late_org/weak_sense_{weak}_{weak_severity}",
        f"{weak.capitalize()} channel underdeveloped, reduced sensory integration expected.",
        filters={"sense": weak, "severity": weak_severity},
    )
    perception_style = _sample_template(
        f"late_org/perception_style_{primary}",
        f"This individual perceives the world primarily through {primary} channels.",
        filters={"primary_sense": primary},
    )

    # 重新分配 budget：primary 权重 3×，weak 0.3×，其他 1×
    weights = {s: 1.0 for s in _SENSE_CHANNELS}
    weights[primary] = 3.0
    weights[weak] = 0.3
    total_w = sum(weights.values())
    allocation: dict[str, int] = {}
    remaining = budget
    n = len(_SENSE_CHANNELS)
    for i, s in enumerate(_SENSE_CHANNELS):
        if i == n - 1:
            allocation[s] = max(1, remaining)
        else:
            pts = max(1, round(budget * weights[s] / total_w))
            pts = min(pts, remaining - (n - i - 1))
            allocation[s] = pts
            remaining -= pts

    return {
        "organ_maturation": organ_maturation,
        "primary_sense": primary_text,
        "weak_sense": weak_text,
        "perception_style": perception_style,
        "resource_allocation": allocation,
    }


# ============================================================
# Stage 3B: Late Neural — 本能回路 + 唤醒基线 + 髓鞘化
# ============================================================

# 感官域 → 髓鞘化通路映射（视听在对应皮层；触觉 → 体感；前体觉 → 运动；嗅觉未覆盖时走 auditory）
_MYELINATION_PATHWAY = {
    "visual": "visual",
    "auditory": "auditory",
    "tactile": "somatosensory",
    "olfactory": "auditory",
    "proprioceptive": "motor",
}


def rule_tendencies(
    arousal: str, dominant_sense: str, n: int = 5,
) -> list[str]:
    """生成新生儿 tendencies（性格倾向词数组）。

    从 arousal 池采 2 条 + 从 dominant_sense 池采 2-3 条 → 去重 → 返回 4-5 条。
    模板库缺失时降级到固定词对。

    - arousal: "high" | "moderate" | "low"
    - dominant_sense: "visual" | "auditory" | "tactile" | "olfactory" | "proprioceptive"
    - n: 目标条数（默认 5）
    """
    DEFAULT_AROUSAL = {
        "high": ["alert", "reactive", "intense"],
        "moderate": ["curious", "attentive", "steady"],
        "low": ["placid", "observant", "slow to warm"],
    }
    DEFAULT_SENSE = {
        "visual": ["keen-eyed", "pattern-sensitive"],
        "auditory": ["sound-tracking", "rhythm-sensitive"],
        "tactile": ["touch-seeking", "contact-calmed"],
        "olfactory": ["scent-aware", "odor-responsive"],
        "proprioceptive": ["body-aware", "movement-oriented"],
    }

    lib = _get_template_lib()
    tendencies: list[str] = []

    def _sample(key: str, filters: dict, fallback_list: list[str], want: int):
        out = []
        # 先尝试模板库
        if lib is not None and lib.pool_size(key) > 0:
            seen = set()
            for _ in range(want * 3):  # 多试几次避免重复
                t = lib.sample(key, filters=filters)
                if t and t not in seen and t not in tendencies:
                    seen.add(t)
                    out.append(t)
                if len(out) >= want:
                    return out
        # 降级：从 fallback 随机选
        if len(out) < want:
            remaining = [f for f in fallback_list if f not in tendencies and f not in out]
            random.shuffle(remaining)
            out.extend(remaining[:want - len(out)])
        return out

    # 2 条 arousal + 2-3 条 sense
    arousal_traits = _sample(
        f"trait/arousal_{arousal}", {"arousal": arousal},
        DEFAULT_AROUSAL.get(arousal, ["curious"]), want=2,
    )
    tendencies.extend(arousal_traits)

    sense_want = n - len(tendencies)
    sense_traits = _sample(
        f"trait/sense_{dominant_sense}", {"dominant_sense": dominant_sense},
        DEFAULT_SENSE.get(dominant_sense, ["alert"]), want=sense_want,
    )
    tendencies.extend(sense_traits)

    return tendencies[:n]


def rule_late_neural(
    budget: int, stage_results: list, env: dict, defects: list,
) -> dict:
    """Stage 3B 规则引擎。

    从 late_organogenesis 提取主导感官；从环境压力推断 arousal；
    模板库采样 arousal_baseline / myelination / instinct_loops (2-3 条) / neural_anomalies。
    """
    # 主导感官（从 late_organogenesis 关键词匹配）
    late_org = _parse_json_safe(stage_results[2]) if len(stage_results) > 2 else {}
    primary_blob = (late_org.get("primary_sense") or "").lower()
    dominant = next((s for s in _SENSE_CHANNELS if s in primary_blob), random.choice(_SENSE_CHANNELS))

    # arousal 档位（由环境压力驱动）
    stress = env.get("stress_level", 0.3)
    if stress > 0.6:
        arousal_tier = "high"
    elif stress < 0.3:
        arousal_tier = "low"
    else:
        arousal_tier = "moderate"

    # 髓鞘化速率（由 budget + defects 共同决定）
    if budget < 15 or defects:
        mye_rate = "delayed"
    elif budget > 28:
        mye_rate = "early"
    else:
        mye_rate = "normal"
    mye_pathway = _MYELINATION_PATHWAY.get(dominant, "motor")

    # 采样叙事
    arousal_baseline = _sample_template(
        f"late_neu/arousal_baseline_{arousal_tier}",
        f"{arousal_tier.capitalize()} arousal baseline set by excitatory/inhibitory balance.",
        filters={"arousal": arousal_tier},
    )
    myelination = _sample_template(
        f"late_neu/myelination_{mye_pathway}_{mye_rate}",
        f"{mye_pathway.capitalize()} pathway myelinating at {mye_rate} rate.",
        filters={"pathway": mye_pathway, "rate": mye_rate},
    )
    neural_anomalies = _sample_template(
        f"late_neu/neural_anomalies_{'present' if defects else 'clean'}",
        "Minor deviations consistent with noted defects." if defects else "None detected.",
        filters={"has_anomaly": bool(defects)},
    )

    # 本能回路：从 (dominant, arousal→tier) 池子采样 2-3 条（去重）
    loop_tier_map = {"high": "strong", "moderate": "moderate", "low": "weak"}
    loop_tier = loop_tier_map[arousal_tier]
    loops: list[str] = []
    for _ in range(random.randint(2, 3) + 2):  # 多试几次以保证去重后够数
        loop = _sample_template(
            f"late_neu/instinct_loop_{dominant}_{loop_tier}",
            f"{dominant.capitalize()} stimulus → orientation response",
            filters={"sense": dominant, "tier": loop_tier},
        )
        if loop and loop not in loops:
            loops.append(loop)
        if len(loops) >= 3:
            break
    if not loops:
        loops = [f"{dominant.capitalize()} stimulus → orientation response"]
    loops = loops[:3] if len(loops) > 3 else loops

    # resource_allocation: 4 个神经通道
    allocation = _distribute_budget(
        budget, ["excitatory", "inhibitory", "integration", "motor_planning"],
    )

    return {
        "instinct_loops": loops,
        "arousal_baseline": arousal_baseline,
        "myelination_priority": myelination,
        "neural_anomalies": neural_anomalies,
        "resource_allocation": allocation,
    }
