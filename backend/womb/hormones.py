"""
简化激素轴：4 条通路的阶段基线 + 环境修正。

通路：
  1. 皮质醇 (cortisol) — stress → HPA 轴编程 → 出生后焦虑基线
  2. 甲状腺 (thyroid_t4) — iodine → 神经发育 → 认知上限
  3. 性激素 (sex_hormones) — 性分化 → 脑masculinization/feminization
  4. hCG — 胎盘健康标志物 → 流产风险

数据来源：Williams Obstetrics 26th Ed, Speroff's Clinical Endocrinology

[INPUT]: 当前阶段、环境 dict、性别、并发症
[OUTPUT]: 导出 compute_hormones, get_hormone_effects, format_hormones_for_prompt
[POS]: womb/ 的激素子系统，被 stages.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random


# ============================================================
# 激素阶段基线（归一化到 0-1 范围，1=峰值）
# ============================================================

HORMONE_STAGE_BASELINES = {
    "cortisol": {
        # 胎儿皮质醇：1-2 trimester 低，3rd trimester 升高（肺成熟）
        "zygote": 0.05,
        "early_organogenesis": 0.10,
        "late_organogenesis": 0.15,
        "early_neural": 0.20,
        "late_neural": 0.30,
        "fetal_movement": 0.55,
        "birth": 0.85,  # 分娩时皮质醇激增
    },
    "thyroid_t4": {
        # 胎儿甲状腺 12 周开始活跃，之前依赖母体
        "zygote": 0.05,              # 完全依赖母体
        "early_organogenesis": 0.10,
        "late_organogenesis": 0.25,   # 甲状腺开始形成
        "early_neural": 0.60,        # 甲状腺活跃，关键窗口
        "late_neural": 0.80,
        "fetal_movement": 0.90,
        "birth": 0.95,
    },
    "sex_hormones": {
        # 雄性：testosterone 在 8-24 周激增（脑 masculinization）
        # 雌性：低水平但非零
        "zygote": 0.0,
        "early_organogenesis": 0.10,
        "late_organogenesis": 0.70,   # 峰值窗口开始
        "early_neural": 0.90,        # 峰值——脑性分化关键期
        "late_neural": 0.60,
        "fetal_movement": 0.30,
        "birth": 0.20,
    },
    "hcg": {
        # hCG 8-12 周达峰，之后下降——胎盘健康标志
        "zygote": 0.30,
        "early_organogenesis": 0.90,  # 峰值
        "late_organogenesis": 0.50,
        "early_neural": 0.25,
        "late_neural": 0.15,
        "fetal_movement": 0.10,
        "birth": 0.05,
    },
}

# 压力等级 → 皮质醇乘数
STRESS_CORTISOL_MULTIPLIER = {
    "minimal": 1.0,
    "mild": 1.1,
    "moderate": 1.4,     # 中度压力：皮质醇升高 40%
    "severe": 2.0,       # 重度压力：皮质醇翻倍
}

# 碘水平 → 甲状腺功能系数
IODINE_THYROID_FACTOR = {
    "sufficient": 1.0,    # iodine >= 0.55
    "mild_deficiency": 0.80,  # 0.35 <= iodine < 0.55
    "severe_deficiency": 0.50,  # iodine < 0.35
}


def _iodine_status(env: dict) -> str:
    iodine = env.get("nutrients", {}).get("iodine", 0.65)
    if iodine >= 0.55:
        return "sufficient"
    elif iodine >= 0.35:
        return "mild_deficiency"
    return "severe_deficiency"


def compute_hormones(
    stage: str,
    env: dict,
    sex: str = "female",
    complications: list = None,
) -> dict:
    """
    计算当前阶段的激素水平。

    Returns:
        {
            "cortisol": float,       # 0-1+，可超过 1（stress 极端场景）
            "thyroid_t4": float,     # 0-1
            "sex_hormones": float,   # 0-1，雄性在关键期高于雌性
            "hcg": float,           # 0-1
            "cortisol_chronic": bool, # 慢性高皮质醇（连续 moderate+ stress）
            "thyroid_deficient": bool, # 甲状腺功能不足
        }
    """
    # 基线
    cortisol = HORMONE_STAGE_BASELINES["cortisol"].get(stage, 0.2)
    thyroid = HORMONE_STAGE_BASELINES["thyroid_t4"].get(stage, 0.5)
    sex_h = HORMONE_STAGE_BASELINES["sex_hormones"].get(stage, 0.1)
    hcg = HORMONE_STAGE_BASELINES["hcg"].get(stage, 0.1)

    # 皮质醇：受 stress 影响
    stress = env.get("stress", "mild")
    cortisol *= STRESS_CORTISOL_MULTIPLIER.get(stress, 1.0)
    # 随机波动 ±10%
    cortisol *= random.uniform(0.90, 1.10)
    cortisol_chronic = stress in ("moderate", "severe")

    # 甲状腺：受 iodine 影响
    iodine_stat = _iodine_status(env)
    thyroid *= IODINE_THYROID_FACTOR.get(iodine_stat, 1.0)
    thyroid *= random.uniform(0.92, 1.08)
    thyroid_deficient = iodine_stat == "severe_deficiency"

    # 性激素：雄性在关键期高 3-5x，雌性低基线
    if sex == "male":
        sex_h *= random.uniform(2.5, 4.0)  # testosterone surge
    else:
        sex_h *= random.uniform(0.3, 0.6)  # 低水平 estradiol

    # hCG：胎盘问题时下降
    placenta = env.get("placenta", {})
    if placenta.get("complications"):
        hcg *= 0.70  # 胎盘并发症 → hCG 下降
    hcg *= random.uniform(0.90, 1.10)

    return {
        "cortisol": round(min(2.0, cortisol), 3),
        "thyroid_t4": round(min(1.0, thyroid), 3),
        "sex_hormones": round(min(2.0, sex_h), 3),
        "hcg": round(min(1.0, hcg), 3),
        "cortisol_chronic": cortisol_chronic,
        "thyroid_deficient": thyroid_deficient,
    }


def get_hormone_effects(hormones: dict) -> dict:
    """
    从激素水平推导发育效应。

    Returns:
        {
            "budget_penalty": float,    # 额外 budget 惩罚
            "neural_modifier": float,   # 神经发育系数（<1=受损）
            "anxiety_baseline": str,    # 出生后焦虑基线预测
            "cognitive_ceiling": str,   # 认知上限预测
        }
    """
    budget_penalty = 0.0
    neural_mod = 1.0

    # 慢性高皮质醇 → HPA 轴编程 → 高焦虑基线 + 轻微 budget 惩罚
    cortisol = hormones.get("cortisol", 0.2)
    if cortisol > 0.8:
        budget_penalty += 0.03
        anxiety = "elevated"
    elif cortisol > 0.5 and hormones.get("cortisol_chronic"):
        anxiety = "mildly_elevated"
    else:
        anxiety = "normal"

    # 甲状腺不足 → 神经发育减速
    if hormones.get("thyroid_deficient"):
        neural_mod *= 0.75
        budget_penalty += 0.04
        cognitive = "impaired"
    elif hormones.get("thyroid_t4", 0.5) < 0.4:
        neural_mod *= 0.90
        cognitive = "mildly_reduced"
    else:
        cognitive = "normal"

    return {
        "budget_penalty": round(budget_penalty, 3),
        "neural_modifier": round(neural_mod, 3),
        "anxiety_baseline": anxiety,
        "cognitive_ceiling": cognitive,
    }


def format_hormones_for_prompt(hormones: dict, stage: str) -> str:
    """生成 LLM prompt 注入文本：激素状态。"""
    lines = ["## Hormonal Environment"]

    # 皮质醇
    cortisol = hormones.get("cortisol", 0.2)
    if cortisol > 0.8:
        lines.append(f"- Cortisol: {cortisol:.2f} — ELEVATED. Chronic maternal stress is programming "
                      "the fetal HPA axis. This individual will have a higher anxiety baseline at birth. "
                      "Neural pruning may be accelerated.")
    elif cortisol > 0.5:
        lines.append(f"- Cortisol: {cortisol:.2f} — moderately elevated. Fetal stress response activated.")
    else:
        lines.append(f"- Cortisol: {cortisol:.2f} — within normal range.")

    # 甲状腺
    t4 = hormones.get("thyroid_t4", 0.5)
    if hormones.get("thyroid_deficient"):
        lines.append(f"- Thyroid T4: {t4:.2f} — DEFICIENT (iodine shortage). Neural development is constrained. "
                      "Myelination will be slower; cognitive potential is reduced.")
    elif t4 < 0.4:
        lines.append(f"- Thyroid T4: {t4:.2f} — below optimal. Mild impact on neural development tempo.")
    else:
        lines.append(f"- Thyroid T4: {t4:.2f} — adequate for neural development.")

    # 性激素
    sex_h = hormones.get("sex_hormones", 0.1)
    sensitive_stages = ("late_organogenesis", "early_neural")
    if stage in sensitive_stages:
        if sex_h > 1.0:
            lines.append(f"- Sex hormones: {sex_h:.2f} — testosterone surge active. "
                          "Brain masculinization in progress. Spatial processing circuits prioritized.")
        elif sex_h < 0.5:
            lines.append(f"- Sex hormones: {sex_h:.2f} — low/estradiol-dominant. "
                          "Brain feminization pathway. Verbal processing circuits may be prioritized.")

    # hCG
    hcg = hormones.get("hcg", 0.1)
    if stage in ("zygote", "early_organogenesis") and hcg < 0.5:
        lines.append(f"- hCG: {hcg:.2f} — below expected for this stage. Possible placental insufficiency signal.")

    return "\n".join(lines)
