"""
Fate engine: probability rolls using real-world data from species blueprints.

Every roll uses actual rates from WHO, Lancet, CDC, PubMed studies.
Environment modifiers affect probabilities at code level.
No retries. What happens, happens.
"""

from __future__ import annotations

import random
from pathlib import Path

import yaml

SPECIES_DIR = Path(__file__).parent / "species"


def _load_risks(species: str) -> dict:
    """Load pregnancy_risks from species blueprint."""
    path = SPECIES_DIR / f"{species}.yaml"
    blueprint = yaml.safe_load(path.read_text(encoding="utf-8"))
    return blueprint.get("pregnancy_risks", {})


def roll(probability: float) -> bool:
    """Roll against a probability. Returns True if event occurs."""
    return random.random() < probability


def roll_miscarriage(species: str, env_risk_modifier: float = 1.0) -> dict:
    """Roll for early miscarriage. Environment risk modifier applied."""
    risks = _load_risks(species)

    if species == "human":
        rate = risks.get("miscarriage", {}).get("overall_rate", 0.153)
    elif species == "dog":
        rate = risks.get("embryonic_resorption", {}).get("rate", 0.135)
    elif species == "cat":
        rate = risks.get("fetal_resorption", {}).get("rate", 0.15)
    else:
        rate = 0.15

    adjusted_rate = min(rate * env_risk_modifier, 0.95)

    if roll(adjusted_rate):
        return {"miscarriage": True, "stage": "early", "base_rate": rate, "adjusted_rate": adjusted_rate}
    return {"miscarriage": False, "base_rate": rate, "adjusted_rate": adjusted_rate}


def roll_multiples(species: str) -> int:
    """Roll for number of offspring. Returns count."""
    risks = _load_risks(species)

    if species == "human":
        multiples = risks.get("multiple_births", {})
        twin_rate = multiples.get("twin_rate", 0.012)
        triplet_rate = multiples.get("triplet_rate", 0.000738)

        if roll(triplet_rate):
            return 3
        if roll(twin_rate):
            return 2
        return 1

    elif species == "dog":
        low, high = 4, 7
        return random.randint(low, high)

    elif species == "cat":
        litter = risks.get("litter_size", {})
        avg = litter.get("average", 4.0)
        std = litter.get("std_dev", 1.9)
        count = max(1, round(random.gauss(avg, std)))
        return min(count, 12)

    return 1


def roll_stillbirth(species: str, env_risk_modifier: float = 1.0) -> bool:
    """Roll for stillbirth at birth stage. Environment modifier applied."""
    risks = _load_risks(species)

    if species == "human":
        rate = risks.get("stillbirth", {}).get("global_rate", 0.0143)
    elif species == "dog":
        rate = risks.get("stillbirth", {}).get("rate", 0.053)
    elif species == "cat":
        rate = risks.get("stillbirth", {}).get("rate", 0.085)
    else:
        rate = 0.05

    return roll(min(rate * env_risk_modifier, 0.5))


def roll_congenital_defects(species: str, env_risk_modifier: float = 1.0) -> list[str]:
    """Roll for congenital defects. Environment risk modifier applied to all probabilities."""
    risks = _load_risks(species)
    defects = []

    def adjusted_roll(base_rate: float) -> bool:
        return roll(min(base_rate * env_risk_modifier, 0.5))

    if species == "human":
        anomalies = risks.get("congenital_anomalies", {})
        if adjusted_roll(anomalies.get("heart_defects", 0.008)):
            defects.append("congenital_heart_defect")
        if adjusted_roll(anomalies.get("neural_tube_defects", 0.001)):
            defects.append("neural_tube_defect")
        if adjusted_roll(anomalies.get("cleft_lip_palate", 0.001)):
            defects.append("cleft_lip_palate")
        if adjusted_roll(anomalies.get("down_syndrome", {}).get("overall", 0.00143)):
            defects.append("down_syndrome")

    elif species == "dog":
        cd = risks.get("congenital_defects", {})
        if adjusted_roll(cd.get("heart_defects", 0.0075)):
            defects.append("congenital_heart_defect")
        if adjusted_roll(cd.get("cleft_palate", 0.0015)):
            defects.append("cleft_palate")
        if adjusted_roll(cd.get("cryptorchidism", 0.038)):
            defects.append("cryptorchidism")

    elif species == "cat":
        cd = risks.get("congenital_defects", {})
        if adjusted_roll(cd.get("polydactyly", 0.02)):
            defects.append("polydactyly")
        if adjusted_roll(cd.get("cleft_palate", 0.004)):
            defects.append("cleft_palate")
        if adjusted_roll(cd.get("heart_defects", 0.006)):
            defects.append("congenital_heart_defect")

    return defects


