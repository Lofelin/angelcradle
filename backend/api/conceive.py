import json
import os
import time
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

# 快速事件之间的微延迟（秒），让 TCP 栈有机会 flush 每个 SSE 事件
_PACE_DELAY = 0.05

from womb import conceive
from womb.baby import determine_sex, determine_phenotype, generate_id, Baby
from womb.fate import roll_miscarriage, roll_multiples, roll_stillbirth, roll_congenital_defects, roll_preterm
from womb.environment import generate_environment, get_defect_risk_modifier, get_miscarriage_risk_modifier
from womb.genetics import express_stream, SPECIES_DIR, STAGE_DURATIONS, STAGE_NAMES, RESOURCE_BUDGET
from womb.fate import _load_risks
from womb.nutrients import get_overall_nutrient_risk_effects
from womb.teratogen import get_overall_teratogen_risk
from womb.heredity import ParentGenome, random_genome, crossover, genotype_to_phenotype
from womb.epigenetics import generate_methylation_profile, apply_epigenetic_modification
from womb.birthplace import resolve_birthplace, get_race_weights
from . import registry

router = APIRouter()


def _validate_species(species: str):
    species_list = sorted(p.stem for p in SPECIES_DIR.glob("*.yaml"))
    if species not in species_list:
        raise HTTPException(400, f"Unknown species '{species}', available: {', '.join(species_list)}")


@router.post("/conceive")
def do_conceive(species: str, model: Optional[str] = None, birthplace: Optional[str] = None):
    """Conceive — synchronous. Returns ConceptionResult."""
    _validate_species(species)

    try:
        result = conceive(species=species, model=model, birthplace=birthplace)
        # Save each baby
        for baby in result.babies:
            registry.save(baby.to_dict(include_log=True))
        return result.to_dict()
    except Exception as e:
        raise HTTPException(500, f"Conception failed: {e}")


