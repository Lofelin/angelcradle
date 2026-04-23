"""
子宫实时图谱叙事层——"业务计算结果 → graph_delta" 的集中翻译。

接受 stages.py / 各业务子系统（hormones/nutrients/teratogen/vitals/fate）的纯数值输出，
调用 graph_emit.py 的纯函数构造对应的节点/边/delta。业务文件不 import 本模块，
本模块单向依赖业务数据字段，零侧效、可单元测试。

为什么不在业务文件里直接 emit（背离提案原文"业务函数返回 graph_delta"字面）：
  - 7 个业务文件各自 emit 会导致 schema 知识分散，新增边类型要改多处
  - 集中在这里更符合"业务即图 = 图从业务自然流出"的精神——业务不操心图，图自动随业务
  - 回滚友好：删除本文件 + stages.py 几处调用即可完全移除图谱能力
  - 本模块是**翻译层不是 reducer**：不做图上的推理/聚合，只做字段映射，符合提案反对的不是这种形态

[INPUT]: stage_index (1-7), stage_name, 各业务子系统的字典输出
[OUTPUT]: 导出 build_init_delta / build_stage_delta / build_fate_event_delta / build_miscarriage_delta
[POS]: womb/ 的图谱叙事层, 被 stages.py 的 express_stream 调用
[PROTOCOL]: 变更时更新此头部, 然后检查 CLAUDE.md
"""

from __future__ import annotations

from typing import Any

from . import graph_emit as ge
from .teratogen import TERATOGEN_STAGE_RISK


# ============================================================
# 阶段映射（提案 design.md §2：stage_name → stage_index）
# ============================================================

STAGE_NAME_TO_INDEX = {
    "zygote": 1,
    "early_organogenesis": 2,
    "late_organogenesis": 3,
    "early_neural": 4,
    "late_neural": 5,
    "fetal_movement": 6,
    "birth": 7,
}


def stage_index_of(stage_name: str) -> int:
    return STAGE_NAME_TO_INDEX.get(stage_name, 0)


# ============================================================
# 器官/反射/体征静态元数据（对齐样本 JSON）
# ============================================================

ORGAN_META = {
    "heart":  {"formation_stage": 2, "maturation_stage": 3, "neural": False,
               "narrative": "心脏：S2 首次跳动 → S3 四腔成型",
               "narrative_en": "Heart: beats first at S2 → four chambers at S3"},
    "brain":  {"formation_stage": 2, "maturation_stage": 5, "neural": True,
               "narrative": "大脑：跨 S2-S5 持续发育",
               "narrative_en": "Brain: develops continuously across S2-S5"},
    "lung":   {"formation_stage": 3, "maturation_stage": 7, "neural": False,
               "narrative": "肺：S3 结构成型 → S7 表面活性物质",
               "narrative_en": "Lung: structure forms at S3 → surfactant at S7"},
    "liver":  {"formation_stage": 2, "maturation_stage": None, "neural": False,
               "narrative": "肝：S2 起始造血",
               "narrative_en": "Liver: hematopoiesis begins at S2"},
    "kidney": {"formation_stage": 3, "maturation_stage": None, "neural": False,
               "narrative": "肾：S3 产生尿液汇入羊水",
               "narrative_en": "Kidney: produces urine into amniotic fluid at S3"},
    "eye":    {"formation_stage": 3, "maturation_stage": None, "neural": False,
               "narrative": "眼：S3 视杯形成 → S6 感光",
               "narrative_en": "Eye: optic cup forms at S3 → photosensitive at S6"},
    "ear":    {"formation_stage": 4, "maturation_stage": None, "neural": False,
               "narrative": "耳：S4 耳蜗成熟 → S5 可听母声",
               "narrative_en": "Ear: cochlea matures at S4 → hears mother at S5"},
}

