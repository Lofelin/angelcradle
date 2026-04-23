"""
摇篮图谱节点双语文本词典——给 dimension / phase / progression / capability /
milestone / need 等节点补充 label + narrative.primary + narrative.scientific。

[INPUT]: dim / (dim,stage) / phase_name / cap_key / milestone_slug / trigger
[OUTPUT]: hydrate_dimension / hydrate_phase_dim / hydrate_progression /
          hydrate_capability / hydrate_milestone / hydrate_need / hydrate_trait /
          DIMENSION_META / PHASE_DIM_META / PROGRESSION_META /
          CAPABILITY_META / MILESTONE_META / NEED_META
[POS]: cradle/ 的本地化文本层，被 graph_emit 的 bootstrap / business 代码消费
[PROTOCOL]: 变更时更新此头部，然后检查 cradle/CLAUDE.md

设计原则
========
- 每个 META 字典值是 dict(label_zh?, label_en?, narrative_zh?, narrative_en?,
  scientific_zh?, scientific_en?)——缺失字段由调用方做 fallback。
- 未命中 key 的节点仍可正常构造，只是没有 narrative——避免单点词条缺失阻塞图谱生成。
- capability / milestone 不一一列全，只为主要 BSID / Vineland / Piaget 标志能力
  写精细说明，其余靠 `_template_capability(cap_key, dim)` 生成通用文本。
- 科学参考（scientific 字段）只在领域知识明确的维度/能力上填写，避免伪严谨。
"""

from __future__ import annotations

from cradle.ontology import capability_dimension


# ============================================================
# 1. DIMENSION_META
# ============================================================

DIMENSION_META: dict[str, dict] = {
    "motor": {
        "label_zh": "运动发育",
        "label_en": "Motor Development",
        "narrative_zh": "粗大动作到精细动作：反射 → 抓握 → 爬站走 → 工具使用 → 精细协调。",
        "narrative_en": "Gross to fine motor: reflexes → grasp → crawl/stand/walk → tool use → fine coordination.",
        "scientific_zh": "Bayley-III Motor Scale（粗动作 + 精细动作）",
        "scientific_en": "Bayley-III Motor Scale (gross + fine motor)",
    },
    "cognitive": {
        "label_zh": "认知发育",
        "label_en": "Cognitive Development",
        "narrative_zh": "从反射循环反应到前运算期的符号与因果思维——Piaget 六阶段的前两大期。",
        "narrative_en": "From reflex circular reactions to preoperational symbolic/causal thinking — Piaget's first two major stages.",
        "scientific_zh": "Piaget 认知发展阶段理论（sensorimotor → preoperational）",
        "scientific_en": "Piaget's stages (sensorimotor → preoperational)",
    },
    "language": {
        "label_zh": "语言发育",
        "label_en": "Language Development",
        "narrative_zh": "哭泣 → 咕咕 → 咿呀 → 首词 → 双词 → 句子 → 叙事。",
        "narrative_en": "Cry → cooing → babble → first words → two-word → sentence → narrative.",
        "scientific_zh": "McArthur-Bates CDI 词汇发展里程碑",
        "scientific_en": "McArthur-Bates CDI vocabulary milestones",
    },
    "social": {
        "label_zh": "社交发育",
        "label_en": "Social Development",
        "narrative_zh": "印记 → 识别 → 依附 → 平行游戏 → 合作 → 道德意识。",
        "narrative_en": "Imprint → recognize → attachment → parallel play → cooperative → moral sense.",
        "scientific_zh": "Vineland-3 Interpersonal Subdomain + Bowlby attachment theory",
        "scientific_en": "Vineland-3 Interpersonal subdomain + Bowlby attachment theory",
    },
    "emotional": {
        "label_zh": "情绪发育",
        "label_en": "Emotional Development",
        "narrative_zh": "反射情感 → 基本情绪分化 → 自我意识情绪 → 同理心 → 情绪调节。",
        "narrative_en": "Reflex affect → primary emotions → self-conscious emotions → empathy → regulation.",
        "scientific_zh": "Lewis 自我意识情绪理论 + 情绪调节发育轨迹",
        "scientific_en": "Lewis self-conscious emotions theory + emotion regulation trajectory",
    },
    "physical": {
        "label_zh": "体格发育",
        "label_en": "Physical Development",
        "narrative_zh": "身高 / 体重 / 生理节律 / 如厕独立 / 分房睡——可量化的生理成长曲线。",
        "narrative_en": "Height / weight / circadian / toilet training / independent sleep — quantifiable growth.",
        "scientific_zh": "WHO MGRS 生长曲线（0-5 岁）",
        "scientific_en": "WHO MGRS growth standards (0-5 yr)",
    },
}