@router.get("/conceive/stream")
def do_conceive_stream(
    species: str,
    model: Optional[str] = None,
    sex: Optional[str] = None,
    phenotype: Optional[str] = None,
    nutrition: Optional[str] = None,
    stress: Optional[str] = None,
    toxin_exposure: Optional[str] = None,
    maternal_age_factor: Optional[str] = None,
    offspring_count: Optional[int] = None,
    # 营养素细分参数
    folate: Optional[float] = None,
    iodine: Optional[float] = None,
    iron: Optional[float] = None,
    dha: Optional[float] = None,
    calcium: Optional[float] = None,
    # 遗传参数（JSON 字符串）
    father_genome: Optional[str] = None,
    mother_genome: Optional[str] = None,
    # 出生地（ISO code 或国家名）
    birthplace: Optional[str] = None,
):
    """Conceive — SSE stream with real-time stage progress and fate rolls."""
    _validate_species(species)

    provider = os.environ.get("LLM_PROVIDER", "deepseek")

    def event_generator():
        # 0. Birthplace
        bp = resolve_birthplace(species, birthplace)
        bp_summary = {"name": bp["name"], "code": bp["code"], "coordinates": bp["coordinates"]} if bp else None
        race_wts = get_race_weights(bp)
        yield _sse({
            "event": "birthplace",
            "result": bp_summary,
            "method": "specified" if birthplace and bp else "random" if bp else "skipped",
        })

        # 1. Parse parent genomes
        father = None
        mother = None
        if father_genome:
            try:
                father = ParentGenome.from_dict(json.loads(father_genome))
            except (json.JSONDecodeError, TypeError):
                pass
        if mother_genome:
            try:
                mother = ParentGenome.from_dict(json.loads(mother_genome))
            except (json.JSONDecodeError, TypeError):
                pass
        if father is None:
            father = random_genome(species)
        if mother is None:
            mother = random_genome(species)
        parent_genomes_snapshot = {"father": father.to_dict(), "mother": mother.to_dict()}

        # 2. Environment (with nutrient overrides + birthplace bias)
        nutrient_overrides = {}
        for name, val in [("folate", folate), ("iodine", iodine), ("iron", iron), ("dha", dha), ("calcium", calcium)]:
            if val is not None:
                nutrient_overrides[name] = val

        env = generate_environment(
            nutrition=nutrition,
            stress=stress,
            toxin_exposure=toxin_exposure,
            maternal_age_factor=maternal_age_factor,
            nutrients=nutrient_overrides or None,
            birthplace=bp,
        )
        yield _sse({"event": "environment", "result": env})
        yield _sse({"event": "parent_genomes", "result": parent_genomes_snapshot})

        miscarriage_mod = get_miscarriage_risk_modifier(env)
        defect_mod = get_defect_risk_modifier(env)
        nutrient_risk = get_overall_nutrient_risk_effects(env.get("nutrients", {}))
        teratogen_risk_overall = get_overall_teratogen_risk(env.get("toxin_types", []))

        # 3. Miscarriage roll（仅非 human 物种保留前置判定；human 改为逐阶段）
        if species != "human":
            miscarriage_fate = roll_miscarriage(species, env_risk_modifier=miscarriage_mod)
            yield _sse({"event": "fate_roll", "type": "miscarriage", "result": miscarriage_fate})
            if miscarriage_fate["miscarriage"]:
                yield _sse({"event": "miscarriage", "message": f"Miscarriage at early stage (rate: {miscarriage_fate.get('adjusted_rate', 0):.1%})"})
                return

        # 3. Offspring count
        actual_count = offspring_count if offspring_count and 1 <= offspring_count <= 12 else roll_multiples(species)
        yield _sse({"event": "fate_roll", "type": "offspring_count", "result": actual_count})

        # 4. Develop each offspring
        now = datetime.now(timezone.utc)
        babies = []

        for idx in range(actual_count):
            # 遗传杂交
            child_genotype = crossover(father, mother, species)
            child_phenotype_from_genes = genotype_to_phenotype(child_genotype, species)

            baby_sex = determine_sex(species, override=sex)
            baby_phenotype = determine_phenotype(species, override=phenotype, race_weights=race_wts)
            baby_phenotype.update({f"genetic_{k}": v for k, v in child_phenotype_from_genes.items()})

            # 表观遗传修饰
            methylation = generate_methylation_profile(child_genotype, env)
            baby_phenotype = apply_epigenetic_modification(baby_phenotype, methylation)

            defects = roll_congenital_defects(
                species, env_risk_modifier=defect_mod,
                nutrient_risk_effects=nutrient_risk, teratogen_risk=teratogen_risk_overall,
            )
            defect_names = [d["defect"] if isinstance(d, dict) else d for d in defects]
            preterm = roll_preterm(species)
            is_stillborn = roll_stillbirth(species, env_risk_modifier=defect_mod)

            yield _sse({
                "event": "offspring_fate",
                "index": idx,
                "sex": baby_sex,
                "phenotype": {k: v for k, v in baby_phenotype.items() if not k.startswith("_")},
                "genotype": {k: list(v) for k, v in child_genotype.items()},
                "methylation": methylation,
                "defects": defects,
                "preterm": preterm,
                "stillborn": is_stillborn,
            })

            # Seven-stage development
            gestation_log = []
            development_failed = False

            for event in express_stream(
                species, sex=baby_sex, phenotype=baby_phenotype,
                environment=env, defects=defect_names,
                offspring_count=actual_count, birth_order=idx,
                provider=provider, model=model,
                genotype=child_genotype,
                defects_full=defects,
            ):
                if event.get("status") == "failed":
                    yield _sse({"event": "development_failed", "index": idx, **event})
                    development_failed = True
                    break

                if event.get("status") == "miscarriage":
                    yield _sse({"event": "miscarriage", "index": idx, **event})
                    development_failed = True
                    break

                if event["stage"] == "complete":
                    result = event["result"]
                    baby = Baby(
                        id=generate_id(now, index=idx),
                        species=species,
                        sex=baby_sex,
                        phenotype=baby_phenotype,
                        born_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        genes={"expression": result["tendencies"], "genotype": {k: list(v) for k, v in child_genotype.items()}},
                        first_cry=result["first_cry"] if not is_stillborn else "",
                        gestation_log=result["gestation_log"],
                        environment=env,
                        complications=defects,
                        preterm=preterm,
                        alive=not is_stillborn,
                        parent_genomes=parent_genomes_snapshot,
                        birthplace=bp_summary or {},
                    )
                    registry.save(baby.to_dict(include_log=True))
                    babies.append(baby)

                    yield _sse({
                        "event": "born",
                        "index": idx,
                        "alive": baby.alive,
                        "baby": baby.to_dict(include_log=False),
                    })
                else:
                    yield _sse({"event": "stage", "index": idx, **event})

            if development_failed:
                yield _sse({"event": "offspring_lost", "index": idx, "cause": "development_failure"})

        yield _sse({
            "event": "complete",
            "total_conceived": actual_count,
            "total_born": len(babies),
            "total_alive": sum(1 for b in babies if b.alive),
        })

    return StreamingResponse(
        _paced(event_generator()),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# SSE 响应头：禁止所有层面的缓冲
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "X-Accel-Buffering": "no",         # nginx
    "Connection": "keep-alive",
}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _paced(gen):
    """在快速事件之间插入微延迟，确保每个 SSE 事件独立 flush。"""
    for item in gen:
        yield item
        time.sleep(_PACE_DELAY)