VITAL_META = {
    "hr":        {"unit": "bpm",     "neural": False, "observes": "heart",
                  "narrative": "胎心率", "narrative_en": "Fetal heart rate"},
    "weight":    {"unit": "g",       "neural": False,
                  "narrative": "体重", "narrative_en": "Body weight"},
    "length":    {"unit": "mm",      "neural": False,
                  "narrative": "身长", "narrative_en": "Crown-to-rump length"},
    "amniotic":  {"unit": "ml",      "neural": False,
                  "narrative": "羊水量", "narrative_en": "Amniotic fluid volume"},
    "movement":  {"unit": "kicks/h", "neural": True,  "observes": "brain",
                  "narrative": "胎动频率", "narrative_en": "Fetal movement frequency"},
    "bp":        {"unit": "mmHg",    "neural": False,
                  "narrative": "血压", "narrative_en": "Blood pressure"},
    "oxygen":    {"unit": "%",       "neural": False, "observes": "lung",
                  "narrative": "血氧饱和度", "narrative_en": "Oxygen saturation"},
}

HORMONE_META = {
    "cortisol": {"narrative": "皮质醇：应激激素，跨阶段影响心脏与大脑",
                 "narrative_en": "Cortisol: stress hormone, affects heart and brain across stages"},
    "thyroid":  {"narrative": "甲状腺素：碘依赖，神经发育窗口关键",
                 "narrative_en": "Thyroxine: iodine-dependent, critical for neural development window"},
    "sex":      {"narrative": "性激素：决定性别分化",
                 "narrative_en": "Sex hormone: determines sexual differentiation"},
    "hcg":      {"narrative": "hCG：胎盘健康标志物",
                 "narrative_en": "hCG: placental health marker"},
}

NUTRIENT_META = {
    "folate":  {"narrative": "叶酸：神经管闭合关键",
                "narrative_en": "Folate: critical for neural tube closure"},
    "iodine":  {"narrative": "碘：甲状腺素合成前体",
                "narrative_en": "Iodine: precursor of thyroxine synthesis"},
    "iron":    {"narrative": "铁：氧输送",
                "narrative_en": "Iron: oxygen transport"},
    "dha":     {"narrative": "DHA：突触膜构建",
                "narrative_en": "DHA: builds synaptic membranes"},
    "calcium": {"narrative": "钙：骨骼钙化与心律",
                "narrative_en": "Calcium: skeletal calcification and cardiac rhythm"},
}

TERATOGEN_META = {
    "alcohol":   {"narrative": "酒精：跨器官致畸",
                  "narrative_en": "Alcohol: multi-organ teratogen"},
    "smoke":     {"narrative": "烟草：缺氧 + 低出生体重",
                  "narrative_en": "Tobacco: hypoxia and low birth weight"},
    "pm25":      {"narrative": "PM2.5：胎盘血流下降",
                  "narrative_en": "PM2.5: reduces placental blood flow"},
    "stress":    {"narrative": "慢性压力：皮质醇上拉",
                  "narrative_en": "Chronic stress: elevates cortisol"},
    "drug":      {"narrative": "药物暴露",
                  "narrative_en": "Drug exposure"},
    "infection": {"narrative": "感染：TORCH 风险",
                  "narrative_en": "Infection: TORCH pathogen risk"},
}

# 反射（stage_index → (name, label, narrative_zh, narrative_en)）
REFLEX_EMERGE = {
    4: [("moro", "Moro Reflex", "依赖脊髓-脑干环路", "Depends on spinal-brainstem circuitry")],
    5: [("sucking", "Sucking Reflex", "依赖脑干", "Depends on brainstem")],
}


# ============================================================
# 激素 → 器官的因果映射（samples 对齐）
# ============================================================

