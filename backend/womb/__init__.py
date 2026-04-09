"""
Womb: the world womb. Conceives life from species blueprints.

Multi-fetus competition: shared resource pool, first-developed advantage.
Environment quantitatively modifies budgets and risk probabilities.
Dynamic environment + nutrient specificity + teratogenic windows + maternal feedback numerification.
Simplified Mendelian genetics for inheritable traits.
No retries. What happens, happens.

[INPUT]: species, 可选 model/father_genome/mother_genome
[OUTPUT]: 导出 conceive()
[POS]: womb/ 的入口，被 api/conceive.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from .fate import roll_miscarriage, roll_multiples, roll_stillbirth, roll_congenital_defects, roll_preterm
from .environment import generate_environment, get_defect_risk_modifier, get_miscarriage_risk_modifier
from .genetics import express
from .baby import Baby, ConceptionResult, generate_id, determine_sex, determine_phenotype
from .heredity import ParentGenome, random_genome, crossover, genotype_to_phenotype
from .nutrients import get_overall_nutrient_risk_effects
from .teratogen import get_overall_teratogen_risk
from .epigenetics import generate_methylation_profile, apply_epigenetic_modification


def conceive(
    species: str,
    model: str | None = None,
    father_genome: dict | None = None,
    mother_genome: dict | None = None,
) -> ConceptionResult:
    """
    Attempt to conceive.

    Flow:
        1. Generate or receive parent genomes
        2. Generate maternal environment (quantitative modifiers + nutrients + toxins)
        3. Roll for miscarriage (modified by environment)
        4. Roll for offspring count
        5. For each offspring (sharing resource pool):
           a. Determine sex, phenotype (with genetic inheritance)
           b. Roll for defects (with nutrient/teratogen risk)
           c. Seven-stage development
           d. Roll for stillbirth / preterm
        5. Return ConceptionResult
    """
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    fate_log = {}

    # 1. Parent genomes
    father = ParentGenome.from_dict(father_genome) if father_genome else random_genome(species)
    mother = ParentGenome.from_dict(mother_genome) if mother_genome else random_genome(species)
    parent_genomes_snapshot = {"father": father.to_dict(), "mother": mother.to_dict()}
    fate_log["parent_genomes"] = parent_genomes_snapshot

    # 2. Environment
    env = generate_environment()
    fate_log["environment"] = env
    defect_risk_mod = get_defect_risk_modifier(env)
    miscarriage_risk_mod = get_miscarriage_risk_modifier(env)

    # 3. Miscarriage roll
    miscarriage_fate = roll_miscarriage(species, env_risk_modifier=miscarriage_risk_mod)
    fate_log["miscarriage_roll"] = miscarriage_fate

    if miscarriage_fate["miscarriage"]:
        return ConceptionResult(
            success=False,
            miscarriage=True,
            fate_log=fate_log,
        )

    # 4. Offspring count
    offspring_count = roll_multiples(species)
    fate_log["offspring_count"] = offspring_count

    # 5. Develop each offspring
    babies = []
    now = datetime.now(timezone.utc)

    for i in range(offspring_count):
        # 遗传杂交
        child_genotype = crossover(father, mother, species)
        child_phenotype_from_genes = genotype_to_phenotype(child_genotype, species)

        sex = determine_sex(species)
        phenotype = determine_phenotype(species)
        # 合并遗传表型到 phenotype
        phenotype.update({f"genetic_{k}": v for k, v in child_phenotype_from_genes.items()})

        # 表观遗传：甲基化噪声修饰表型（同基因双胞胎在此分化）
        methylation = generate_methylation_profile(child_genotype, env)
        phenotype = apply_epigenetic_modification(phenotype, methylation)

        # 营养素/致畸风险聚合用于缺陷掷骰
        nutrient_risk = get_overall_nutrient_risk_effects(env.get("nutrients", {}))
        teratogen_risk = get_overall_teratogen_risk(env.get("toxin_types", []))
        defects = roll_congenital_defects(
            species, env_risk_modifier=defect_risk_mod,
            nutrient_risk_effects=nutrient_risk, teratogen_risk=teratogen_risk,
        )
        preterm = roll_preterm(species)
        is_stillborn = roll_stillbirth(species, env_risk_modifier=defect_risk_mod)

        individual_fate = {
            "index": i,
            "sex": sex,
            "phenotype": phenotype,
            "genotype": {k: list(v) for k, v in child_genotype.items()},
            "methylation": methylation,
            "defects": defects,
            "preterm": preterm,
            "stillborn": is_stillborn,
            "birth_order": i,
        }
        fate_log[f"offspring_{i}"] = individual_fate

        # 缺陷名称列表（用于 prompt 注入）
        defect_names = [d["defect"] if isinstance(d, dict) else d for d in defects]

        try:
            result = express(
                species, sex=sex, phenotype=phenotype,
                environment=env, defects=defect_names,
                offspring_count=offspring_count, birth_order=i,
                provider=provider, model=model,
                genotype=child_genotype,
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
            genes={"expression": result["tendencies"], "genotype": {k: list(v) for k, v in child_genotype.items()}},
            first_cry=result["first_cry"] if not is_stillborn else "",
            gestation_log=result["gestation_log"],
            environment=env,
            complications=defects,
            preterm=preterm,
            alive=not is_stillborn,
            parent_genomes=parent_genomes_snapshot,
        )
        babies.append(baby)

    return ConceptionResult(
        success=len(babies) > 0,
        babies=babies,
        offspring_count=offspring_count,
        fate_log=fate_log,
    )
