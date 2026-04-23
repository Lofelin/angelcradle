"""
出生地系统：地区数据加载、人口加权掷骰、环境修正提取。

仅 human 物种支持。非 human 物种所有函数返回 None。

[INPUT]: womb/data/regions.yaml, womb/geo_sampler（坐标采样）
[OUTPUT]: 导出 load_regions, roll_birthplace, resolve_birthplace, get_race_weights, get_environment_bias
[POS]: womb/ 的地理维度基础设施，被 __init__.py 和 api/conceive.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

import yaml

from . import geo_sampler

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent / "data"
_REGIONS_CACHE: dict | None = None
_REGIONS_CACHE_MTIME: float | None = None


def load_regions() -> dict:
    """加载 regions.yaml，按文件 mtime 自动失效。缺失或格式错误时返回空结构。"""
    global _REGIONS_CACHE, _REGIONS_CACHE_MTIME

    path = _DATA_DIR / "regions.yaml"
    if not path.is_file():
        if _REGIONS_CACHE is None:
            logger.warning("regions.yaml not found at %s, birthplace disabled", path)
        _REGIONS_CACHE = {"regional_defaults": {}, "countries": []}
        _REGIONS_CACHE_MTIME = None
        return _REGIONS_CACHE

    mtime = path.stat().st_mtime
    if _REGIONS_CACHE is not None and _REGIONS_CACHE_MTIME == mtime:
        return _REGIONS_CACHE

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "countries" not in data:
            raise ValueError("Invalid regions.yaml structure")
        _REGIONS_CACHE = data
        _REGIONS_CACHE_MTIME = mtime
        logger.info("Loaded regions.yaml: %d countries", len(data.get("countries", [])))
    except Exception as e:
        logger.warning("Failed to load regions.yaml: %s, birthplace disabled", e)
        _REGIONS_CACHE = {"regional_defaults": {}, "countries": []}
        _REGIONS_CACHE_MTIME = mtime

    return _REGIONS_CACHE


def _build_birthplace_dict(country: dict) -> dict:
    """从国家条目构建标准化的 birthplace dict。

    coordinates + city 按三级降级链生成：
      L1 geo_sampler.sample_city_and_point — 城市加权 + 高斯抖动，city 为英文城市名
      L2 geo_sampler 内部降级到 polygon 均匀采样，city 为 None
      L3 regions.yaml 的国家中心点（shapely/数据不可用时），city 为 None
    """
    sampled = geo_sampler.sample_city_and_point(country.get("code", ""))
    if sampled is not None:
        coordinates = {"lat": sampled["lat"], "lng": sampled["lng"]}
        city = sampled.get("city")
    else:
        coordinates = country.get("coordinates", {})
        city = None
    return {
        "name": country["name"],
        "code": country["code"],
        "city": city,
        "coordinates": coordinates,
        "region": country.get("region", ""),
        "race_distribution": country.get("race_distribution", {}),
        "environment_modifiers": country.get("environment_modifiers", {}),
    }


def roll_birthplace(species: str) -> dict | None:
    """人口加权随机抽取出生国家。非 human 返回 None。"""
    if species != "human":
        return None

    regions = load_regions()
    countries = regions.get("countries", [])
    if not countries:
        return None

    weights = [c.get("population_weight", 1.0) for c in countries]
    selected = random.choices(countries, weights=weights, k=1)[0]
    return _build_birthplace_dict(selected)


def resolve_birthplace(species: str, birthplace_input: str | None = None) -> dict | None:
    """
    解析出生地。

    - species != "human": 返回 None
    - birthplace_input 为 None: 人口加权随机
    - birthplace_input 为 ISO code 或国家名: 查找匹配
    - 无匹配: log warning, fallback 到随机
    """
    if species != "human":
        return None

    if birthplace_input is None:
        return roll_birthplace(species)

    regions = load_regions()
    countries = regions.get("countries", [])
    query = birthplace_input.strip().upper()

    # 精确匹配 ISO code
    for c in countries:
        if c.get("code", "").upper() == query:
            return _build_birthplace_dict(c)

    # 模糊匹配国家名
    query_lower = birthplace_input.strip().lower()
    for c in countries:
        if c.get("name", "").lower() == query_lower:
            return _build_birthplace_dict(c)

    logger.warning("Birthplace '%s' not found in regions.yaml, falling back to random", birthplace_input)
    return roll_birthplace(species)


def get_race_weights(birthplace: dict | None) -> dict | None:
    """提取出生地的 race 概率分布。"""
    if birthplace is None:
        return None
    return birthplace.get("race_distribution") or None


def get_environment_bias(birthplace: dict | None) -> dict | None:
    """提取出生地的环境修正系数。"""
    if birthplace is None:
        return None
    return birthplace.get("environment_modifiers") or None