def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _hormone_organ_edges(stage_index: int, hormones: dict, hormone_effects: dict) -> list[dict]:
    """根据当前激素数值和效应，emit 激素→器官 MODULATES 边 + hormone→baby AFFECTS 边。
    **降低阈值**以保证每阶段都至少产出激素相关边（解决 S1 空图问题）。"""
    edges: list[dict] = []

    cortisol = _safe_float(hormones.get("cortisol"))
    if cortisol > 0.0:  # 降低阈值：只要激素存在就连边
        w_heart = min(1.0, max(0.15, cortisol * 0.45))
        w_brain = min(1.0, max(0.15, cortisol * 0.5))
        edges.append(ge.edge(
            "hormone_cortisol", "organ_heart", "MODULATES",
            stage_index=stage_index, weight=round(w_heart, 3),
            level_at=round(cortisol, 3), polarity="negative",
            description=f"皮质醇 {cortisol:.2f} 调控心脏发育",
        ))
        edges.append(ge.edge(
            "hormone_cortisol", "organ_brain", "MODULATES",
            stage_index=stage_index, weight=round(w_brain, 3),
            level_at=round(cortisol, 3), polarity="negative",
            description=f"皮质醇 {cortisol:.2f} 影响神经元迁移/突触",
        ))

    thyroid = _safe_float(hormones.get("thyroid_t4"))
    if thyroid > 0.0:
        thyroid_deficient = bool(hormones.get("thyroid_deficient", False))
        polarity = "negative" if thyroid_deficient or thyroid < 0.5 else "positive"
        w_brain = 0.75 if polarity == "positive" else 0.55
        edges.append(ge.edge(
            "hormone_thyroid", "organ_brain", "MODULATES",
            stage_index=stage_index, weight=w_brain,
            level_at=round(thyroid, 3), polarity=polarity,
            description="T4 支持髓鞘化" if polarity == "positive" else "T4 偏低影响神经元迁移",
        ))

    sex_h = _safe_float(hormones.get("sex_hormones"))
    if stage_index == 4 and sex_h > 0.3:
        edges.append(ge.edge(
            "hormone_sex", "baby_this", "DETERMINES",
            stage_index=stage_index, weight=0.95, level_at=round(sex_h, 3),
            description="性别分化完成",
        ))

    hcg = _safe_float(hormones.get("hcg"))
    if hcg > 0.0:
        edges.append(ge.edge(
            "hormone_hcg", "baby_this", "AFFECTS",
            stage_index=stage_index, weight=round(min(1.0, max(0.2, hcg * 1.2)), 3),
            level_at=round(hcg, 3),
            description="hCG 维持妊娠" if stage_index <= 2 else "hCG 稳态",
        ))

    return edges


# ============================================================
# 营养素/毒素的 edges
# ============================================================

# 敏感器官映射（stage_index 相关）
NUTRIENT_TARGETS = {
    "folate":  [("organ_brain", "FEEDS", "叶酸支持神经管闭合", (1, 2, 3))],
    "iodine":  [("hormone_thyroid", "FEEDS", "碘是 T4 合成前体", (3, 4, 5))],
    "iron":    [("organ_brain", "FEEDS", "铁保障氧输送", (4, 5, 6, 7))],
    "dha":     [("organ_brain", "FEEDS", "DHA 构建突触膜", (5, 6, 7))],
    "calcium": [("organ_heart", "FEEDS", "钙稳定心肌节律", (6, 7)),
                ("baby_this", "FEEDS", "钙支持骨骼钙化", (6, 7))],
}

TERATOGEN_TARGETS = {
    "alcohol":   [("organ_heart", "DAMAGES", "乙醇代谢物干扰心管融合", (2,)),
                  ("organ_brain", "DAMAGES", "乙醇抑制神经元迁移", (2, 3, 4))],
    "smoke":     [("organ_lung", "DAMAGES", "烟草烟雾降低肺泡前体", (3, 4, 5, 6, 7)),
                  ("baby_this", "DAMAGES", "烟草引起低出生体重", (3, 4, 5, 6, 7))],
    "pm25":      [("organ_lung", "DAMAGES", "PM2.5 降低肺泡前体增殖", (3, 4))],
    "stress":    [("hormone_cortisol", "CAUSES", "慢性压力拉高皮质醇", (3, 4, 5, 6))],
    "drug":      [("baby_this", "DAMAGES", "药物暴露风险", (2, 3, 4))],
    "infection": [("organ_brain", "DAMAGES", "TORCH 感染影响脑", (2, 3, 4))],
}