# ============================================================
# 2. PHASE_DIM_META
# ============================================================

# key = (dim, stage)
PHASE_DIM_META: dict[tuple[str, str], dict] = {
    # motor
    ("motor", "neonatal"):      {"narrative_zh": "纯反射期：惊跳、吸吮、握持。", "narrative_en": "Pure reflex era: startle, sucking, grasp."},
    ("motor", "early_infant"):  {"narrative_zh": "头控、翻身、手部发现。",       "narrative_en": "Head control, rolling, hand discovery."},
    ("motor", "late_infant"):   {"narrative_zh": "坐起、爬行、扶站。",           "narrative_en": "Sitting, crawling, supported standing."},
    ("motor", "toddler"):       {"narrative_zh": "独立行走、跑、简单工具使用。",   "narrative_en": "Walking, running, simple tool use."},
    ("motor", "preschool"):     {"narrative_zh": "精细动作成熟，协调性成人化。",  "narrative_en": "Fine motor maturation, adult-like coordination."},
    # cognitive
    ("cognitive", "sensorimotor_reflex"): {"narrative_zh": "反射循环反应，世界只是感官流。", "narrative_en": "Reflex circular reactions; world is sensory flux."},
    ("cognitive", "primary_circular"):    {"narrative_zh": "初级循环反应：发现自己可以让事情重复发生。", "narrative_en": "Primary circular reactions: discovering self can repeat."},
    ("cognitive", "coordination"):        {"narrative_zh": "手段-目的协调，对象恒常性萌发。", "narrative_en": "Means-ends coordination, object permanence dawns."},
    ("cognitive", "symbolic"):            {"narrative_zh": "符号思维 + 假装游戏，语言与思维挂钩。", "narrative_en": "Symbolic thought + pretend play; language hooks thought."},
    ("cognitive", "preoperational"):      {"narrative_zh": "前运算期：类比、时间概念、直观但非逻辑。", "narrative_en": "Preoperational: analogy, time concept, intuitive not logical."},
    # language
    ("language", "cry"):         {"narrative_zh": "以哭声为唯一通道表达所有内在状态。", "narrative_en": "Cry as the single channel for all inner states."},
    ("language", "cooing"):      {"narrative_zh": "元音流 + 社交凝视同步——前语言社交萌发。",   "narrative_en": "Vowel flow + social gaze in sync — prelinguistic social bud."},
    ("language", "babble"):      {"narrative_zh": "音节重复（mamama/bababa），语音方案在成形。",   "narrative_en": "Reduplicated babble (mamama/bababa); phonological scheme forming."},
    ("language", "first_words"): {"narrative_zh": "首批实义词出现，通常指向主照护者与常见物。", "narrative_en": "First content words, often primary caregiver + frequent objects."},
    ("language", "sentence"):    {"narrative_zh": "双词到简单句，语法雏形在对话反馈中生长。",   "narrative_en": "Two-word to simple sentence; grammar sprouts in dialogue."},
    ("language", "narrative"):   {"narrative_zh": "讲故事能力上线——时间线、因果、主角意图。",     "narrative_en": "Storytelling emerges — timeline, causality, protagonist intent."},
    # social
    ("social", "imprint"):       {"narrative_zh": "气味与声音的印记，最原始的他者识别。",       "narrative_en": "Scent + voice imprint; the most primitive 'other'."},
    ("social", "recognize"):     {"narrative_zh": "面孔识别 + 社交微笑。",                    "narrative_en": "Face recognition + social smile."},
    ("social", "attachment"):    {"narrative_zh": "依附定型，陌生人焦虑峰值。",                 "narrative_en": "Attachment consolidates; stranger anxiety peaks."},
    ("social", "parallel_play"): {"narrative_zh": "平行游戏——旁边玩但各玩各的。",              "narrative_en": "Parallel play — side-by-side but separate."},
    ("social", "cooperative"):   {"narrative_zh": "合作游戏与角色扮演，共享规则。",              "narrative_en": "Cooperative play + role play; shared rules."},
    ("social", "moral"):         {"narrative_zh": "道德意识萌发，判断公平与伤害。",              "narrative_en": "Moral sense sprouts; judging fairness and harm."},
    # emotional
    ("emotional", "reflex_affect"):    {"narrative_zh": "反射性情感：饱暖舒适、饥饿不适。",     "narrative_en": "Reflex affect: full/warm vs hungry/uncomfortable."},
    ("emotional", "primary_emotions"): {"narrative_zh": "基本情绪分化：喜怒哀惧、惊奇厌恶。",     "narrative_en": "Primary emotions differentiate: joy, anger, sadness, fear, surprise, disgust."},
    ("emotional", "self_awareness"):   {"narrative_zh": "自我意识情绪：羞耻、骄傲、嫉妒。",       "narrative_en": "Self-conscious emotions: shame, pride, jealousy."},
    ("emotional", "empathy"):          {"narrative_zh": "真正的同理心与情感视角采择。",           "narrative_en": "True empathy + affective perspective taking."},
    ("emotional", "regulation"):       {"narrative_zh": "主动情绪调节——延迟满足、重评。",       "narrative_en": "Active emotion regulation — delay, reappraisal."},
    # physical
    ("physical", "neonate"):        {"narrative_zh": "新生体型：皮下脂肪薄，睡眠占主导。",      "narrative_en": "Neonate: thin subcutaneous fat, sleep-dominant."},
    ("physical", "early_infant"):   {"narrative_zh": "体重翻倍，脑容量快速扩张。",              "narrative_en": "Weight doubles; rapid brain volume expansion."},
    ("physical", "toddler_body"):   {"narrative_zh": "体型从婴儿转向幼儿，如厕训练窗口。",        "narrative_en": "Body shifts from infant to toddler; toilet training window."},
    ("physical", "preschool_body"): {"narrative_zh": "身高增长主导，换牙开始。",                  "narrative_en": "Height growth dominates; permanent teeth begin."},
}


