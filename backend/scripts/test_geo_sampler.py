"""
geo_sampler.py 自检脚本——验证国境采样 + 人口分布 + 降级链 + 确定性。

运行方式:
    python backend/scripts/test_geo_sampler.py

[INPUT]: 无（加载 backend/womb/data/{countries.geojson, cities.csv, iso_alpha2_to_numeric.json}）
[OUTPUT]: stdout 打印各 case 结果, 全部通过则 exit 0, 任一失败 exit 1
[POS]: backend/scripts/ 的出生地采样器自检, 对应 add-birthplace-geo-sampling 任务 4.1
[PROTOCOL]: 变更时更新此头部, 然后检查 CLAUDE.md
"""

from __future__ import annotations

import importlib.util
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.normpath(os.path.join(_HERE, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

_GS_PATH = os.path.normpath(os.path.join(_HERE, "..", "womb", "geo_sampler.py"))
_spec = importlib.util.spec_from_file_location("geo_sampler", _GS_PATH)
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)  # type: ignore

from shapely.geometry import Point  # noqa: E402


def case(name: str):
    def deco(fn):
        def wrapper():
            t0 = time.time()
            try:
                fn()
            except AssertionError as e:
                print(f"FAIL {name}: {e}")
                return False
            dt = time.time() - t0
            print(f"PASS {name} ({dt:.2f}s)")
            return True
        wrapper.__case_name__ = name
        return wrapper
    return deco


# ------------------------------------------------------------
# 准备
# ------------------------------------------------------------

_INDEX = gs.load_geo_index()
assert _INDEX is not None, "geo_index 加载失败——geojson/iso_map 缺失或 shapely 不可用"


# ------------------------------------------------------------
# 核心采样正确性
# ------------------------------------------------------------

@case("sample_in_china_polygon")
def t_china_polygon():
    random.seed(1)
    poly = _INDEX["CN"]["polygon"]
    for _ in range(100):
        p = gs.sample_point_by_population("CN")
        assert p is not None, "sample returned None"
        assert poly.contains(Point(p["lng"], p["lat"])), f"outside China polygon: {p}"


@case("sample_no_duplicates_same_country")
def t_cn_no_dup():
    random.seed(2)
    seen = set()
    for _ in range(100):
        p = gs.sample_point_by_population("CN")
        seen.add((p["lat"], p["lng"]))
    assert len(seen) == 100, f"dup count: {100 - len(seen)}"


@case("japan_no_ocean")
def t_jp_no_ocean():
    random.seed(3)
    poly = _INDEX["JP"]["polygon"]
    for _ in range(100):
        p = gs.sample_point_by_population("JP")
        assert poly.contains(Point(p["lng"], p["lat"])), f"outside JP polygon: {p}"


# ------------------------------------------------------------
# 人口权重生效（Gate 3/4 硬指标）
# ------------------------------------------------------------

@case("population_weighting_china_east")
def t_cn_east():
    random.seed(4)
    N = 1000
    hit = 0
    for _ in range(N):
        p = gs.sample_point_by_population("CN")
        if 100 <= p["lng"] <= 122 and 20 <= p["lat"] <= 42:
            hit += 1
    ratio = hit / N
    print(f"  CN east belt hit: {hit}/{N} = {ratio:.1%}")
    assert ratio >= 0.80, f"east belt ratio too low: {ratio:.1%}"


@case("gobi_low_hit")
def t_gobi():
    random.seed(5)
    N = 1000
    hit = 0
    for _ in range(N):
        p = gs.sample_point_by_population("CN")
        if 85 <= p["lng"] <= 95 and 40 <= p["lat"] <= 45:
            hit += 1
    ratio = hit / N
    print(f"  CN gobi hit: {hit}/{N} = {ratio:.1%}")
    assert ratio < 0.05, f"gobi hit ratio too high: {ratio:.1%}"


@case("us_metro_concentration")
def t_us_metro():
    """人口集中度：落在任一 pop>500k 城市的 0.5° 范围内的占比 ≥ 45%"""
    random.seed(6)
    big_cities = [c for c in _INDEX["US"]["cities"] if c["population"] > 500000]
    print(f"  US big_cities (pop>500k): {len(big_cities)}")
    N = 1000
    hit = 0
    for _ in range(N):
        p = gs.sample_point_by_population("US")
        for c in big_cities:
            if abs(p["lat"] - c["lat"]) <= 0.5 and abs(p["lng"] - c["lng"]) <= 0.5:
                hit += 1
                break
    ratio = hit / N
    print(f"  US big-city vicinity hit: {hit}/{N} = {ratio:.1%}")
    assert ratio >= 0.45, f"US big-city ratio too low: {ratio:.1%}"


@case("cn_western_sparse")
def t_cn_west_sparse():
    """反向测试：西部稀疏带 lng<100 的占比 < 20%"""
    random.seed(7)
    N = 1000
    hit = sum(1 for _ in range(N) if gs.sample_point_by_population("CN")["lng"] < 100)
    ratio = hit / N
    print(f"  CN west (lng<100): {hit}/{N} = {ratio:.1%}")
    assert ratio < 0.20, f"west ratio too high: {ratio:.1%}"


# ------------------------------------------------------------
# 城市内抖动独立性
# ------------------------------------------------------------

@case("city_jitter_spread")
def t_jitter():
    random.seed(8)
    # 强制抽中同一城市（Shanghai），检查高斯抖动产生的坐标个体唯一
    shanghai = None
    for c in _INDEX["CN"]["cities"]:
        if c["city"].lower() == "shanghai":
            shanghai = c
            break
    assert shanghai is not None, "Shanghai not in CN cities"
    poly = _INDEX["CN"]["polygon"]
    sigma = gs._compute_sigma(shanghai["population"])
    seen = set()
    for _ in range(100):
        for _retry in range(gs._JITTER_MAX_TRIES):
            lat = shanghai["lat"] + random.gauss(0, sigma)
            lng = shanghai["lng"] + random.gauss(0, sigma)
            if poly.contains(Point(lng, lat)):
                seen.add((lat, lng))
                break
    assert len(seen) == 100, f"jitter dup count: {100 - len(seen)}"


# ------------------------------------------------------------
# 降级与错误路径
# ------------------------------------------------------------

@case("unknown_iso_returns_none")
def t_unknown_iso():
    assert gs.sample_point_by_population("ZZ") is None
    assert gs.sample_point_by_population("") is None


@case("l2_fallback_uniform")
def t_l2_direct():
    """L2 直调：bbox 均匀拒绝采样应返回境内点"""
    random.seed(9)
    poly = _INDEX["CN"]["polygon"]
    for _ in range(20):
        p = gs.sample_point_in_country("CN")
        assert p is not None
        assert poly.contains(Point(p["lng"], p["lat"]))


@case("chile_long_country_fast")
def t_chile():
    """狭长国家 CL 50 次采样 < 5s 且全部境内"""
    random.seed(10)
    poly = _INDEX["CL"]["polygon"]
    t0 = time.time()
    for _ in range(50):
        p = gs.sample_point_by_population("CL")
        assert p is not None
        assert poly.contains(Point(p["lng"], p["lat"]))
    dt = time.time() - t0
    print(f"  CL 50 samples in {dt:.2f}s")
    assert dt < 5.0, f"CL sampling too slow: {dt:.2f}s"


@case("seed_reproducibility")
def t_seed():
    random.seed(42)
    a = [gs.sample_point_by_population("CN") for _ in range(5)]
    random.seed(42)
    b = [gs.sample_point_by_population("CN") for _ in range(5)]
    assert a == b, f"non-deterministic: {a} vs {b}"


@case("no_duplicates_across_seeds")
def t_cross_seed_diverse():
    """不固定 seed，100 次采样去重 = 100"""
    seen = set()
    for _ in range(100):
        p = gs.sample_point_by_population("CN")
        seen.add((p["lat"], p["lng"]))
    assert len(seen) == 100


@case("shapely_unavailable_returns_none")
def t_shapely_missing():
    """monkeypatch _SHAPELY_AVAILABLE=False 清缓存 → 返回 None + 不 raise"""
    orig_avail = gs._SHAPELY_AVAILABLE
    orig_index = gs._POLY_INDEX
    orig_mtime = gs._LAST_MTIME
    orig_warn = set(gs._WARN_ONCE)
    gs._SHAPELY_AVAILABLE = False
    gs._POLY_INDEX = None
    gs._LAST_MTIME = None
    gs._WARN_ONCE.clear()
    try:
        assert gs.load_geo_index() is None
        assert gs.sample_point_by_population("CN") is None
    finally:
        gs._SHAPELY_AVAILABLE = orig_avail
        gs._POLY_INDEX = orig_index
        gs._LAST_MTIME = orig_mtime
        gs._WARN_ONCE = orig_warn


@case("cities_missing_degrades_to_l2")
def t_cities_missing():
    """mock _CITIES_PATH 指向不存在 → load 仍成功 → 所有 cities 空 → 走 L2 均匀采样"""
    import pathlib
    orig_path = gs._CITIES_PATH
    orig_index = gs._POLY_INDEX
    orig_mtime = gs._LAST_MTIME
    orig_warn = set(gs._WARN_ONCE)
    gs._CITIES_PATH = pathlib.Path("/tmp/does_not_exist_cities.csv")
    gs._POLY_INDEX = None
    gs._LAST_MTIME = None
    gs._WARN_ONCE.clear()
    try:
        idx = gs.load_geo_index()
        assert idx is not None, "geo_index should still load without cities"
        assert all(len(entry["cities"]) == 0 for entry in idx.values()), "cities should all be empty"
        random.seed(11)
        poly = idx["CN"]["polygon"]
        for _ in range(10):
            p = gs.sample_point_by_population("CN")
            assert p is not None
            assert poly.contains(Point(p["lng"], p["lat"]))
    finally:
        gs._CITIES_PATH = orig_path
        gs._POLY_INDEX = orig_index
        gs._LAST_MTIME = orig_mtime
        gs._WARN_ONCE = orig_warn


# ------------------------------------------------------------
# 运行
# ------------------------------------------------------------

def main():
    cases = [
        t_china_polygon, t_cn_no_dup, t_jp_no_ocean,
        t_cn_east, t_gobi, t_us_metro, t_cn_west_sparse,
        t_jitter,
        t_unknown_iso, t_l2_direct, t_chile,
        t_seed, t_cross_seed_diverse,
        t_shapely_missing, t_cities_missing,
    ]
    results = [c() for c in cases]
    total, passed = len(results), sum(results)
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
