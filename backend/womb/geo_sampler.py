"""
出生地坐标采样器：GeoJSON 国境 + GeoNames 城市人口的分层加权采样。

三级降级链：
  L1 首选 sample_point_by_population: 城市加权 + 高斯抖动 + polygon 校验
  L2 降级 sample_point_in_country:    polygon 内 bbox 均匀拒绝采样（README 原方案）
  L3 兜底 返回 None:                   上游 birthplace.py 回退 regions.yaml 中心点

任一外部数据（shapely/countries.geojson/cities.csv/iso_alpha2_to_numeric.json）
缺失时自动向下跌级，不 raise 中断 conceive 流程。

[INPUT]: backend/womb/data/{countries.geojson, cities.csv, iso_alpha2_to_numeric.json}
         shapely>=2.0（可选，缺失时整链路降级）
[OUTPUT]: 导出 load_geo_index, sample_point_by_population, sample_point_in_country
[POS]: womb/ 的地理维度采样基础设施，被 birthplace.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import csv
import json
import logging
import math
import random
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from shapely.geometry import Point, shape
    from shapely.validation import make_valid
    _SHAPELY_AVAILABLE = True
except ImportError:
    Point = None  # type: ignore
    shape = None  # type: ignore
    make_valid = None  # type: ignore
    _SHAPELY_AVAILABLE = False

_DATA_DIR = Path(__file__).parent / "data"
_GEOJSON_PATH = _DATA_DIR / "countries.geojson"
_CITIES_PATH = _DATA_DIR / "cities.csv"
_ISO_MAP_PATH = _DATA_DIR / "iso_alpha2_to_numeric.json"

_POLY_INDEX: dict[str, dict] | None = None
_LAST_MTIME: tuple[float, float, float] | None = None
_WARN_ONCE: set[str] = set()

_JITTER_SIGMA_MIN = 0.01
_JITTER_SIGMA_MAX = 0.30
_JITTER_SIGMA_SCALE = 1e-4
_JITTER_MAX_TRIES = 10
_BBOX_MAX_TRIES = 1000


def _warn_once(key: str, msg: str) -> None:
    if key in _WARN_ONCE:
        return
    _WARN_ONCE.add(key)
    logger.warning(msg)


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _cache_valid() -> bool:
    if _POLY_INDEX is None or _LAST_MTIME is None:
        return False
    current = (_file_mtime(_GEOJSON_PATH), _file_mtime(_CITIES_PATH), _file_mtime(_ISO_MAP_PATH))
    return current == _LAST_MTIME


def load_geo_index() -> dict | None:
    """加载 GeoJSON + cities.csv + ISO 映射，构建 alpha2 → {polygon, bbox, cities} 索引。

    返回 None 表示整链路不可用（shapely 缺失 / geojson 缺失 / iso 映射缺失）。
    cities.csv 缺失不返回 None，只是所有国家的 cities 列表为空（L2 降级仍可用）。
    """
    global _POLY_INDEX, _LAST_MTIME

    if _cache_valid():
        return _POLY_INDEX

    if not _SHAPELY_AVAILABLE:
        _warn_once("shapely_missing", "shapely not installed; birthplace sampling disabled")
        return None

    if not _GEOJSON_PATH.is_file():
        _warn_once("geojson_missing", f"{_GEOJSON_PATH} not found; birthplace sampling disabled")
        return None

    if not _ISO_MAP_PATH.is_file():
        _warn_once("iso_map_missing", f"{_ISO_MAP_PATH} not found; birthplace sampling disabled")
        return None

    try:
        iso_alpha2_to_numeric: dict[str, str] = json.loads(_ISO_MAP_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        _warn_once("iso_map_parse_error", f"failed to parse {_ISO_MAP_PATH}: {e}")
        return None
    numeric_to_alpha2 = {v: k for k, v in iso_alpha2_to_numeric.items()}

    try:
        geo = json.loads(_GEOJSON_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        _warn_once("geojson_parse_error", f"failed to parse {_GEOJSON_PATH}: {e}")
        return None

    index: dict[str, dict] = {}
    for feat in geo.get("features", []):
        numeric = str(feat.get("id") or "").zfill(3)
        alpha2 = numeric_to_alpha2.get(numeric)
        if not alpha2:
            continue
        try:
            polygon = shape(feat["geometry"])
            if not polygon.is_valid:
                polygon = make_valid(polygon)
        except Exception:
            continue
        bbox = feat.get("bbox")
        if not bbox or len(bbox) < 4:
            try:
                bbox = list(polygon.bounds)
            except Exception:
                continue
        index[alpha2] = {"polygon": polygon, "bbox": bbox, "cities": []}

    if _CITIES_PATH.is_file():
        drop_total = 0
        keep_total = 0
        with _CITIES_PATH.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                iso2 = (row.get("iso2") or "").strip().upper()
                if not iso2 or iso2 not in index:
                    continue
                try:
                    lat = float(row["lat"])
                    lng = float(row["lng"])
                except (KeyError, ValueError):
                    continue
                pop_raw = (row.get("population") or "").strip()
                try:
                    pop = float(pop_raw) if pop_raw else 1000.0
                except ValueError:
                    pop = 1000.0
                if pop <= 0:
                    pop = 1000.0
                entry = index[iso2]
                try:
                    inside = entry["polygon"].contains(Point(lng, lat))
                except Exception:
                    drop_total += 1
                    continue
                if not inside:
                    drop_total += 1
                    continue
                entry["cities"].append({
                    "city": row.get("city") or "",
                    "lat": lat,
                    "lng": lng,
                    "population": pop,
                })
                keep_total += 1
        logger.info("cities loaded: kept=%d dropped_out_of_polygon=%d", keep_total, drop_total)
        if keep_total > 0 and drop_total > keep_total * 0.005:
            _warn_once("cities_drop_high", f"dropped {drop_total} cities outside country polygons (> 0.5%)")
    else:
        _warn_once("cities_missing", f"{_CITIES_PATH} not found; falling back to uniform polygon sampling")

    _POLY_INDEX = index
    _LAST_MTIME = (_file_mtime(_GEOJSON_PATH), _file_mtime(_CITIES_PATH), _file_mtime(_ISO_MAP_PATH))
    logger.info("geo_sampler loaded: %d countries indexed", len(index))
    return _POLY_INDEX


def _compute_sigma(population: float) -> float:
    raw = math.sqrt(max(population, 1.0)) * _JITTER_SIGMA_SCALE
    return max(_JITTER_SIGMA_MIN, min(_JITTER_SIGMA_MAX, raw))


def sample_city_and_point(alpha2: str) -> dict | None:
    """按人口加权采样国境内坐标，同时返回被抽中的城市名（主入口）。

    成功返回 {"city": str | None, "lat": float, "lng": float}。
    L1（城市加权）路径 city 为该城市英文名；
    L2（polygon 均匀降级）路径 city 为 None。
    任何失败路径返回 None，由调用方决定回退。
    """
    if not alpha2:
        return None
    index = load_geo_index()
    if index is None:
        return None

    entry = index.get(alpha2.upper())
    if entry is None:
        _warn_once(f"alpha2_missing_{alpha2}", f"alpha2 '{alpha2}' not in geo index; fallback upstream")
        return None

    cities = entry["cities"]
    if cities:
        weights = [c["population"] for c in cities]
        city = random.choices(cities, weights=weights, k=1)[0]
        sigma = _compute_sigma(city["population"])
        polygon = entry["polygon"]
        for _ in range(_JITTER_MAX_TRIES):
            lat = city["lat"] + random.gauss(0, sigma)
            lng = city["lng"] + random.gauss(0, sigma)
            try:
                if polygon.contains(Point(lng, lat)):
                    return {"city": city["city"], "lat": lat, "lng": lng}
            except Exception:
                continue
        return {"city": city["city"], "lat": city["lat"], "lng": city["lng"]}

    # L2 降级：polygon 均匀采样，无 city 归属
    point = sample_point_in_country(alpha2)
    if point is None:
        return None
    return {"city": None, **point}


def sample_point_by_population(alpha2: str) -> dict | None:
    """向后兼容薄层：只返回 {lat, lng}，不含 city 字段。"""
    result = sample_city_and_point(alpha2)
    if result is None:
        return None
    return {"lat": result["lat"], "lng": result["lng"]}


def nearest_city(alpha2: str, lat: float, lng: float) -> str | None:
    """对已有坐标反查最近城市名（用于历史数据回填 city 字段）。

    使用粗略的等距网格（经纬度差平方和）近似最近距离，对 city 名单级别的精度足够。
    没有城市索引时返回 None。
    """
    if not alpha2:
        return None
    index = load_geo_index()
    if index is None:
        return None
    entry = index.get(alpha2.upper())
    if entry is None:
        return None
    cities = entry["cities"]
    if not cities:
        return None
    best = min(cities, key=lambda c: (c["lat"] - lat) ** 2 + (c["lng"] - lng) ** 2)
    return best["city"]


def sample_point_in_country(alpha2: str, max_tries: int = _BBOX_MAX_TRIES) -> dict | None:
    """polygon 内 bbox 均匀拒绝采样（L2 降级 / README 原方案）。

    成功返回 {"lat": float, "lng": float}；失败返回 None。
    """
    if not alpha2:
        return None
    index = load_geo_index()
    if index is None:
        return None

    entry = index.get(alpha2.upper())
    if entry is None:
        return None

    polygon = entry["polygon"]
    bbox = entry["bbox"]
    min_lng, min_lat, max_lng, max_lat = bbox[0], bbox[1], bbox[2], bbox[3]
    for _ in range(max_tries):
        lng = random.uniform(min_lng, max_lng)
        lat = random.uniform(min_lat, max_lat)
        try:
            if polygon.contains(Point(lng, lat)):
                return {"lat": lat, "lng": lng}
        except Exception:
            continue

    _warn_once(f"reject_exhausted_{alpha2}", f"rejection sampling exhausted after {max_tries} tries for {alpha2}")
    return None