# ============================================================
# 3. PROGRESSION_META （12 个）
# ============================================================

PROGRESSION_META: dict[str, dict] = {
    "neonatal":           {"label_zh": "新生期",     "narrative_zh": "全反射、纯生理、完全依赖——世界是感官模糊流。",
                           "narrative_en": "All reflex, pure physiology, total dependence — the world is a sensory blur."},
    "sensory_awakening":  {"label_zh": "感官觉醒",   "narrative_zh": "开始追声追视，社交微笑登场。",
                           "narrative_en": "Sound/light tracking begins; social smile emerges."},
    "body_discovery":     {"label_zh": "身体发现",   "narrative_zh": "发现自己的手、抓握、翻身——身体是第一个工具。",
                           "narrative_en": "Hands discovered, grasp + roll — the body is the first tool."},
    "object_permanence":  {"label_zh": "对象恒常",   "narrative_zh": "物体消失仍存在——世界开始有记忆，陌生人焦虑峰值。",
                           "narrative_en": "Objects persist when hidden — the world gains memory; stranger anxiety peaks."},
    "locomotion":         {"label_zh": "移动",       "narrative_zh": "爬行开启探索，首个实义词出现。",
                           "narrative_en": "Crawling opens exploration; first meaningful words emerge."},
    "first_word":         {"label_zh": "首词",       "narrative_zh": "词汇 10-50，工具使用，独立行走。",
                           "narrative_en": "Vocab 10-50, tool use, independent walking."},
    "language_explosion": {"label_zh": "语言爆发",   "narrative_zh": "双词句、假装游戏、镜中自识。",
                           "narrative_en": "Two-word phrases, pretend play, mirror self-recognition."},
    "why_phase":          {"label_zh": "为什么期",   "narrative_zh": "完整句 + 无尽为什么 + 情绪风暴。",
                           "narrative_en": "Full sentences + endless whys + emotional storms."},
    "social_budding":     {"label_zh": "社交萌芽",   "narrative_zh": "同伴意识、角色扮演、道德萌芽。",
                           "narrative_en": "Peer awareness, role play, moral bud."},
    "rule_understanding": {"label_zh": "规则理解",   "narrative_zh": "知道规则存在，开始试探边界。",
                           "narrative_en": "Rules exist and boundaries get tested."},
    "abstract_beginning": {"label_zh": "抽象开端",   "narrative_zh": "类比 + 时间概念 + 简单假设推理。",
                           "narrative_en": "Analogy + time concept + simple hypothetical reasoning."},
    "independence":       {"label_zh": "独立",       "narrative_zh": "'我自己来'，有观点、能辩论，准备进入世界。",
                           "narrative_en": "'I'll do it myself' — has opinions, argues, ready for the world."},
}