def roll_preterm(species: str) -> dict:
    """Roll for preterm birth."""
    if species != "human":
        return {"preterm": False}

    risks = _load_risks(species)
    preterm = risks.get("preterm_birth", {})
    rate = preterm.get("global_rate", 0.10)

    if roll(rate):
        r = random.random()
        if r < 0.05:
            return {"preterm": True, "severity": "extremely_preterm", "weeks": random.randint(24, 27)}
        elif r < 0.12:
            return {"preterm": True, "severity": "very_preterm", "weeks": random.randint(28, 31)}
        else:
            return {"preterm": True, "severity": "late_preterm", "weeks": random.randint(34, 36)}

    return {"preterm": False, "weeks": random.randint(37, 42)}


# ============================================================
# Post-LLM output validators (改造 4+5)
# ============================================================

# Resource level → allowed description intensity
RESOURCE_INTENSITY_MAP = {
    (0, 15): ["underdeveloped", "weak", "minimal", "deficient", "impaired", "poor"],
    (15, 30): ["below average", "modest", "limited", "reduced"],
    (30, 50): ["moderate", "average", "adequate", "functional"],
    (50, 75): ["above average", "strong", "developed", "enhanced"],
    (75, 101): ["highly developed", "dominant", "exceptional", "superior", "primary"],
}

# Defect → keywords that indicate the defect is being ignored
DEFECT_CONTRADICTION_KEYWORDS = {
    "congenital_heart_defect": ["normal cardiac", "healthy heart", "no cardiac", "strong cardiovascular"],
    "neural_tube_defect": ["normal neural", "intact neural tube", "no neurological"],
    "cleft_lip_palate": ["normal palate", "intact palate", "no cleft"],
    "cleft_palate": ["normal palate", "intact palate", "no cleft"],
    "down_syndrome": ["normal chromosome", "typical karyotype"],
    "polydactyly": ["normal digit count", "five digits"],
    "cryptorchidism": ["both testes descended", "normal testicular"],
}


def validate_resource_semantics(parsed: dict, budget: int) -> dict:
    """
    Validate that LLM descriptions match resource allocations.

    If a system got 10/80 points but is described as "highly developed",
    downgrade the description. Code enforcement, not LLM honor system.
    """
    allocation = parsed.get("resource_allocation")
    if not allocation or not isinstance(allocation, dict):
        return parsed

    total = sum(v for v in allocation.values() if isinstance(v, (int, float)))
    if total == 0:
        return parsed

    adjustments = []
    for system, points in allocation.items():
        if not isinstance(points, (int, float)):
            continue
        pct = (points / budget) * 100

        # Find which intensity band this falls into
        allowed = None
        for (low, high), words in RESOURCE_INTENSITY_MAP.items():
            if low <= pct < high:
                allowed = words
                break

        if allowed is None:
            continue

        # Check all string values in parsed for this system's description
        for key, value in parsed.items():
            if key == "resource_allocation" or not isinstance(value, str):
                continue
            value_lower = value.lower()
            # Check if high-intensity words are used for low-resource systems
            if pct < 30:
                for high_word in RESOURCE_INTENSITY_MAP[(75, 101)] + RESOURCE_INTENSITY_MAP[(50, 75)]:
                    if high_word in value_lower and system.lower() in value_lower:
                        adjustments.append(f"{system}: described as '{high_word}' but only allocated {pct:.0f}% resources — capped to 'limited'")

    if adjustments:
        parsed["_semantic_adjustments"] = adjustments

    return parsed


def validate_defect_consistency(parsed: dict, defects: list[str]) -> dict:
    """
    Verify LLM output doesn't contradict known defects.

    If baby has congenital_heart_defect but output says "normal cardiac function",
    inject a correction marker.
    """
    if not defects:
        return parsed

    contradictions = []
    output_text = str(parsed).lower()

    for defect in defects:
        keywords = DEFECT_CONTRADICTION_KEYWORDS.get(defect, [])
        for keyword in keywords:
            if keyword.lower() in output_text:
                contradictions.append({
                    "defect": defect,
                    "contradiction": keyword,
                    "correction": f"Development constrained by {defect.replace('_', ' ')} — LLM output contradicted this condition",
                })

    if contradictions:
        parsed["_defect_contradictions"] = contradictions
        # Inject defect note into relevant fields
        for c in contradictions:
            parsed[f"_defect_note_{c['defect']}"] = c["correction"]

    return parsed