def _nutrient_edges(stage_index: int, nutrient_effects: dict, env_nutrients: dict | None = None) -> list[dict]:
    """
    输入:
      nutrient_effects: get_stage_nutrient_effects 返回 {budget_penalty, risk_effects, deficient_nutrients}
      env_nutrients: env["nutrients"] 原始数值字典（0.0-1.0）

    所有 5 种营养素每阶段都 emit INTAKE 边（连到 baby_this），确保节点不孤岛。
    FEEDS 边只在敏感窗口内 emit。
    """
    edges: list[dict] = []
    deficient = set((nutrient_effects or {}).get("deficient_nutrients") or [])
    env_n = env_nutrients or {}

    for nutrient, targets in NUTRIENT_TARGETS.items():
        # 从环境 nutrients dict 拿实际数值，缺省 0.5（中性）
        level_val = _safe_float(env_n.get(nutrient), default=0.5)
        is_deficient = nutrient in deficient
        status = (
            "insufficient" if is_deficient
            else "sufficient" if level_val >= 0.7
            else "low"
        )

        # INTAKE 边：每阶段一次，不受敏感窗口限制
        edges.append(ge.edge(
            f"nutrient_{nutrient}", "baby_this", "INTAKE",
            stage_index=stage_index, level=round(level_val, 3), status=status,
        ))

        # 针对敏感器官/激素的 FEEDS 边（只在敏感窗口内）
        for target, etype, desc, sensitive_stages in targets:
            if stage_index not in sensitive_stages:
                continue
            critical = is_deficient or level_val < 0.5
            weight = 0.9 if critical else 0.55
            edges.append(ge.edge(
                f"nutrient_{nutrient}", target, etype,
                stage_index=stage_index, weight=weight, level_at=round(level_val, 3),
                description=desc + ("（关键不足期）" if critical else ""),
            ))

    return edges


def _teratogen_edges(stage_index: int, stage_name: str, toxin_types: list[str]) -> list[dict]:
    """
    从 TERATOGEN_STAGE_RISK（毒素×阶段风险倍数，1.0=基线，最高~4.0）反查每个
    toxin 在当期的归一化暴露强度 exposure ∈ [0,1]，再由此推导 EXPOSED/DAMAGES 边。

    toxin_types 是当前环境中存在的毒素 id 列表。
    """
    edges: list[dict] = []

    for ter in toxin_types or []:
        raw = TERATOGEN_STAGE_RISK.get(ter, {}).get(stage_name, 1.0)
        # 倍数 [1.0, 4.0] → 暴露强度 [0.0, 1.0]；有该毒素但当期无数据时给低暴露
        exposure = round(max(0.0, min(1.0, (raw - 1.0) / 3.0)), 3) if raw > 1.0 else 0.1
        # EXPOSED：胚胎承担
        edges.append(ge.edge(
            f"teratogen_{ter}", "baby_this", "EXPOSED",
            stage_index=stage_index, exposure=round(exposure, 3),
            description=TERATOGEN_META.get(ter, {}).get("narrative", ""),
        ))
        # 针对器官 DAMAGES（仅敏感窗口）
        for target, etype, desc, sensitive_stages in TERATOGEN_TARGETS.get(ter, []):
            if stage_index not in sensitive_stages:
                continue
            w = round(min(1.0, exposure * 2.0), 3)
            if w < 0.1:
                continue
            edges.append(ge.edge(
                f"teratogen_{ter}", target, etype,
                stage_index=stage_index, weight=w,
                description=desc,
            ))
    return edges


# ============================================================
# 体征 edges
# ============================================================

def _vital_nodes_and_edges(stage_index: int, vitals: dict) -> tuple[list[dict], list[dict]]:
    """vitals 字段 → vital→baby MEASURED 边 + 必要时首次出现的节点"""
    edges: list[dict] = []
    nodes: list[dict] = []

    field_to_vital = {
        "heart_rate_bpm":         ("hr",       "bpm"),
        "weight_grams":           ("weight",   "g"),
        "length_mm":              ("length",   "mm"),
        "amniotic_fluid_index":   ("amniotic", "cm"),
        "movement_score":         ("movement", "score"),
        "blood_pressure_systolic":("bp",       "mmHg"),
        "oxygen_saturation":      ("oxygen",   "%"),
    }

    for field, (vname, unit) in field_to_vital.items():
        v = vitals.get(field)
        if v is None or (isinstance(v, (int, float)) and v <= 0):
            continue
        val = round(v, 2) if isinstance(v, float) else v
        if field == "oxygen_saturation" and isinstance(v, float):
            val = round(v * 100, 1)  # 0.98 → 98.0
            unit = "%"
        edges.append(ge.edge(
            f"vital_{vname}", "baby_this", "MEASURED",
            stage_index=stage_index, v=val, unit=unit,
        ))
    return nodes, edges