# ============================================================
# 4. CAPABILITY_META（精细说明，未命中走模板）
# ============================================================

CAPABILITY_META: dict[str, dict] = {
    # 标志性 milestone-grade capability
    "walking": {
        "label_zh": "独立行走",
        "label_en": "Walking",
        "narrative_zh": "双足离地自主移动——运动发育里程碑。",
        "narrative_en": "Bipedal independent locomotion — motor milestone.",
    },
    "first_words": {
        "label_zh": "首词",
        "label_en": "First Words",
        "narrative_zh": "首批指称性词汇：mama / dada / 常见物。",
        "narrative_en": "First referential words: mama / dada / frequent objects.",
    },
    "object_permanence": {
        "label_zh": "对象恒常性",
        "label_en": "Object Permanence",
        "narrative_zh": "理解物体消失后依然存在——Piaget coordination 阶段的认知飞跃。",
        "narrative_en": "Understanding objects persist when unseen — Piaget coordination-stage leap.",
    },
    "self_recognition": {
        "label_zh": "镜中自识",
        "label_en": "Self-Recognition",
        "narrative_zh": "镜面测试通过，自我意识的决定性标志。",
        "narrative_en": "Passes mirror test — decisive marker of self-awareness.",
    },
    "pretend_play": {
        "label_zh": "假装游戏",
        "label_en": "Pretend Play",
        "narrative_zh": "把香蕉当电话——符号思维上线。",
        "narrative_en": "Banana-as-phone — symbolic thought online.",
    },
    "social_smile": {
        "label_zh": "社交微笑",
        "label_en": "Social Smile",
        "narrative_zh": "针对照护者面孔的定向微笑——依附系统的第一次对话。",
        "narrative_en": "Directed smile at caregiver's face — first dialogue of attachment system.",
    },
    "stranger_anxiety": {
        "label_zh": "陌生人焦虑",
        "label_en": "Stranger Anxiety",
        "narrative_zh": "对陌生面孔回避哭泣——依附分化的健康标志。",
        "narrative_en": "Avoidance/crying to strangers — healthy marker of attachment differentiation.",
    },
    "emotional_storms": {
        "label_zh": "情绪风暴",
        "label_en": "Emotional Storms",
        "narrative_zh": "tantrum 高发期——情绪强度远超调节能力。",
        "narrative_en": "Tantrum-prone era — emotion intensity outstrips regulation.",
    },
    "why_questions": {
        "label_zh": "无尽为什么",
        "label_en": "Why Questions",
        "narrative_zh": "对因果链的主动探询——认知发动机上线。",
        "narrative_en": "Active inquiry into causal chains — cognitive engine on.",
    },
    "self_regulation": {
        "label_zh": "自我调节",
        "label_en": "Self-Regulation",
        "narrative_zh": "延迟满足 + 情绪重评 + 注意调控。",
        "narrative_en": "Delayed gratification + reappraisal + attention control.",
    },
}


def _template_capability(cap_key: str) -> dict:
    """未在 CAPABILITY_META 显式列出的能力：按 dim 生成通用说明。"""
    dim = capability_dimension(cap_key)
    pretty = cap_key.replace("_", " ").title()
    dim_zh = DIMENSION_META[dim]["label_zh"]
    dim_en = DIMENSION_META[dim]["label_en"]
    return {
        "label_zh": pretty,
        "label_en": pretty,
        "narrative_zh": f"{dim_zh}维度能力：{pretty}。",
        "narrative_en": f"{dim_en} dimension capability: {pretty}.",
    }


