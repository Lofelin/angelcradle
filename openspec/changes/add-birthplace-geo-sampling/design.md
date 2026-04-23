# 设计稿：出生地坐标按人口密度 + 国境多边形随机采样

## 1. 数据契约

### 1.1 输入 A：GeoJSON FeatureCollection

落位 `backend/womb/data/countries.geojson`，结构（来自 Natural Earth via npm `world-atlas`）：

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "156",                              // ISO 3166-1 数字代码（字符串）
      "properties": { "name": "China" },        // 英文短名
      "bbox": [73.61, 18.22, 134.75, 53.56],    // [minLng, minLat, maxLng, maxLat]
      "geometry": { "type": "MultiPolygon", "coordinates": [...] }
    }
  ]
}
```

### 1.2 输入 B：GeoNames cities15000

落位 `backend/womb/data/cities.csv`，约 33k 行，字段（CSV 头）：

```
city,lat,lng,iso2,population
```

仅保留 `feature_class == 'P'`（城市/聚居地）且 `population > 0` 的条目。源数据是 TSV 19 列，经 `scripts/build_cities_dataset.py` 过滤+裁剪+重命名为上述 5 列 CSV。

- 来源：https://download.geonames.org/export/dump/cities15000.zip
- 许可：CC BY 4.0（GeoNames），归属声明记录在 `backend/womb/data/CITIES_LICENSE.txt` + 根 `README.md`
- 备注：最初设计方案用 SimpleMaps World Cities Basic，实施阶段发现 SimpleMaps 站点被 Cloudflare 保护不可程序化下载，切换为 GeoNames。两者字段互为超集，仅数据源名称不同，其他设计不变

### 1.3 输入 C：ISO alpha-2 ↔ numeric 映射表

落位 `backend/womb/data/iso_alpha2_to_numeric.json`，约 250 行，用于把 `regions.yaml.code`（alpha-2）和 GeoJSON `feature.id`（numeric）打通：

```json
{
  "CN": "156",
  "US": "840",
  "JP": "392",
  "..." : "..."
}
```

一次性通过 `scripts/generate_iso_mapping.py` + `pycountry` 生成并 commit；prod 运行时不依赖 pycountry。

### 1.4 已有数据：`regions.yaml.countries[*]`

```yaml
- name: China
  code: CN              # ISO 3166-1 alpha-2 — 主键
  region: east_asia
  coordinates: {lat: 35.86, lng: 104.2}   # 国家中心，本变更后作为最后一级 fallback
  population_weight: 1425.0                # 抽国家用，不是抽坐标用
```

### 1.5 输出：`Baby.birthplace.coordinates`

schema 不变：`{"lat": float, "lng": float}`。变更后 `lat`/`lng` 为城市附近随机点（首选）/ 国境内随机点（降级）/ 国家中心（兜底）。

## 2. 模块设计

### 2.1 `backend/womb/geo_sampler.py` 公开 API

```python
def load_geo_index() -> dict | None
    """加载 countries.geojson + cities.csv + iso 映射，按三文件 mtime 联合失效。
    任一核心文件缺失或 shapely 不可用 → 返回 None。"""

def sample_point_by_population(alpha2: str) -> dict | None
    """
    [主入口] 按人口加权采样国境内坐标。
    
    L1 首选：城市加权 + 高斯抖动 + polygon 校验
    L2 降级：polygon 内 bbox 均匀拒绝采样
    L3 兜底：返回 None（上游 fallback 到 regions.yaml 中心）
    
    - alpha2: ISO 3166-1 alpha-2 代码（如 'CN'）
    - 返回 {"lat": float, "lng": float} 或 None
    """

def sample_point_in_country(alpha2: str, max_tries: int = 1000) -> dict | None
    """
    [fallback] 不考虑人口分布的均匀采样（README 原方案）。
    由 sample_point_by_population 在 L2 降级时内部调用，也对外暴露供调试/测试。
    """
```

### 2.2 内部状态

```python
_DATA_DIR = Path(__file__).parent / "data"
_GEOJSON_PATH = _DATA_DIR / "countries.geojson"
_CITIES_PATH  = _DATA_DIR / "cities.csv"
_ISO_MAP_PATH = _DATA_DIR / "iso_alpha2_to_numeric.json"

