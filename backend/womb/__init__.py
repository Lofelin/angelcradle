"""
Womb: the world womb. Conceives life from species blueprints.

Multi-fetus competition: shared resource pool, first-developed advantage.
Environment quantitatively modifies budgets and risk probabilities.
No retries. What happens, happens.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from .fate import roll_miscarriage, roll_multiples, roll_stillbirth, roll_congenital_defects, roll_preterm
from .environment import generate_environment, get_defect_risk_modifier, get_miscarriage_risk_modifier
from .genetics import express
from .baby import Baby, ConceptionResult, generate_id, determine_sex, determine_phenotype


def conceive(species: str, model: str | None = None) -> ConceptionResult:
    """
    Attempt to conceive.

    Flow:
        1. Generate maternal environment (quantitative modifiers)
        2. Roll for miscarriage (modified by environment)
        3. Roll for offspring count
        4. For each offspring (sharing resource pool):
           a. Determine sex, phenotype
           b. Roll for defects (modified by environment)
           c. Seven-stage development (resource budget adjusted for multi-fetus + environment)
           d. Roll for stillbirth / preterm
        5. Return ConceptionResult
    """
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    fate_log = {}

    # 1. Environment (before any rolls — it affects everything)
    env = generate_environment()
    fate_log["environment"] = env
    defect_risk_mod = get_defect_risk_modifier(env)
    miscarriage_risk_mod = get_miscarriage_risk_modifier(env)

    # 2. Miscarriage roll (uses its own gentle modifier, NOT defect modifier)
    miscarriage_fate = roll_miscarriage(species, env_risk_modifier=miscarriage_risk_mod)
    fate_log["miscarriage_roll"] = miscarriage_fate

    if miscarriage_fate["miscarriage"]:
        return ConceptionResult(
            success=False,
            miscarriage=True,
            fate_log=fate_log,
        )

    # 3. Offspring count
    offspring_count = roll_multiples(species)
    fate_log["offspring_count"] = offspring_count

    # 4. Develop each offspring
    babies = []
    now = datetime.now(timezone.utc)

    for i in range(offspring_count):
        sex = determine_sex(species)
        phenotype = determine_phenotype(species)
        defects = roll_congenital_defects(species, env_risk_modifier=defect_risk_mod)
        preterm = roll_preterm(species)
        is_stillborn = roll_stillbirth(species, env_risk_modifier=defect_risk_mod)

        individual_fate = {
            "index": i,
            "sex": sex,
            "phenotype": phenotype,
            "defects": defects,
            "preterm": preterm,
            "stillborn": is_stillborn,
            "birth_order": i,  # earlier = slight resource advantage
        }
        fate_log[f"offspring_{i}"] = individual_fate

        # Development with multi-fetus competition
        try:
            result = express(
                species, sex=sex, phenotype=phenotype,
                environment=env, defects=defects,
                offspring_count=offspring_count, birth_order=i,
                provider=provider, model=model,
            )
        except RuntimeError:
            individual_fate["development_failed"] = True
            continue

        baby = Baby(
            id=generate_id(now, index=i),
            species=species,
            sex=sex,
            phenotype=phenotype,
            born_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            genes={"expression": result["tendencies"]},
            first_cry=result["first_cry"] if not is_stillborn else "",
            gestation_log=result["gestation_log"],
            environment=env,
            complications=defects,
            preterm=preterm,
            alive=not is_stillborn,
        )
        babies.append(baby)

    return ConceptionResult(
        success=len(babies) > 0,
        babies=babies,
        offspring_count=offspring_count,
        fate_log=fate_log,
    )