# ============================================================
# 5. MILESTONE_META（选常见，未覆盖走模板）
# ============================================================

MILESTONE_META: dict[str, dict] = {
    "first_steps": {
        "label_zh": "迈出第一步",
        "label_en": "First Steps",
        "narrative_zh": "独立迈出连续两步——运动自主性里程碑。",
        "narrative_en": "Two unsupported steps in a row — motor autonomy milestone.",
    },
    "first_word": {
        "label_zh": "第一个词",
        "label_en": "First Word",
        "narrative_zh": "首个带指称的词汇——语言里程碑。",
        "narrative_en": "First referential word — language milestone.",
    },
    "naming": {
        "label_zh": "命名仪式",
        "label_en": "Naming Ceremony",
        "narrative_zh": "照护者正式命名——身份坐标的锚点。",
        "narrative_en": "Caregiver bestows name — identity anchor.",
    },
    "separation_success": {
        "label_zh": "分离成功",
        "label_en": "Separation Success",
        "narrative_zh": "短时分离未引发崩溃——依附安全的可操作标志。",
        "narrative_en": "Brief separation without collapse — operational safe-attachment marker.",
    },
    "toilet_trained": {
        "label_zh": "如厕独立",
        "label_en": "Toilet Trained",
        "narrative_zh": "主动感知 + 控制排泄——自我照料的基础技能。",
        "narrative_en": "Active sense + control of elimination — basic self-care.",
    },
    "capability_recovered": {
        "label_zh": "能力恢复",
        "label_en": "Capability Recovered",
        "narrative_zh": "压力回退的能力在照护下重建，有时更强韧。",
        "narrative_en": "Regressed capability rebuilt with care, sometimes strengthened.",
    },
    "world_ready": {
        "label_zh": "世界就绪",
        "label_en": "World Ready",
        "narrative_zh": "通过所有硬性条件，可离开摇篮进入世界。",
        "narrative_en": "All hard conditions met; can leave cradle and enter the world.",
    },
}


def _template_milestone(slug: str) -> dict:
    pretty = slug.replace("_", " ").title()
    return {"label_zh": pretty, "label_en": pretty}


# ============================================================
# 6. NEED_META（19 种 trigger）
# ============================================================

NEED_META: dict[str, dict] = {
    # 生理类
    "hunger":        {"label_zh": "饥饿",    "label_en": "Hunger",        "urgency": "physiological"},
    "thirst":        {"label_zh": "口渴",    "label_en": "Thirst",        "urgency": "physiological"},
    "sleepy":        {"label_zh": "困倦",    "label_en": "Sleepy",        "urgency": "physiological"},
    "diaper":        {"label_zh": "尿布",    "label_en": "Diaper",        "urgency": "physiological"},
    "pain":          {"label_zh": "疼痛",    "label_en": "Pain",          "urgency": "physiological"},
    "teething":      {"label_zh": "出牙",    "label_en": "Teething",      "urgency": "physiological"},
    "cold":          {"label_zh": "寒冷",    "label_en": "Cold",          "urgency": "physiological"},
    "hot":           {"label_zh": "燥热",    "label_en": "Hot",           "urgency": "physiological"},
    # 情感类
    "fear":          {"label_zh": "恐惧",    "label_en": "Fear",          "urgency": "emotional"},
    "lonely":        {"label_zh": "孤独",    "label_en": "Lonely",        "urgency": "emotional"},
    "frustrated":    {"label_zh": "挫败",    "label_en": "Frustrated",    "urgency": "emotional"},
    "overstimulated":{"label_zh": "过度刺激","label_en": "Overstimulated","urgency": "emotional"},
    "comfort":       {"label_zh": "求抚慰",  "label_en": "Seeking Comfort","urgency": "emotional"},
    "separation":    {"label_zh": "分离焦虑","label_en": "Separation Anxiety","urgency": "emotional"},
    # 社交类
    "curious":       {"label_zh": "好奇",    "label_en": "Curious",       "urgency": "social"},
    "playful":       {"label_zh": "想玩",    "label_en": "Playful",       "urgency": "social"},
    "attention":     {"label_zh": "求关注",  "label_en": "Attention",     "urgency": "social"},
    "share":         {"label_zh": "想分享",  "label_en": "Wants to Share","urgency": "social"},
    "autonomy":      {"label_zh": "求自主",  "label_en": "Seeks Autonomy","urgency": "social"},
}