_LAST_MTIME: tuple[float, float, float] | None = None
_POLY_INDEX: dict[str, dict] | None = None
#   {
#     "CN": {
#       "polygon": <shapely MultiPolygon>,
#       "bbox": [minLng, minLat, maxLng, maxLat],
#       "cities": [
#         {"city": "Shanghai", "lat": 31.22, "lng": 121.47, "population": 22315000.0},
#         ...
#       ]
#     }
#   }

_SHAPELY_AVAILABLE: bool = _try_import_shapely()
_WARN_ONCE: set[str] = set()    # 防 log 刷屏
```

### 2.3 加载流程（惰性）

```
load_geo_index() 首次调用
  ├── shapely 可用？否 → warn_once("shapely_missing") → 返回 None
  ├── countries.geojson 存在？否 → warn_once("geojson_missing") → 返回 None
  ├── cities.csv 存在？否 → warn_once("cities_missing")（继续，L2 降级可用）
  ├── 读 iso_alpha2_to_numeric.json → 反向字典 numeric_to_alpha2
  ├── 解析 GeoJSON → for feat in features:
  │         numeric = str(feat['id'])
  │         alpha2 = numeric_to_alpha2.get(numeric)
  │         if not alpha2: continue
  │         _POLY_INDEX[alpha2] = {
  │             "polygon": shape(feat['geometry']),
  │             "bbox": feat['bbox'],
  │             "cities": []
  │         }
  ├── 读 cities.csv → for row in rows:
  │         iso2 = row['iso2'].upper()
  │         if iso2 not in _POLY_INDEX: continue
  │         lat, lng = float(row['lat']), float(row['lng'])
  │         pop = float(row['population']) if row['population'] else 1000.0
  │         pt = Point(lng, lat)
  │         if not _POLY_INDEX[iso2]['polygon'].contains(pt):
  │             drop_count[iso2] += 1; continue   # 脏数据过滤
  │         _POLY_INDEX[iso2]['cities'].append({
  │             "city": row['city'], "lat": lat, "lng": lng, "population": pop
  │         })
  ├── log drop_count（如 > 总城市数 0.5% 则 warn_once）
  ├── 缓存 mtime 三元组
  └── 返回索引（非 None）
```

### 2.4 `sample_point_by_population` 采样流程

```
sample_point_by_population(alpha2)
  ├── idx = load_geo_index()
  ├── idx is None → 返回 None（L3）
  ├── entry = _POLY_INDEX.get(alpha2)
  ├── entry is None → warn_once(f"alpha2_missing_{alpha2}") → 返回 None（L3）
  │
  ├── cities = entry['cities']
  ├── if cities:  # L1 首选路径
  │     city = random.choices(cities, weights=[c['population'] for c in cities], k=1)[0]
  │     σ = min(max(math.sqrt(city['population']) * 1e-4, 0.01), 0.30)
  │     poly = entry['polygon']
  │     for _ in range(10):
  │         lat = city['lat'] + random.gauss(0, σ)
  │         lng = city['lng'] + random.gauss(0, σ)
  │         if poly.contains(Point(lng, lat)):
  │             return {"lat": lat, "lng": lng}
  │     # 10 次抖动都在境外（城市贴海岸）→ 返回 city 中心点（已在境内）
  │     return {"lat": city['lat'], "lng": city['lng']}
  │
  └── else:  # L2 降级：无城市数据（极小国 or cities.csv 缺失）
        return sample_point_in_country(alpha2)  # polygon 均匀拒绝采样
```

### 2.5 `sample_point_in_country` 流程（L2 / 原 README 方案）

```
sample_point_in_country(alpha2, max_tries=1000)
  ├── idx = load_geo_index()
  ├── idx is None or alpha2 not in _POLY_INDEX → None
  ├── poly, bbox = entry['polygon'], entry['bbox']
  ├── min_lng, min_lat, max_lng, max_lat = bbox
  ├── for _ in range(max_tries):
  │     lng = random.uniform(min_lng, max_lng)
  │     lat = random.uniform(min_lat, max_lat)
  │     if poly.contains(Point(lng, lat)):
  │         return {"lat": lat, "lng": lng}
  └── warn_once(f"reject_sampling_exhausted_{alpha2}") → 返回 None
