"""
Maternal environment: randomly generated conditions that affect fetal development.

Environment is not just labels — each condition produces quantitative modifiers
that are enforced at code level on resource budgets and risk probabilities.
"""

from __future__ import annotations

import random


# Environment profiles with relative weights
NUTRITION_LEVELS = [
    ("excellent", 0.20),
    ("adequate", 0.50),
    ("moderate_deficiency", 0.20),
    ("severe_deficiency", 0.10),
]

STRESS_LEVELS = [
    ("minimal", 0.25),
    ("mild", 0.35),
    ("moderate", 0.25),
    ("severe", 0.15),
]

TOXIN_EXPOSURES = [
    ("none", 0.60),
    ("mild", 0.25),
    ("moderate", 0.10),
    ("severe", 0.05),
]

# Quantitative modifiers: how each condition affects development
BUDGET_MODIFIERS = {
    "nutrition": {
        "excellent": 1.05,
        "adequate": 1.0,
        "moderate_deficiency": 0.85,
        "severe_deficiency": 0.70,
    },
    "stress": {
        "minimal": 1.0,
        "mild": 0.97,
        "moderate": 0.90,
        "severe": 0.80,
    },
    "toxin_exposure": {
        "none": 1.0,
        "mild": 0.95,
        "moderate": 0.85,
        "severe": 0.70,
    },
    "maternal_age_factor": {
        "very_young": 0.92,
        "optimal": 1.0,
        "moderate": 0.97,
        "advanced": 0.93,
        "very_advanced": 0.85,
    },
}

# Risk multipliers for congenital defects (can be high — defects are rare events)
DEFECT_RISK_MODIFIERS = {
    "toxin_exposure": {
        "none": 1.0,
        "mild": 1.3,
        "moderate": 2.0,
        "severe": 3.5,
    },
    "maternal_age_factor": {
        "very_young": 1.2,
        "optimal": 1.0,
        "moderate": 1.3,
        "advanced": 2.0,
        "very_advanced": 3.5,
    },
}

# Risk multipliers for miscarriage (gentler — miscarriage base rate is already high)
MISCARRIAGE_RISK_MODIFIERS = {
    "stress": {
        "minimal": 1.0,
        "mild": 1.0,
        "moderate": 1.2,
        "severe": 1.5,
    },
    "maternal_age_factor": {
        "very_young": 1.1,
        "optimal": 1.0,
        "moderate": 1.1,
        "advanced": 1.3,
        "very_advanced": 1.6,
    },
}

# Multi-fetus resource sharing
# Twins don't get 50% each — mother increases supply, but not 2x
MULTI_FETUS_BUDGET_FACTOR = {
    1: 1.0,
    2: 0.55,   # each twin gets 55% of singleton budget
    3: 0.40,   # each triplet gets 40%
    4: 0.32,
    5: 0.27,
    6: 0.23,
}


def _weighted_choice(options: list[tuple[str, float]]) -> str:
    labels, weights = zip(*options)
    return random.choices(labels, weights=weights, k=1)[0]


def generate_environment() -> dict:
    """Generate a random maternal environment with quantitative modifiers."""
    env = {
        "nutrition": _weighted_choice(NUTRITION_LEVELS),
        "stress": _weighted_choice(STRESS_LEVELS),
        "toxin_exposure": _weighted_choice(TOXIN_EXPOSURES),
        "maternal_age_factor": _random_age_factor(),
    }
    env["modifiers"] = compute_modifiers(env)
    return env


def _random_age_factor() -> str:
    r = random.random()
    if r < 0.05:
        return "very_young"
    elif r < 0.60:
        return "optimal"
    elif r < 0.85:
        return "moderate"
    elif r < 0.95:
        return "advanced"
    else:
        return "very_advanced"


def compute_modifiers(env: dict) -> dict:
    """Compute quantitative modifiers from environment labels."""
    budget_mod = 1.0
    for factor, levels in BUDGET_MODIFIERS.items():
        budget_mod *= levels.get(env.get(factor, ""), 1.0)

    defect_risk_mod = 1.0
    for factor, levels in DEFECT_RISK_MODIFIERS.items():
        defect_risk_mod *= levels.get(env.get(factor, ""), 1.0)

    miscarriage_risk_mod = 1.0
    for factor, levels in MISCARRIAGE_RISK_MODIFIERS.items():
        miscarriage_risk_mod *= levels.get(env.get(factor, ""), 1.0)

    return {
        "budget_multiplier": round(budget_mod, 3),
        "defect_risk_multiplier": round(defect_risk_mod, 3),
        "miscarriage_risk_multiplier": round(miscarriage_risk_mod, 3),
    }


def get_effective_budget(base_budget: int, env: dict, offspring_count: int = 1) -> int:
    """
    Calculate effective budget after environment and multi-fetus adjustments.

    base_budget × environment_modifier × multi_fetus_factor
    """
    env_mod = env.get("modifiers", {}).get("budget_multiplier", 1.0)
    fetus_factor = MULTI_FETUS_BUDGET_FACTOR.get(offspring_count, 0.20)
    return max(1, round(base_budget * env_mod * fetus_factor))


def get_defect_risk_modifier(env: dict) -> float:
    """Get the defect risk multiplier from environment."""
    return env.get("modifiers", {}).get("defect_risk_multiplier", 1.0)


def get_miscarriage_risk_modifier(env: dict) -> float:
    """Get the miscarriage risk multiplier from environment."""
    return env.get("modifiers", {}).get("miscarriage_risk_multiplier", 1.0)


def format_environment(env: dict) -> str:
    """Format environment for injection into LLM prompt."""
    lines = [
        f"- Maternal nutrition: {env['nutrition']}",
        f"- Maternal stress level: {env['stress']}",
        f"- Environmental toxin exposure: {env['toxin_exposure']}",
        f"- Maternal age factor: {env['maternal_age_factor']}",
    ]
    modifiers = env.get("modifiers", {})
    if modifiers:
        lines.append(f"- Effective resource modifier: {modifiers.get('budget_multiplier', 1.0):.0%} of baseline")
        lines.append(f"- Defect risk modifier: {modifiers.get('defect_risk_multiplier', 1.0):.1f}x baseline")
    return "\n".join(lines)


def environment_impact_text(env: dict) -> str:
    """Generate text describing how the environment affects development."""
    impacts = []
    modifiers = env.get("modifiers", {})
    budget_mod = modifiers.get("budget_multiplier", 1.0)

    if budget_mod < 0.80:
        impacts.append(f"Severely constrained uterine environment (resource capacity at {budget_mod:.0%}). "
                       "Multiple developmental systems will be below optimal.")
    elif budget_mod < 0.95:
        impacts.append(f"Moderately constrained environment (resource capacity at {budget_mod:.0%}). "
                       "Some developmental tradeoffs will be sharper than normal.")

    if env.get("stress") in ("moderate", "severe"):
        impacts.append("Elevated maternal cortisol crosses the placenta, shifting fetal arousal baseline upward "
                       "and potentially accelerating neural pruning.")
    if env.get("toxin_exposure") in ("moderate", "severe"):
        risk_mod = modifiers.get("defect_risk_multiplier", 1.0)
        impacts.append(f"Teratogenic exposure active (defect risk at {risk_mod:.1f}x baseline). "
                       "Organogenesis stage particularly vulnerable.")
    if env.get("maternal_age_factor") in ("advanced", "very_advanced"):
        impacts.append("Advanced maternal age reduces placental efficiency and increases chromosomal risk.")

    if not impacts:
        impacts.append("Favorable uterine environment. Development proceeds without significant external constraints.")

    return " ".join(impacts)
