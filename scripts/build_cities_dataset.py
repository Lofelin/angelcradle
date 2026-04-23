"""
一次性脚本：下载 GeoNames cities15000 并转换为 backend/womb/data/cities.csv。

数据来源：https://download.geonames.org/export/dump/cities15000.zip
  - 字段（TSV，无表头）：
      0 geonameid    1 name         2 asciiname   3 alternatenames
      4 latitude     5 longitude    6 feature_class
      7 feature_code 8 country_code 9 cc2
      10 admin1    11 admin2    12 admin3    13 admin4
      14 population 15 elevation 16 dem   17 timezone 18 modification_date
  - 仅保留 feature_class == 'P'（城市/聚居地）且 population > 0 的条目
  - 产物 CSV 列：city, lat, lng, iso2, population

许可：GeoNames 数据采用 CC BY 4.0（https://creativecommons.org/licenses/by/4.0/）。
产物要在产品文档标注归属。

用法：
    python scripts/build_cities_dataset.py
"""
from __future__ import annotations

import csv
import io
import logging
import sys
import urllib.request
import zipfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

URL = "https://download.geonames.org/export/dump/cities15000.zip"
OUT_PATH = Path(__file__).parent.parent / "backend" / "womb" / "data" / "cities.csv"


def fetch_tsv() -> str:
    log.info("downloading %s", URL)
    with urllib.request.urlopen(URL, timeout=120) as resp:
        blob = resp.read()
    log.info("downloaded %d bytes", len(blob))
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        with zf.open("cities15000.txt") as f:
            return f.read().decode("utf-8")


def convert(tsv: str) -> list[dict]:
    rows: list[dict] = []
    dropped_non_city = 0
    dropped_no_pop = 0
    dropped_bad_coord = 0

    for line in tsv.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 19:
            continue
        feat_class = parts[6]
        if feat_class != "P":
            dropped_non_city += 1
            continue
        try:
            lat = float(parts[4])
            lng = float(parts[5])
        except ValueError:
            dropped_bad_coord += 1
            continue
        iso2 = parts[8].strip().upper()
        if not iso2 or len(iso2) != 2:
            continue
        try:
            population = int(parts[14]) if parts[14] else 0
        except ValueError:
            population = 0
        if population <= 0:
            dropped_no_pop += 1
            continue
        name = parts[1] or parts[2]
        rows.append({
            "city": name,
            "lat": f"{lat:.5f}",
            "lng": f"{lng:.5f}",
            "iso2": iso2,
            "population": population,
        })

    log.info(
        "kept=%d dropped_non_city=%d dropped_no_pop=%d dropped_bad_coord=%d",
        len(rows), dropped_non_city, dropped_no_pop, dropped_bad_coord,
    )
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["city", "lat", "lng", "iso2", "population"])
        writer.writeheader()
        writer.writerows(rows)
    log.info("wrote %d rows to %s (%.1f KB)", len(rows), path, path.stat().st_size / 1024)


def main() -> None:
    tsv = fetch_tsv()
    rows = convert(tsv)
    if not rows:
        log.error("no rows kept")
        sys.exit(1)
    write_csv(rows, OUT_PATH)


if __name__ == "__main__":
    main()