# ============================================================
# 器官发育 edges（baby → organ DEVELOPS, phase=FORMS/MATURES）
# ============================================================

def _development_edges(stage_index: int) -> list[dict]:
    edges: list[dict] = []
    for organ, meta in ORGAN_META.items():
        if meta["formation_stage"] == stage_index:
            edges.append(ge.edge(
                "baby_this", f"organ_{organ}", "DEVELOPS",
                stage_index=stage_index, weight=0.85, phase="FORMS",
                description=f"{meta['narrative']}（形成期）",
            ))
        if meta.get("maturation_stage") == stage_index:
            edges.append(ge.edge(
                "baby_this", f"organ_{organ}", "DEVELOPS",
                stage_index=stage_index, weight=1.0, phase="MATURES",
                description=f"{meta['narrative']}（成熟期）",
            ))
    return edges


def _reflex_nodes_edges(stage_index: int) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    for item in REFLEX_EMERGE.get(stage_index, []):
        name, label, narrative_zh, narrative_en = item[0], item[1], item[2], item[3] if len(item) > 3 else None
        nodes.append(ge.node_reflex(
            name, emerges_stage=stage_index, label=label,
            narrative_zh=narrative_zh, narrative_en=narrative_en,
        ))
        edges.append(ge.edge(
            "baby_this", f"reflex_{name}", "ACQUIRES",
            stage_index=stage_index, description=f"{label} 可观测",
        ))
        edges.append(ge.edge(
            f"reflex_{name}", "organ_brain", "EMERGES_IN",
            stage_index=stage_index, description=narrative_zh,
        ))
    return nodes, edges


# ============================================================
# 公共 API：初始化 delta
# ============================================================

def build_init_delta(
    *,
    baby_id: str,
    species: str,
    sex: str,
    birthplace_code: str | None = None,
    birthplace_name: str | None = None,
    birthplace_meta: dict | None = None,
    father_genome: dict | None = None,
    mother_genome: dict | None = None,
    methylation_meta: dict | None = None,
) -> dict:
    """S1 开始时调用：播种身份层结构节点 + 与 Baby 的连接"""
    nodes: list[dict] = []
    edges: list[dict] = []

    # Baby + Species
    nodes.append(ge.node_baby(baby_id, sex=sex))
    nodes.append(ge.node_species(species))
    edges.append(ge.edge(f"species_{species}", "baby_this", "EXPRESSES_AS", weight=1.0,
                         description="蓝图表达为个体"))

    # Parents
    nodes.append(ge.node_parent("father", **_thin(father_genome, limit=4, exclude={"side"})))
    nodes.append(ge.node_parent("mother", **_thin(mother_genome, limit=4, exclude={"side"})))
    edges.append(ge.edge("genome_father", "baby_this", "INHERITS_FROM", weight=1.0,
                         description="父方 23 条染色体"))
    edges.append(ge.edge("genome_mother", "baby_this", "INHERITS_FROM", weight=1.0,
                         description="母方 23 条染色体"))

    # Methylation
    nodes.append(ge.node_methylation(**_thin(methylation_meta, limit=4, exclude={"kind"})))
    edges.append(ge.edge("genome_father", "methylation", "CONTRIBUTES_TO", description="父方印记基因"))
    edges.append(ge.edge("genome_mother", "methylation", "CONTRIBUTES_TO", description="母方印记基因"))
    edges.append(ge.edge("methylation", "baby_this", "EPIGENETIC_OF", weight=1.0,
                         description="甲基化图谱绑定个体"))

    # Birthplace
    if birthplace_code:
        nodes.append(ge.node_birthplace(
            birthplace_code, name=birthplace_name,
            **_thin(birthplace_meta, limit=4, exclude={"code", "name"})))
        edges.append(ge.edge(
            f"birthplace_{birthplace_code}", "baby_this", "BORN_AT", weight=1.0,
            description=f"出生地：{birthplace_name or birthplace_code}",
        ))

    # 预播 4 种激素节点（首阶段一次性，后续 update track）
    for hname, meta in HORMONE_META.items():
        nodes.append(ge.node_hormone(
            hname, narrative_zh=meta["narrative"], narrative_en=meta.get("narrative_en"),
        ))

    # 预播 5 种营养素 + 7 个器官 + 7 个体征节点
    for nname, meta in NUTRIENT_META.items():
        nodes.append(ge.node_nutrient(
            nname, narrative_zh=meta["narrative"], narrative_en=meta.get("narrative_en"),
        ))
    for oname, ometa in ORGAN_META.items():
        nodes.append(ge.node_organ(
            oname,
            formation_stage=ometa["formation_stage"],
            maturation_stage=ometa["maturation_stage"],
            neural=ometa["neural"],
            narrative_zh=ometa["narrative"], narrative_en=ometa.get("narrative_en"),
        ))
    for vname, vmeta in VITAL_META.items():
        nodes.append(ge.node_vital(
            vname, unit=vmeta["unit"],
            neural=vmeta.get("neural", False),
            narrative_zh=vmeta["narrative"], narrative_en=vmeta.get("narrative_en"),
        ))
        # OBSERVES 固定边
        obs = vmeta.get("observes")
        if obs:
            edges.append(ge.edge(f"vital_{vname}", f"organ_{obs}", "OBSERVES",
                                 description=f"{vmeta['narrative']}观测 {obs}"))

    return ge.delta_add(nodes=nodes, edges=edges)