@router.get("/species/{species}/blueprint")
def get_blueprint(species: str):
    """Return species blueprint: traits, probabilities, stages — single source of truth."""
    _validate_species(species)

    import yaml
    path = SPECIES_DIR / f"{species}.yaml"
    bp = yaml.safe_load(path.read_text(encoding="utf-8"))
    birth = bp.get("birth_attributes", {})
    risks = _load_risks(species)

    # Phenotype options
    phenotype_key = "race" if birth.get("races") else "breed"
    phenotypes = birth.get("races") or birth.get("breeds") or []

    # Miscarriage rate
    if species == "human":
        miscarriage_rate = risks.get("miscarriage", {}).get("overall_rate", 0.153)
    elif species == "dog":
        miscarriage_rate = risks.get("embryonic_resorption", {}).get("rate", 0.135)
    elif species == "cat":
        miscarriage_rate = risks.get("fetal_resorption", {}).get("rate", 0.15)
    else:
        miscarriage_rate = 0.15

    # Stillbirth rate
    if species == "human":
        stillbirth_rate = risks.get("stillbirth", {}).get("global_rate", 0.0143)
    else:
        stillbirth_rate = risks.get("stillbirth", {}).get("rate", 0.05)

    # Offspring range
    if species == "human":
        m = risks.get("multiple_births", {})
        offspring = {"typical": 1, "twin_rate": m.get("twin_rate", 0.012), "triplet_rate": m.get("triplet_rate", 0.000738)}
    elif species == "dog":
        offspring = {"min": 4, "max": 7}
    elif species == "cat":
        ls = risks.get("litter_size", {})
        offspring = {"average": ls.get("average", 4.0), "std_dev": ls.get("std_dev", 1.9), "max": 12}
    else:
        offspring = {"typical": 1}

    # Congenital defects with rates
    defects = {}
    if species == "human":
        a = risks.get("congenital_anomalies", {})
        defects = {
            "congenital_heart_defect": a.get("heart_defects", 0.008),
            "neural_tube_defect": a.get("neural_tube_defects", 0.001),
            "cleft_lip_palate": a.get("cleft_lip_palate", 0.001),
            "down_syndrome": a.get("down_syndrome", {}).get("overall", 0.00143),
        }
    elif species == "dog":
        d = risks.get("congenital_defects", {})
        defects = {
            "congenital_heart_defect": d.get("heart_defects", 0.0075),
            "cleft_palate": d.get("cleft_palate", 0.0015),
            "cryptorchidism": d.get("cryptorchidism", 0.038),
        }
    elif species == "cat":
        d = risks.get("congenital_defects", {})
        defects = {
            "polydactyly": d.get("polydactyly", 0.02),
            "cleft_palate": d.get("cleft_palate", 0.004),
            "congenital_heart_defect": d.get("heart_defects", 0.006),
        }

    # Stage durations
    durations = STAGE_DURATIONS.get(species, STAGE_DURATIONS["human"])
    total_gestation = sum(durations.values())

    return {
        "species": species,
        "sex_system": birth.get("sex_system", "XY"),
        "phenotype_key": phenotype_key,
        "phenotypes": phenotypes,
        "gestation_days": total_gestation,
        "stages": [
            {"name": name, "duration": durations.get(name, 0), "budget": RESOURCE_BUDGET.get(name, 0)}
            for name in STAGE_NAMES
        ],
        "miscarriage_rate": miscarriage_rate,
        "stillbirth_rate": stillbirth_rate,
        "offspring": offspring,
        "defects": defects,
    }


@router.get("/babies")
def list_babies():
    return {"babies": registry.list_all()}


@router.get("/baby/{baby_id}")
def get_baby(baby_id: str):
    data = registry.load(baby_id)
    if data is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found")
    return data


@router.get("/baby/{baby_id}/gestation")
def get_gestation(baby_id: str):
    data = registry.load(baby_id)
    if data is None:
        raise HTTPException(404, f"Baby '{baby_id}' not found")
    return {"id": baby_id, "gestation_log": data.get("gestation_log", [])}