# ============================================================
# hydrate helpers：把 META 字段转成 node_* 构造器 kwargs
# ============================================================

def _to_kwargs(meta: dict | None) -> dict:
    if not meta:
        return {}
    out = {}
    for k, v in meta.items():
        if k in ("label_zh", "label_en",
                 "narrative_zh", "narrative_en",
                 "scientific_zh", "scientific_en"):
            out[k] = v
    return out


def hydrate_dimension(dim: str) -> dict:
    """返回可直接 **解包 给 node_dimension 的 kwargs。"""
    meta = DIMENSION_META.get(dim, {})
    kw = {}
    if "label_zh" in meta:
        kw["display_zh"] = meta["label_zh"]
    if "label_en" in meta:
        kw["display_en"] = meta["label_en"]
    if "narrative_zh" in meta:
        kw["narrative_zh"] = meta["narrative_zh"]
    if "narrative_en" in meta:
        kw["narrative_en"] = meta["narrative_en"]
    return kw


def hydrate_phase_dim(dim: str, stage: str) -> dict:
    """可直接 **解包 给 node_phase_dim 的 kwargs。"""
    meta = PHASE_DIM_META.get((dim, stage), {})
    return {k: v for k, v in meta.items()
            if k in ("narrative_zh", "narrative_en",
                     "scientific_zh", "scientific_en")}


def hydrate_progression(phase_name: str) -> dict:
    """可直接 **解包 给 node_progression 的 kwargs（含 display_name override）。"""
    meta = PROGRESSION_META.get(phase_name, {})
    kw = {}
    if "label_zh" in meta:
        # progression 的 display_name 用英文；label_zh 只进 narrative
        pass
    if "narrative_zh" in meta:
        kw["narrative_zh"] = meta["narrative_zh"]
    if "narrative_en" in meta:
        kw["narrative_en"] = meta["narrative_en"]
    return kw


def hydrate_capability(cap_key: str) -> dict:
    """可直接 **解包 给 node_capability 的 kwargs。"""
    meta = CAPABILITY_META.get(cap_key) or _template_capability(cap_key)
    return {k: v for k, v in meta.items()
            if k in ("narrative_zh", "narrative_en",
                     "scientific_zh", "scientific_en")}


def hydrate_milestone(slug: str) -> dict:
    meta = MILESTONE_META.get(slug) or _template_milestone(slug)
    kw = {}
    if "label_en" in meta:
        kw["label"] = meta["label_en"]
    if "narrative_zh" in meta:
        kw["narrative_zh"] = meta["narrative_zh"]
    if "narrative_en" in meta:
        kw["narrative_en"] = meta["narrative_en"]
    return kw


def hydrate_need(trigger: str) -> dict:
    meta = NEED_META.get(trigger, {})
    kw = {}
    if "urgency" in meta:
        kw["urgency"] = meta["urgency"]
    if "label_zh" in meta:
        kw["narrative_zh"] = meta["label_zh"]
    if "label_en" in meta:
        kw["narrative_en"] = meta["label_en"]
    return kw


# ============================================================
# 辅助：全需求清单（按 urgency 分组），供初始化一次性 emit 使用
# ============================================================

def all_known_needs() -> list[tuple[str, str]]:
    """返回 [(trigger, urgency), ...]，按 NEED_META 顺序。"""
    return [(t, m["urgency"]) for t, m in NEED_META.items() if "urgency" in m]


__all__ = [
    "DIMENSION_META", "PHASE_DIM_META", "PROGRESSION_META",
    "CAPABILITY_META", "MILESTONE_META", "NEED_META",
    "hydrate_dimension", "hydrate_phase_dim", "hydrate_progression",
    "hydrate_capability", "hydrate_milestone", "hydrate_need",
    "all_known_needs",
]