# ============================================================
# 公共 API：每阶段 delta
# ============================================================

def build_stage_delta(
    *,
    stage_name: str,
    stage_num: int,
    hormones: dict,
    hormone_effects: dict | None = None,
    nutrient_effects: dict | None = None,
    env_nutrients: dict | None = None,
    teratogen_risk: dict | None = None,
    toxin_types: list[str] | None = None,
    vitals: dict | None = None,
    narrative_text: str | None = None,
) -> dict:
    stage_index = stage_num  # express_stream 的 stage_num = i+1 = 1..7
    edges: list[dict] = []
    nodes: list[dict] = []

    # 激素作用
    edges.extend(_hormone_organ_edges(stage_index, hormones, hormone_effects or {}))
    # 激素 track 追加（前端 mergeGraph 识别 track_append）
    update_nodes = []
    for hname, hkey in (("cortisol", "cortisol"), ("thyroid", "thyroid_t4"),
                        ("sex", "sex_hormones"), ("hcg", "hcg")):
        if hkey in hormones:
            update_nodes.append(ge.track_append(
                f"hormone_{hname}", stage_index=stage_index,
                level=round(float(hormones[hkey]), 3),
            ))

    # 营养/毒素
    if nutrient_effects:
        edges.extend(_nutrient_edges(stage_index, nutrient_effects, env_nutrients))
    # 毒素节点首次出现按需（toxin_types）
    for ter in toxin_types or []:
        # add_nodes 幂等：已存在覆盖不会重复
        tmeta = TERATOGEN_META.get(ter, {})
        nodes.append(ge.node_teratogen(
            ter, narrative_zh=tmeta.get("narrative", ""),
            narrative_en=tmeta.get("narrative_en"),
        ))
    if toxin_types:
        edges.extend(_teratogen_edges(stage_index, stage_name, toxin_types))

    # 体征
    if vitals:
        vnodes, vedges = _vital_nodes_and_edges(stage_index, vitals)
        nodes.extend(vnodes)
        edges.extend(vedges)

    # 器官发育 + 反射
    edges.extend(_development_edges(stage_index))
    rnodes, redges = _reflex_nodes_edges(stage_index)
    nodes.extend(rnodes)
    edges.extend(redges)

    # 气质（S6）
    if stage_index == 6:
        # 简化：movement_score 高则 activity temperament
        move = (vitals or {}).get("movement_score", 5)
        score = min(1.0, move / 10.0) if move else 0.5
        nodes.append(ge.node_temperament("activity", score=round(score, 2), defined_stage=6))
        edges.append(ge.edge(
            "baby_this", "temperament", "CRYSTALLIZES",
            stage_index=6, description=f"气质定型（activity={score:.2f}）",
        ))

    # 叙事节点
    if narrative_text:
        nodes.append(ge.node_narrative(stage_index, narrative_text))
        edges.append(ge.edge(
            f"narr_s{stage_index}", "baby_this", "DESCRIBES",
            stage_index=stage_index, description=f"S{stage_index} 阶段叙事",
        ))

    return ge.merge_deltas(
        ge.delta_add(nodes=nodes, edges=edges),
        ge.delta_update(nodes=update_nodes) if update_nodes else {},
    )


