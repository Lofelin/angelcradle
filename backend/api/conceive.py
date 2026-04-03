import json
import os
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from womb import conceive
from womb.baby import determine_sex, determine_phenotype, generate_id, Baby
from womb.fate import roll_miscarriage, roll_multiples, roll_stillbirth, roll_congenital_defects, roll_preterm
from womb.environment import generate_environment, get_defect_risk_modifier, get_miscarriage_risk_modifier
from womb.genetics import express_stream, SPECIES_DIR
from . import registry

router = APIRouter()


def _validate_species(species: str):
    species_list = sorted(p.stem for p in SPECIES_DIR.glob("*.yaml"))
    if species not in species_list:
        raise HTTPException(400, f"Unknown species '{species}', available: {', '.join(species_list)}")


@router.post("/conceive")
def do_conceive(species: str, model: Optional[str] = None):
    """Conceive — synchronous. Returns ConceptionResult."""
    _validate_species(species)

    try:
        result = conceive(species=species, model=model)
        # Save each baby
        for baby in result.babies:
            registry.save(baby.to_dict(include_log=True))
        return result.to_dict()
    except Exception as e:
        raise HTTPException(500, f"Conception failed: {e}")


@router.get("/conceive/stream")
def do_conceive_stream(species: str, model: Optional[str] = None):
    """Conceive — SSE stream with real-time stage progress and fate rolls."""
    _validate_species(species)

    provider = os.environ.get("LLM_PROVIDER", "deepseek")

    def event_generator():
        # 1. Environment first (affects all rolls)
        env = generate_environment()
        yield _sse({"event": "environment", "result": env})

        miscarriage_mod = get_miscarriage_risk_modifier(env)
        defect_mod = get_defect_risk_modifier(env)

        # 2. Miscarriage roll
        miscarriage_fate = roll_miscarriage(species, env_risk_modifier=miscarriage_mod)
        yield _sse({"event": "fate_roll", "type": "miscarriage", "result": miscarriage_fate})

        if miscarriage_fate["miscarriage"]:
            yield _sse({"event": "miscarriage", "message": f"Miscarriage at early stage (rate: {miscarriage_fate.get('adjusted_rate', 0):.1%})"})
            return

        # 3. Offspring count
        offspring_count = roll_multiples(species)
        yield _sse({"event": "fate_roll", "type": "offspring_count", "result": offspring_count})

        # 4. Develop each offspring
        now = datetime.now(timezone.utc)
        babies = []

        for idx in range(offspring_count):
            sex = determine_sex(species)
            phenotype = determine_phenotype(species)
            defects = roll_congenital_defects(species, env_risk_modifier=defect_mod)
            preterm = roll_preterm(species)
            is_stillborn = roll_stillbirth(species, env_risk_modifier=defect_mod)

            yield _sse({
                "event": "offspring_fate",
                "index": idx,
                "sex": sex,
                "phenotype": phenotype,
                "defects": defects,
                "preterm": preterm,
                "stillborn": is_stillborn,
            })

            # Five-stage development
            gestation_log = []
            development_failed = False

            for event in express_stream(
                species, sex=sex, phenotype=phenotype,
                environment=env, defects=defects,
                offspring_count=offspring_count, birth_order=idx,
                provider=provider, model=model,
            ):
                if event.get("status") == "failed":
                    yield _sse({"event": "development_failed", "index": idx, **event})
                    development_failed = True
                    break

                if event["stage"] == "complete":
                    result = event["result"]
                    baby = Baby(
                        id=generate_id(now, index=idx),
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
            "total_conceived": offspring_count,
            "total_born": len(babies),
            "total_alive": sum(1 for b in babies if b.alive),
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


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
