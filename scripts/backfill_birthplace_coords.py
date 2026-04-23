"""
回填 archive/*/birth.json + state.json 的 birthplace.coordinates 和 birthplace.city。

本脚本处理两种历史形态：

  形态 A（国家中心点）：coordinates == regions.yaml[code].coordinates
    → 按 baby_id hash 派生 seed → sample_city_and_point → 同时填 coordinates + city

  形态 B（已采样但无 city）：coordinates 已是随机点但 birthplace 无 city 字段或 city=None
    → 保持 coordinates 不变 → nearest_city 反查最近城市名 → 仅补 city 字段

  形态 C（完整）：coordinates 非中心点且 city 已有值
    → 跳过（幂等）

原子写入 + 可 dry-run（默认）。--apply 才真写。

[INPUT]: backend/archive/, backend/womb/data/{regions.yaml, countries.geojson, cities.csv, iso_alpha2_to_numeric.json}
[OUTPUT]: 修改 archive/{baby_id}/{birth.json, state.json} 的 birthplace 字段
[POS]: scripts/ 一次性回填工具，对应 add-birthplace-geo-sampling 历史数据修复
[PROTOCOL]: 变更时更新此头部
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import os
import random
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
ARCHIVE_DIR = ROOT / "backend" / "archive"
REGIONS_PATH = ROOT / "backend" / "womb" / "data" / "regions.yaml"
GS_PATH = ROOT / "backend" / "womb" / "geo_sampler.py"

# 加载 geo_sampler（绕开 womb/__init__.py 的循环 import 链）
sys.path.insert(0, str(ROOT / "backend"))
_spec = importlib.util.spec_from_file_location("geo_sampler", GS_PATH)
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)  # type: ignore


def load_country_centers() -> dict[str, dict]:
    data = yaml.safe_load(REGIONS_PATH.read_text(encoding="utf-8"))
    return {c["code"].upper(): c.get("coordinates") or {} for c in data.get("countries", [])}


def coords_equal(a: dict, b: dict, tol: float = 1e-6) -> bool:
    if not a or not b:
        return False
    try:
        return abs(a["lat"] - b["lat"]) < tol and abs(a["lng"] - b["lng"]) < tol
    except (KeyError, TypeError):
        return False


def stable_seed(baby_id: str) -> int:
    """从 baby_id 派生确定性 seed → 同一 baby 多次回填同一坐标"""
    h = hashlib.sha1(baby_id.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def process_archive(baby_dir: Path, centers: dict[str, dict], apply: bool) -> dict:
    """处理单个 archive 目录，返回 stats dict"""
    baby_id = baby_dir.name
    result = {"baby_id": baby_id, "files_changed": [], "skipped_reasons": []}

    birth_path = baby_dir / "birth.json"
    state_path = baby_dir / "state.json"

    if not birth_path.exists():
        result["skipped_reasons"].append("no birth.json")
        return result

    birth = json.loads(birth_path.read_text(encoding="utf-8"))
    bp = birth.get("birthplace") or {}
    code = (bp.get("code") or "").upper()
    coords = bp.get("coordinates") or {}
    existing_city = bp.get("city")

    if not code:
        result["skipped_reasons"].append("no birthplace.code")
        return result

    center = centers.get(code) or {}
    is_center_point = coords_equal(coords, center)
    has_city = isinstance(existing_city, str) and existing_city

    if not is_center_point and has_city:
        result["skipped_reasons"].append(f"complete: city={existing_city}, coords=({coords.get('lat')},{coords.get('lng')})")
        return result

    new_coords: dict | None = None
    new_city: str | None = None
    op_label: str

    if is_center_point:
        # 形态 A：国家中心点，重新采样 coordinates + city
        random.seed(stable_seed(baby_id))
        sampled = gs.sample_city_and_point(code)
        if sampled is None:
            result["skipped_reasons"].append(f"sampler returned None for {code}")
            return result
        new_coords = {"lat": sampled["lat"], "lng": sampled["lng"]}
        new_city = sampled.get("city")
        op_label = "resample"
    else:
        # 形态 B：坐标已有但 city 缺失，反查最近城市
        new_coords = coords  # 不动
        new_city = gs.nearest_city(code, coords["lat"], coords["lng"])
        if new_city is None:
            result["skipped_reasons"].append(f"no city data for {code}, cannot fill city field")
            # 仍然把 city 字段显式置 None 补齐 schema
            new_city = None
        op_label = "fill-city"

    log.info(
        "%s [%s] %s: %.4f,%.4f city=%r → %.4f,%.4f city=%r",
        baby_id, code, op_label,
        coords.get("lat", 0.0), coords.get("lng", 0.0), existing_city,
        new_coords["lat"], new_coords["lng"], new_city,
    )

    # 写 birth.json
    birth["birthplace"]["coordinates"] = new_coords
    birth["birthplace"]["city"] = new_city
    if apply:
        atomic_write_json(birth_path, birth)
    result["files_changed"].append("birth.json")

    # 同步 state.json（如存在且 birthplace 也存了同一份 code）
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        sbp = state.get("birthplace")
        if isinstance(sbp, dict) and (sbp.get("code") or "").upper() == code:
            state["birthplace"]["coordinates"] = new_coords
            state["birthplace"]["city"] = new_city
            if apply:
                atomic_write_json(state_path, state)
            result["files_changed"].append("state.json")

    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写。默认 dry-run。")
    ap.add_argument("--archive-dir", default=str(ARCHIVE_DIR), help="archive 根目录")
    args = ap.parse_args()

    archive_dir = Path(args.archive_dir)
    if not archive_dir.is_dir():
        log.error("archive dir not found: %s", archive_dir)
        sys.exit(1)

    centers = load_country_centers()
    log.info("loaded %d country centers from regions.yaml", len(centers))

    if not args.apply:
        log.warning("DRY RUN — pass --apply to actually modify files")

    stats = {"total": 0, "changed": 0, "skipped": 0}
    for baby_dir in sorted(archive_dir.iterdir()):
        if not baby_dir.is_dir():
            continue
        stats["total"] += 1
        r = process_archive(baby_dir, centers, args.apply)
        if r["files_changed"]:
            stats["changed"] += 1
        else:
            stats["skipped"] += 1
            for reason in r["skipped_reasons"]:
                log.info("SKIP %s: %s", r["baby_id"], reason)

    log.info("done: total=%d changed=%d skipped=%d apply=%s",
             stats["total"], stats["changed"], stats["skipped"], args.apply)


if __name__ == "__main__":
    main()
