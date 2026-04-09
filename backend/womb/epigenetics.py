"""
表观遗传：甲基化噪声模型。

同卵双胞胎因甲基化差异发展出不同性格倾向——
这是真实生物学中个体差异的重要来源。
叶酸是甲基供体，叶酸缺乏 → 甲基化异常 → 基因表达漂移。

[INPUT]: genotype dict、环境 dict（nutrients、stress、maternal_age）
[OUTPUT]: 导出 generate_methylation_profile, apply_epigenetic_modification, format_epigenetics_for_prompt
[POS]: womb/ 的表观遗传子系统，被 __init__.py 消费，使同基因个体产生可追溯差异
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random
import math


# ============================================================
# 甲基化敏感性配置
# 每个性状的甲基化敏感度：0=不受影响，1=高度敏感
# 数据启发：性格/代谢性状受表观遗传影响远大于结构性状
# ============================================================

METHYLATION_SENSITIVITY = {
    "eye_color": 0.05,          # 结构性状，几乎不受甲基化影响
    "hair_type": 0.10,
    "hair_color": 0.08,
    "skin_tone": 0.05,
    "height_tendency": 0.30,    # 身高受多基因+表观遗传双重影响
    "metabolism_type": 0.45,    # 代谢高度敏感（Barker 假说）
    "blood_type_abo": 0.0,     # 血型不受甲基化影响
    "earwax_type": 0.0,
    "dimples": 0.02,
    "freckles": 0.15,          # 色素沉着受甲基化调控
}

# 环境因素对全局甲基化水平的影响
# 正值 = 促进甲基化（基因沉默）；负值 = 去甲基化（基因激活）
ENV_METHYLATION_EFFECTS = {
    "folate_deficiency": -0.25,     # 叶酸是甲基供体，缺乏→低甲基化
    "stress_high": 0.15,           # 压力→糖皮质激素受体启动子高甲基化
    "toxin_exposure": -0.20,       # 重金属等干扰 DNA 甲基转移酶
    "advanced_maternal_age": 0.10,  # 母龄→全局甲基化漂移
}


def _compute_env_methylation_bias(env: dict) -> float:
    """
    从环境计算全局甲基化偏移。

    返回值 [-1, 1]：负值=低甲基化趋势，正值=高甲基化趋势。
    """
    bias = 0.0

    # 叶酸水平
    nutrients = env.get("nutrients", {})
    folate = nutrients.get("folate", 0.65)
    if folate < 0.35:
        bias += ENV_METHYLATION_EFFECTS["folate_deficiency"] * (1 - folate / 0.35)

    # 压力
    stress = env.get("stress", "mild")
    if stress in ("moderate", "severe"):
        factor = 0.6 if stress == "moderate" else 1.0
        bias += ENV_METHYLATION_EFFECTS["stress_high"] * factor

    # 毒素
    toxin = env.get("toxin_exposure", "none")
    if toxin in ("moderate", "severe"):
        factor = 0.5 if toxin == "moderate" else 1.0
        bias += ENV_METHYLATION_EFFECTS["toxin_exposure"] * factor

    # 母龄
    age = env.get("maternal_age_factor", "optimal")
    if age in ("advanced", "very_advanced"):
        factor = 0.5 if age == "advanced" else 1.0
        bias += ENV_METHYLATION_EFFECTS["advanced_maternal_age"] * factor

    return max(-1.0, min(1.0, bias))


def generate_methylation_profile(genotype: dict, env: dict) -> dict:
    """
    为个体生成甲基化图谱。

    同基因 + 同环境的两次调用会产生不同结果（随机噪声）。
    这就是同卵双胞胎差异的来源。

    Returns:
        {trait_name: methylation_level}
        methylation_level ∈ [-1, 1]：
            负值 → 该性状基因去甲基化（倾向激活/增强表达）
            正值 → 该性状基因高甲基化（倾向沉默/减弱表达）
    """
    env_bias = _compute_env_methylation_bias(env)
    profile = {}

    for trait, sensitivity in METHYLATION_SENSITIVITY.items():
        if trait not in genotype or sensitivity == 0:
            profile[trait] = 0.0
            continue

        # 随机噪声 + 环境偏移
        noise = random.gauss(0, sensitivity)
        value = noise + env_bias * sensitivity
        profile[trait] = round(max(-1.0, min(1.0, value)), 3)

    return profile


def apply_epigenetic_modification(phenotype: dict, methylation: dict) -> dict:
    """
    将甲基化修饰应用到表现型。

    对于连续性状（height、metabolism），甲基化可以移位表达方向。
    对于离散性状（eye_color），甲基化只有足够强时才可能翻转。

    Returns:
        修改后的 phenotype dict + epigenetic_notes 记录
    """
    modified = dict(phenotype)
    notes = []

    # 身高：甲基化偏移
    height_meth = methylation.get("height_tendency", 0)
    if abs(height_meth) > 0.2:
        current = phenotype.get("genetic_height_tendency", phenotype.get("height_tendency"))
        if current:
            direction = "taller" if height_meth < -0.2 else "shorter"
            notes.append(f"height_tendency: epigenetic shift toward {direction} (methylation={height_meth:+.3f})")
            # 实际修改：如果甲基化足够强，可以移位一档
            scale = ["short", "average", "tall"]
            if current in scale and abs(height_meth) > 0.35:
                idx = scale.index(current)
                new_idx = max(0, min(2, idx + (-1 if height_meth > 0 else 1)))
                if new_idx != idx:
                    modified[f"genetic_height_tendency"] = scale[new_idx]
                    notes.append(f"  → shifted from {current} to {scale[new_idx]}")

    # 代谢：甲基化偏移（Barker 假说——宫内营养不良→节俭表型）
    meta_meth = methylation.get("metabolism_type", 0)
    if abs(meta_meth) > 0.25:
        current = phenotype.get("genetic_metabolism_type", phenotype.get("metabolism_type"))
        if current:
            direction = "faster" if meta_meth < -0.25 else "slower (thrifty phenotype)"
            notes.append(f"metabolism_type: epigenetic shift toward {direction} (methylation={meta_meth:+.3f})")
            scale = ["slow", "moderate", "fast"]
            if current in scale and abs(meta_meth) > 0.4:
                idx = scale.index(current)
                new_idx = max(0, min(2, idx + (-1 if meta_meth > 0 else 1)))
                if new_idx != idx:
                    modified[f"genetic_metabolism_type"] = scale[new_idx]
                    notes.append(f"  → shifted from {current} to {scale[new_idx]}")

    # 雀斑：甲基化影响色素表达
    freckle_meth = methylation.get("freckles", 0)
    if freckle_meth < -0.15:
        current = phenotype.get("genetic_freckles")
        if current == "absent":
            notes.append(f"freckles: low methylation may activate freckle genes (methylation={freckle_meth:+.3f})")

    modified["_epigenetic_notes"] = notes
    modified["_methylation_profile"] = methylation
    return modified


def format_epigenetics_for_prompt(methylation: dict, env: dict) -> str:
    """生成 LLM prompt 注入文本：表观遗传状态。"""
    env_bias = _compute_env_methylation_bias(env)

    lines = ["## Epigenetic Profile"]

    if abs(env_bias) > 0.1:
        direction = "hypomethylation" if env_bias < 0 else "hypermethylation"
        cause = []
        nutrients = env.get("nutrients", {})
        if nutrients.get("folate", 0.65) < 0.35:
            cause.append("folate deficiency (methyl donor shortage)")
        if env.get("stress") in ("moderate", "severe"):
            cause.append("maternal stress (glucocorticoid receptor methylation)")
        if env.get("toxin_exposure") in ("moderate", "severe"):
            cause.append("toxin exposure (DNMT disruption)")
        cause_text = ", ".join(cause) if cause else "environmental factors"
        lines.append(f"- Global trend: {direction} (bias {env_bias:+.2f}) due to {cause_text}")

    significant = [(t, v) for t, v in methylation.items() if abs(v) > 0.15]
    if significant:
        lines.append("- Significantly modified traits:")
        for trait, value in significant:
            effect = "silenced/reduced" if value > 0 else "activated/enhanced"
            lines.append(f"  - {trait}: methylation {value:+.3f} → expression {effect}")

    if len(lines) == 1:
        lines.append("- Methylation profile within normal range. No significant epigenetic modifications.")

    return "\n".join(lines)
