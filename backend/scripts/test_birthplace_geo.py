"""
birthplace.py 与 geo_sampler 集成 + 降级链自检。

运行方式:
    python backend/scripts/test_birthplace_geo.py

[INPUT]: 无
[OUTPUT]: stdout 打印各 case 结果, 全部通过则 exit 0
[POS]: backend/scripts/ 的出生地集成测试, 对应 add-birthplace-geo-sampling 任务 4.2
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
_BP_PATH = os.path.normpath(os.path.join(_HERE, "..", "womb", "birthplace.py"))

# 绕过 womb/__init__.py（会拉起整个生物链路触发 circular import），手动加载两个纯模块
import types
_pkg = types.ModuleType("wombmini")
_pkg.__path__ = [os.path.join(_HERE, "..", "womb")]
sys.modules["wombmini"] = _pkg

_spec_gs = importlib.util.spec_from_file_location("wombmini.geo_sampler", _GS_PATH)
gs = importlib.util.module_from_spec(_spec_gs)
sys.modules["wombmini.geo_sampler"] = gs
_spec_gs.loader.exec_module(gs)  # type: ignore

# birthplace.py 里写的是 `from . import geo_sampler`；改源码字符串绕开 package relative import
with open(_BP_PATH) as f:
    _bp_src = f.read().replace("from . import geo_sampler", "import wombmini.geo_sampler as geo_sampler")
bp = types.ModuleType("wombmini.birthplace")
bp.__file__ = _BP_PATH
exec(compile(_bp_src, _BP_PATH, "exec"), bp.__dict__)
sys.modules["wombmini.birthplace"] = bp


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
        return wrapper
    return deco


# ------------------------------------------------------------

@case("diverse_coordinates_same_country")
def t_cn_diverse():
    random.seed(101)
    coords = set()
    for _ in range(50):
        r = bp.resolve_birthplace("human", "CN")
        c = (r["coordinates"]["lat"], r["coordinates"]["lng"])
        coords.add(c)
    assert len(coords) == 50, f"dup found: {50 - len(coords)}"


@case("birthplace_schema_includes_city")
def t_schema():
    r = bp.resolve_birthplace("human", "CN")
    expected_keys = {"name", "code", "city", "coordinates", "region", "race_distribution", "environment_modifiers"}
    assert set(r.keys()) == expected_keys, f"schema drift: {set(r.keys())}"
    assert set(r["coordinates"].keys()) == {"lat", "lng"}, f"coord keys: {r['coordinates'].keys()}"
    assert isinstance(r["coordinates"]["lat"], float) and isinstance(r["coordinates"]["lng"], float)
    # city 可能是 str 或 None（L2 降级）
    assert r["city"] is None or isinstance(r["city"], str), f"city type: {type(r['city'])}"


@case("fallback_when_sampler_returns_none")
def t_fallback():
    """monkeypatch sample_city_and_point → None，验证回退到 regions.yaml 中心 + city=None"""
    orig = gs.sample_city_and_point
    gs.sample_city_and_point = lambda alpha2: None
    try:
        r = bp.resolve_birthplace("human", "CN")
        # regions.yaml 中国中心是 35.86 / 104.2
        assert abs(r["coordinates"]["lat"] - 35.86) < 0.01, f"lat: {r['coordinates']['lat']}"
        assert abs(r["coordinates"]["lng"] - 104.2) < 0.01, f"lng: {r['coordinates']['lng']}"
        assert r["city"] is None, f"city should be None on fallback, got {r['city']}"
    finally:
        gs.sample_city_and_point = orig


@case("sampler_used_when_available")
def t_uses_sampler():
    """正常情况下 sampler 被调用，返回值非国家中心"""
    hit_non_center = False
    for _ in range(10):
        r = bp.resolve_birthplace("human", "CN")
        if abs(r["coordinates"]["lat"] - 35.86) > 0.1 or abs(r["coordinates"]["lng"] - 104.2) > 0.1:
            hit_non_center = True
            break
    assert hit_non_center, "all 10 samples returned near country center — sampler not invoked?"


@case("non_human_returns_none")
def t_non_human():
    assert bp.resolve_birthplace("dog") is None
    assert bp.resolve_birthplace("cat", "CN") is None


@case("city_field_populated_for_real_sample")
def t_city_field():
    """L1 路径返回 birthplace 应带 city 英文名"""
    hit_city = 0
    for _ in range(10):
        r = bp.resolve_birthplace("human", "CN")
        if isinstance(r.get("city"), str) and r["city"]:
            hit_city += 1
    assert hit_city >= 8, f"city filled only {hit_city}/10 times — L1 sampler may not be active"


# ------------------------------------------------------------

def main():
    cases = [t_cn_diverse, t_schema, t_fallback, t_uses_sampler, t_non_human, t_city_field]
    results = [c() for c in cases]
    total, passed = len(results), sum(results)
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