```

### 2.6 抖动 σ 公式的设计理由

`σ = clamp(sqrt(population) * 1e-4, 0.01°, 0.3°)`

| 城市 | 人口 | sqrt(pop) | σ (°) | 约 km |
|---|---|---|---|---|
| Shanghai | 22M | 4690 | 0.30（封顶） | ~33 |
| Beijing | 20M | 4470 | 0.30（封顶） | ~33 |
| Tianjin | 12M | 3460 | 0.30（封顶） | ~33 |
| Chengdu | 9M | 3000 | 0.30（封顶） | ~33 |
| 小县城 | 100k | 316 | 0.032 | ~3.5 |
| 小镇 | 10k | 100 | 0.010（下限） | ~1.1 |
| 默认兜底 | 1k | 32 | 0.010（下限） | ~1.1 |

- **为什么平方根**：真实城市建成区面积大致与人口成正比，σ 作为"半径"应与 `sqrt(area) ~ sqrt(pop)` 成正比
- **上限 0.3°（~33km）**：超大都市（北京/上海）的建成区半径约 30-40km，0.3° 恰好覆盖；再大 σ 会污染到邻近城市
- **下限 0.01°（~1.1km）**：小镇至少 1km 半径保证 baby 坐标不完全重合；σ 更小时高斯近似退化为点

## 3. `birthplace.py` 改造

仅改 `_build_birthplace_dict`：

```python
from . import geo_sampler

def _build_birthplace_dict(country: dict) -> dict:
    sampled = geo_sampler.sample_point_by_population(country.get("code", ""))
    return {
        "name": country["name"],
        "code": country["code"],
        "coordinates": sampled or country.get("coordinates", {}),
        "region": country.get("region", ""),
        "race_distribution": country.get("race_distribution", {}),
        "environment_modifiers": country.get("environment_modifiers", {}),
    }
```

L3 头部注释 `[INPUT]` 行追加 `geo_sampler`。

## 4. 边界场景与处理策略

| 场景 | 行为 |
|------|------|
| `shapely` 未安装 | `_SHAPELY_AVAILABLE = False`，`load_geo_index` 返回 None；整链路降级到中心点；启动 warn 一次 |
| `countries.geojson` 缺失 | `load_geo_index` 返回 None；降级同上 |
| `cities.csv` 缺失 | `_POLY_INDEX[*].cities = []`，L1 跳过，直接走 L2 polygon 均匀采样；warn 一次 |
| `iso_alpha2_to_numeric.json` 缺失 | 严重错误（本变更必带文件），`load_geo_index` 返回 None；降级中心点 |
| `regions.yaml.code` 为空 | `_POLY_INDEX[""]` miss → L3 → 回退中心点 |
| GeoNames 某城市经纬度在国境外（脏数据） | 加载阶段 drop + 计数；total drop > 0.5% 时 warn_once |
| 大都市抖动 10 次全越界 | 返回 city 中心点（已在境内）——不再降级，因 L1 已基本达成目标 |
| 某国只有 1 个城市（如梵蒂冈附近可能只采到 "Vatican City" 1 条） | `random.choices` 每次都抽这个 city，但高斯抖动仍给出不同坐标 |
| 某国城市数为 0（数据未覆盖） | 直接 L2 polygon 均匀采样 |
| GeoJSON `feature.id` 是整数而非字符串 | 加载时统一 `str(feat['id'])` |
| `MultiPolygon` 多块（美国本土 + 阿拉斯加 + 夏威夷） | `polygon.contains` 天然正确；L1 抽城市时 Alaska 城市 population 远低于加州/纽约，自然权重极低 |
| 流产 baby（`status="miscarriage"`） | birthplace 仍正常采样（流产前已决定了出生地概念） |
| `random` 共享状态污染测试 | 测试内 `random.seed(42)`；如需隔离，后续把 `random.gauss/choices/uniform` 改为 `random.Random(seed)` 实例（本期不做） |

## 5. 缓存与性能

- **加载阶段**：首次调用 `load_geo_index` 解析 3.8MB GeoJSON + 构建 241 MultiPolygon + 读 44k 城市 CSV + 过滤，预估 300-700ms（一次性）
- **L1 稳态采样**：一次 `random.choices`（O(N) with N=城市数） + 最多 10 次 `random.gauss + polygon.contains`，90% 场景 < 2ms
- **L2 稳态采样**：bbox 拒绝采样，命中率通常 > 30%，< 5ms
- **mtime 失效**：三文件 mtime 联合判定，任一变更即失效重载，开发期热替换友好

## 6. 测试计划

`backend/tests/test_geo_sampler.py`：

```python
def test_sample_in_china_polygon():
    """100 次采样全部落入中国多边形（shapely.contains 二次校验）"""

