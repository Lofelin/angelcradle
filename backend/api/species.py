from fastapi import APIRouter

from womb.genetics import SPECIES_DIR

router = APIRouter()


@router.get("/species")
def list_species():
    species = sorted(p.stem for p in SPECIES_DIR.glob("*.yaml"))
    return {"species": species}
