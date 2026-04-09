"""
胎儿生命体征：逐阶段心率、体重、身长、羊水指数、胎动评分。

数据来源：
  - 心率：Embryologia (6w ~110 bpm → 9w 170 peak → term 140 avg)
  - 体重：WHO Fetal Growth Charts (Intergrowth-21st)
  - 身长：Crown-rump length tables (Robinson & Fleming 1975, updated)
  - 羊水：AFI normal range 5-25cm, peaks ~34-36 weeks
  - 胎动：Quickening ~16-25w, 10+ kicks/2hr normal in 3rd trimester

[INPUT]: 当前阶段、环境 dict、激素 dict、营养素 dict、并发症列表、胎盘状态
[OUTPUT]: 导出 compute_vitals, format_vitals_for_display
[POS]: womb/ 的生命体征子系统，被 stages.py 消费，为前端提供可观测数据
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import random
import math


# ============================================================
# 阶段基线值
# 每个阶段对应一个 gestational day 中点，用于计算基线
# ============================================================

# 阶段 → (中点天数, 心率 bpm, 体重 g, 身长 mm, 羊水 AFI cm, 胎动 0-10)
VITAL_BASELINES = {
    "zygote": {
        "day_midpoint": 4,
        "heart_rate": 0,          # 尚无心跳
        "weight_grams": 0.001,    # 受精卵 ~0.001g
        "length_mm": 0.1,         # ~0.1mm
        "amniotic_fluid": 0.0,    # 尚无羊水
        "movement_score": 0,      # 无运动
    },
    "early_organogenesis": {
        "day_midpoint": 21,
        "heart_rate": 120,        # 心管开始跳动 day 22, ~100-120
        "weight_grams": 2.0,      # ~2g at 8 weeks
        "length_mm": 16,          # CRL ~16mm at 8 weeks
        "amniotic_fluid": 2.0,    # 早期羊水极少
        "movement_score": 0,      # 无自主运动
    },
    "late_organogenesis": {
        "day_midpoint": 46,
        "heart_rate": 165,        # 峰值 ~170 at 9 weeks
        "weight_grams": 14,       # ~14g at 12 weeks
        "length_mm": 54,          # CRL ~54mm at 12 weeks
        "amniotic_fluid": 5.0,
        "movement_score": 1,      # 微弱反射运动
    },
    "early_neural": {
        "day_midpoint": 73,
        "heart_rate": 150,        # 下降到 ~150
        "weight_grams": 100,      # ~100g at 16 weeks
        "length_mm": 120,         # CRL ~12cm at 16 weeks
        "amniotic_fluid": 10.0,
        "movement_score": 3,      # quickening 开始
    },
    "late_neural": {
        "day_midpoint": 108,
        "heart_rate": 140,        # 稳定 ~140
        "weight_grams": 500,      # ~500g at 22 weeks
        "length_mm": 280,         # 头臀 28cm
        "amniotic_fluid": 15.0,
        "movement_score": 6,      # 活跃运动
    },
    "fetal_movement": {
        "day_midpoint": 168,
        "heart_rate": 135,        # ~135
        "weight_grams": 1700,     # ~1700g at 32 weeks
        "length_mm": 420,         # ~42cm head-heel
        "amniotic_fluid": 18.0,   # 接近峰值
        "movement_score": 8,      # 高活跃度
    },
    "birth": {
        "day_midpoint": 245,
        "heart_rate": 140,        # 出生时 120-160
        "weight_grams": 3400,     # ~3.4kg 足月
        "length_mm": 500,         # ~50cm
        "amniotic_fluid": 12.0,   # 足月时下降
        "movement_score": 5,      # 空间受限运动减少
    },
}

# ============================================================
# 环境/状态对体征的修正
# ============================================================

def _nutrition_weight_factor(env: dict) -> float:
    """营养状况对体重的影响。"""
    nutrition = env.get("nutrition", "adequate")
    return {
        "excellent": 1.08,
        "adequate": 1.0,
        "moderate_deficiency": 0.88,
        "severe_deficiency": 0.72,   # FGR: 28% weight reduction
    }.get(nutrition, 1.0)


def _placenta_efficiency_factor(env: dict) -> float:
    """胎盘效率对整体发育的影响。"""
    placenta = env.get("placenta", {})
    efficiency = placenta.get("efficiency", 1.0)
    return max(0.5, efficiency)


def _stress_heart_rate_modifier(env: dict) -> float:
    """压力 → 心率加速。"""
    stress = env.get("stress", "mild")
    return {
        "minimal": 0,
        "mild": 2,
        "moderate": 8,
        "severe": 15,    # 重度压力：心率+15 bpm
    }.get(stress, 0)


def _complication_modifiers(complications: list) -> dict:
    """并发症对体征的影响。"""
    mods = {"weight": 1.0, "heart_rate": 0, "movement": 0}
    if not complications:
        return mods

    comp_names = [c["defect"] if isinstance(c, dict) else c for c in complications]

    if "congenital_heart_defect" in comp_names:
        mods["heart_rate"] += random.choice([-15, -10, 10, 20])  # 心律异常
    if "neural_tube_defect" in comp_names:
        mods["movement"] -= 2  # 运动受损
    if "microcephaly" in comp_names:
        mods["weight"] *= 0.92
    if "gastroschisis" in comp_names:
        mods["weight"] *= 0.85  # 腹壁裂影响营养吸收

    return mods


def compute_vitals(
    stage: str,
    env: dict,
    hormones: dict = None,
    complications: list = None,
    preterm: dict = None,
) -> dict:
    """
    计算当前阶段的胎儿生命体征。

    Returns:
        {
            "heart_rate_bpm": int,         # 心率（0 = 尚无心跳）
            "weight_grams": float,         # 估计体重
            "length_mm": float,            # 身长（早期 CRL，晚期 head-heel）
            "amniotic_fluid_index": float,  # 羊水指数 cm
            "movement_score": int,          # 胎动评分 0-10
            "blood_pressure_systolic": int | None,  # 收缩压（晚期才可测）
            "oxygen_saturation": float,     # 血氧饱和度（胎儿正常 60-70%）
            "status": str,                  # normal / concerning / critical
            "alerts": list[str],            # 异常告警
        }
    """
    baseline = VITAL_BASELINES.get(stage, VITAL_BASELINES["birth"])
    hormones = hormones or {}
    complications = complications or []
    alerts = []

    # 基线 + 随机波动
    hr = baseline["heart_rate"]
    weight = baseline["weight_grams"]
    length = baseline["length_mm"]
    afi = baseline["amniotic_fluid"]
    movement = baseline["movement_score"]

    if hr > 0:
        # 心率修正
        hr += _stress_heart_rate_modifier(env)
        hr += _complication_modifiers(complications)["heart_rate"]
        # 随机波动 ±5%
        hr = round(hr * random.uniform(0.95, 1.05))

        # 心率异常检查
        if stage not in ("zygote", "early_organogenesis"):
            if hr < 110:
                alerts.append(f"Bradycardia: {hr} bpm (normal 120-160)")
            elif hr > 180:
                alerts.append(f"Tachycardia: {hr} bpm (normal 120-160)")

    # 体重修正
    nut_factor = _nutrition_weight_factor(env)
    plac_factor = _placenta_efficiency_factor(env)
    comp_mods = _complication_modifiers(complications)
    weight *= nut_factor * plac_factor * comp_mods["weight"]
    weight *= random.uniform(0.92, 1.08)
    weight = round(weight, 1)

    # 身长：与体重相关但变异更小
    length *= (nut_factor * 0.3 + 0.7)  # 营养影响身长的幅度小于体重
    length *= random.uniform(0.96, 1.04)
    length = round(length, 1)

    # 羊水
    if afi > 0:
        afi *= plac_factor
        afi *= random.uniform(0.85, 1.15)
        afi = round(afi, 1)
        if afi < 5.0 and stage in ("fetal_movement", "birth"):
            alerts.append(f"Oligohydramnios: AFI {afi:.1f} cm (normal 5-25)")
        elif afi > 25.0:
            alerts.append(f"Polyhydramnios: AFI {afi:.1f} cm (normal 5-25)")

    # 胎动
    movement += comp_mods["movement"]
    # 高皮质醇 → 胎动增加（短期）或减少（慢性）
    cortisol = hormones.get("cortisol", 0.2)
    if cortisol > 0.8 and hormones.get("cortisol_chronic"):
        movement -= 1  # 慢性压力 → 活动减少
    elif cortisol > 0.6:
        movement += 1  # 急性压力 → 活动增加
    movement = max(0, min(10, movement))

    if movement <= 2 and stage in ("late_neural", "fetal_movement"):
        alerts.append(f"Reduced fetal movement: score {movement}/10")

    # 血压（仅晚期有意义）
    bp_systolic = None
    if stage in ("fetal_movement", "birth"):
        bp_systolic = round(random.gauss(40, 5))  # 胎儿收缩压 ~35-45 mmHg
        if comp_mods["heart_rate"] != 0:
            bp_systolic += random.randint(-5, 5)

    # 血氧（胎儿正常 SpO2 60-70%，经胎盘供氧）
    o2_base = 0.65  # 65%
    o2_base *= plac_factor
    if env.get("stress") == "severe":
        o2_base -= 0.05
    o2 = round(max(0.30, min(0.75, o2_base * random.uniform(0.95, 1.05))), 2)
    # 低氧告警仅在胎盘循环建立后有意义（early_neural 起）
    if o2 < 0.50 and stage in ("early_neural", "late_neural", "fetal_movement", "birth"):
        alerts.append(f"Fetal hypoxia: SpO2 {o2:.0%} (normal 60-70%)")

    # 综合状态
    if len(alerts) >= 2 or any("hypoxia" in a for a in alerts):
        status = "critical"
    elif alerts:
        status = "concerning"
    else:
        status = "normal"

    return {
        "heart_rate_bpm": max(0, hr),
        "weight_grams": weight,
        "length_mm": length,
        "amniotic_fluid_index": afi,
        "movement_score": movement,
        "blood_pressure_systolic": bp_systolic,
        "oxygen_saturation": o2,
        "status": status,
        "alerts": alerts,
    }


def format_vitals_for_display(vitals: dict, stage: str) -> dict:
    """
    格式化生命体征为前端友好格式。

    不同于 prompt 格式（给 LLM 看），这个是给人看的。
    """
    hr = vitals["heart_rate_bpm"]
    display = {
        "heart_rate": f"{hr} bpm" if hr > 0 else "—",
        "weight": _format_weight(vitals["weight_grams"]),
        "length": _format_length(vitals["length_mm"]),
        "amniotic_fluid": f"{vitals['amniotic_fluid_index']:.1f} cm" if vitals["amniotic_fluid_index"] > 0 else "—",
        "movement": f"{vitals['movement_score']}/10" if vitals["movement_score"] > 0 else "—",
        "blood_pressure": f"{vitals['blood_pressure_systolic']} mmHg" if vitals["blood_pressure_systolic"] else "—",
        "oxygen": f"{vitals['oxygen_saturation']:.0%}",
        "status": vitals["status"],
        "alerts": vitals["alerts"],
    }
    return display


def _format_weight(grams: float) -> str:
    if grams < 1:
        return f"{grams * 1000:.0f} μg"
    elif grams < 1000:
        return f"{grams:.1f} g"
    else:
        return f"{grams / 1000:.2f} kg"


def _format_length(mm: float) -> str:
    if mm < 10:
        return f"{mm:.1f} mm"
    elif mm < 100:
        return f"{mm:.0f} mm"
    else:
        return f"{mm / 10:.1f} cm"