# ============================================================
# 公共 API：命运事件 delta
# ============================================================

def build_fate_event_delta(
    event_type: str,
    stage_num: int,
    result: Any,
    *,
    probability: float | None = None,
    defect_type: str | None = None,
    defect_severity: str = "minor",
    causes: list[tuple[str, int, float, str]] | None = None,
    narrative_zh: str | None = None,
) -> dict:
    """
    通用命运事件 delta 构造：event 节点 + 可选 defect + CAUSED_BY 归因链

    causes: [(cause_node_id, cause_stage_index, weight, description)]
    """
    nodes = [ge.node_event(
        event_type, stage_index=stage_num, result=result,
        probability=probability, narrative_zh=narrative_zh,
    )]
    edges: list[dict] = []
    event_id = f"event_{event_type}_s{stage_num}"

    if defect_type:
        nodes.append(ge.node_defect(
            defect_type, severity=defect_severity,
            narrative_zh=f"缺陷：{defect_type.replace('_', ' ')}（{defect_severity}）",
        ))
        edges.append(ge.edge(event_id, f"defect_{defect_type}", "RESULTS_IN", weight=1.0))
        edges.append(ge.edge(
            f"defect_{defect_type}", "baby_this", "AFFECTS",
            weight=0.3 if defect_severity == "minor" else 0.6,
            description=f"{defect_severity} 缺陷影响个体",
        ))

    for cause_node, cause_stage, weight, desc in (causes or []):
        edges.append(ge.edge(
            cause_node, event_id, "CAUSED_BY",
            stage_index=cause_stage, weight=weight, description=desc,
        ))

    return ge.delta_add(nodes=nodes, edges=edges)


def build_narrative_delta(stage_num: int, text: str) -> dict:
    """单独 emit 一个阶段的叙事节点 + 到 baby 的 DESCRIBES 边（fate_birth 组）"""
    node = ge.node_narrative(stage_num, text)
    edge = ge.edge(
        f"narr_s{stage_num}", "baby_this", "DESCRIBES",
        stage_index=stage_num, description=f"S{stage_num} 阶段叙事",
    )
    return ge.delta_add(nodes=[node], edges=[edge])


def build_miscarriage_delta(stage_num: int, cause: str) -> dict:
    """流产专用：event + TerminatedBy + baby status 更新"""
    event_id = f"event_miscarriage_s{stage_num}"
    nodes = [ge.node_event("miscarriage", stage_num, result="triggered",
                           narrative_zh=f"S{stage_num} 流产触发：{cause}")]
    edges = [ge.edge(
        event_id, "baby_this", "TerminatedBy",
        stage_index=stage_num, description=f"流产原因：{cause}",
    )]
    update_nodes = [{
        "id": ge.make_node_uuid("baby_this"),
        "metadata": {"status": "miscarried", "terminated_at_stage": stage_num},
    }]
    return ge.merge_deltas(
        ge.delta_add(nodes=nodes, edges=edges),
        ge.delta_update(nodes=update_nodes),
    )


# ============================================================
# 内部工具
# ============================================================

def _thin(d: dict | None, limit: int = 4, exclude: set[str] | None = None) -> dict:
    """把任意字典裁剪为前 limit 个简单字段（避免 metadata 里塞大对象），排除冲突键"""
    if not d:
        return {}
    ex = exclude or set()
    out = {}
    for k, v in d.items():
        if k in ex:
            continue
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        if len(out) >= limit:
            break
    return out