def test_population_weighting_china():
    """CN 1000 次采样中，落在东部人口带 bbox [lng 100-122, lat 20-42] 的占比 ≥ 80%"""

def test_gobi_low_hit():
    """CN 1000 次采样中，落在戈壁核心 bbox [lng 85-95, lat 40-45] 的占比 < 5%"""

def test_us_metro_concentration():
    """US 1000 次采样中，落在 NY/LA/CHI 任一 bbox 的占比 ≥ 25%"""

def test_city_jitter_spread():
    """固定 random.seed 前提下，对 Shanghai city 抽 100 次（直接走 L1 + jitter），coordinates 去重 = 100"""

def test_sample_no_duplicates_same_country():
    """CN 100 次采样去重 size = 100"""

def test_japan_no_ocean():
    """JP 100 次采样，0 个点落在日本海或太平洋（polygon.contains 校验）"""

def test_unknown_iso_returns_none():
    """sample_point_by_population('ZZ') 返回 None（不 raise）"""

def test_small_country_fallback_to_l2():
    """某国 cities 列表为空时，自动走 L2 polygon 均匀采样，返回的点仍在 polygon 内"""

def test_seed_reproducibility():
    """random.seed(42) 两次调用字节相等"""

def test_chile_long_country():
    """CL 50 次采样不超 5s 且全部落在境内（L1 路径，命中率应很高）"""

def test_shapely_unavailable_returns_none(monkeypatch):
    """monkeypatch _SHAPELY_AVAILABLE = False → sample_point_by_population 返回 None"""

def test_cities_csv_missing_fallback(monkeypatch, tmp_path):
    """cities.csv 不存在时，L1 不可用，自动走 L2，返回仍合法"""
```

`backend/tests/test_birthplace.py`：

```python
def test_birthplace_coordinates_diverse_within_country():
    """resolve_birthplace('human', 'CN') × 50，coordinates 去重 = 50"""

def test_birthplace_fallback_when_sampler_fails(monkeypatch):
    """mock geo_sampler.sample_point_by_population → None，验证回退到 country.coordinates"""

def test_birthplace_schema_unchanged():
    """返回 dict 顶层键 = {name, code, coordinates, region, race_distribution, environment_modifiers}"""
```

## 7. 文档同步清单（落地时）

- `backend/womb/CLAUDE.md`：
  - 「地理维度」段新增：`geo_sampler.py: GeoJSON+城市人口的分层采样器（城市加权+抖动 → polygon 均匀 → 中心点兜底）`
  - 「数据」段 `data/` 展开：`regions.yaml` / `countries.geojson` / `cities.csv` / `iso_alpha2_to_numeric.json` / `CITIES_LICENSE.txt`
- `backend/womb/birthplace.py` 头部 `[INPUT]` 追加 `geo_sampler`
- `backend/womb/geo_sampler.py` 头部按 L3 模板写完整（INPUT/OUTPUT/POS/PROTOCOL）
- `README.md`（项目根）：加一行 "City data © GeoNames, CC BY 4.0 (https://download.geonames.org)"
- 根 `CLAUDE.md` / `backend/CLAUDE.md`：预计无需变更

## 8. 与设计模式三问的回答（强制产物）

- **主角**：`Baby.birthplace.coordinates` —— 每个 baby 个体独立的地理标识
- **核心不变量**：「同一国家分配的 N 个 baby → N 个不同坐标 ∧ 每个坐标都严格落在该国境多边形内 ∧ 整体分布匹配真实人口密度（大都市高、荒漠/极地低）」
- **spec 元字段使用情况**：
  - **用了**：
    - GeoJSON `feature.id`（ISO 数字码）作为对齐键（经映射转 alpha-2）
    - GeoJSON `feature.bbox` 作为 L2 降级采样空间
    - GeoJSON `feature.geometry`（MultiPolygon）作为合法性判定
    - GeoNames `iso2` 作为分组键
    - GeoNames `lat` / `lng` 作为抖动中心
    - GeoNames `population` 作为加权抽样权重 **和** 抖动 σ 的输入（sqrt 缩放）
  - **忽略**：
    - GeoJSON `feature.properties.name`（用 iso2 替代，避开英文名分歧）
    - GeoNames `city_ascii` / `admin_name` / `capital` / `iso3` / `id`（采样不需要）
    - `regions.yaml.population_weight`（那是抽"哪个国家"用的，不参与坐标采样）
