# 任务清单：add-birthplace-geo-sampling

## 1. 数据与依赖（Phase A）

- [ ] 1.1 拷贝 `/Users/lifulin/Downloads/fileswww/countries.geojson` → `backend/womb/data/countries.geojson`
- [ ] 1.2 从 https://download.geonames.org/export/dump/cities15000.zip 下载 GeoNames World Cities Basic（免费版，Basic）→ 解压 `worldcities.csv` 重命名为 `backend/womb/data/cities.csv`；记录版本号
- [ ] 1.3 生成 `backend/womb/data/iso_alpha2_to_numeric.json`（一次性脚本 `scripts/generate_iso_mapping.py` 用 `pycountry` 生成，prod 不依赖 pycountry）
- [ ] 1.4 新建 `backend/womb/data/CITIES_LICENSE.txt`，内容 = GeoNames 的 CC BY 4.0 归属声明 + 下载日期 + 版本号
- [ ] 1.5 更新根 `README.md` 加一行 "City data © GeoNames, CC BY 4.0 (https://download.geonames.org/export/dump/cities15000.zip)"
- [ ] 1.6 `backend/pyproject.toml` `dependencies` 追加 `"shapely>=2.0"`
- [ ] 1.7 验证 `pip install -e backend/` 在本机 Python 3.9+ 上成功，`python -c "from shapely.geometry import shape, Point; print('ok')"` 通过
- [ ] 1.8 冒烟验证数据：
  - `python -c "import csv; print(sum(1 for _ in csv.DictReader(open('backend/womb/data/cities.csv'))))"` 应 > 40000
  - `python -c "import json; print(json.load(open('backend/womb/data/iso_alpha2_to_numeric.json'))['CN'])"` 应输出 `156`

## 2. geo_sampler 模块（Phase B）

- [ ] 2.1 新建 `backend/womb/geo_sampler.py`，文件头 L3 注释完整（INPUT/OUTPUT/POS/PROTOCOL）
- [ ] 2.2 实现 try-import shapely 守卫；`_SHAPELY_AVAILABLE` 标志；`warn_once` 防刷屏工具
- [ ] 2.3 实现 `load_geo_index()`：三文件 mtime 联合缓存失效 + GeoJSON 解析 + cities.csv 读取（按 iso2 分组 + polygon.contains 脏数据过滤）+ 构建 `_POLY_INDEX`
- [ ] 2.4 实现 `sample_point_in_country(alpha2, max_tries=1000)`（L2 fallback，bbox 均匀拒绝采样）
- [ ] 2.5 实现 `sample_point_by_population(alpha2)`（L1 首选：`random.choices` 按 population 加权 → `σ = clamp(sqrt(pop)*1e-4, 0.01, 0.3)` 高斯抖动 → polygon.contains 校验 → 10 次内成功返回或回退 city 中心 → 城市表空时调 `sample_point_in_country` L2 降级）
- [ ] 2.6 所有 warn 用 `warn_once(key)` 避免刷屏；key 如 `"shapely_missing"`, `"cities_missing"`, `"alpha2_missing_ZZ"`, `"reject_sampling_exhausted_CL"`
- [ ] 2.7 冒烟：
  - `python -c "from backend.womb.geo_sampler import sample_point_by_population; print(sample_point_by_population('CN'))"` 输出合法点
  - 连续 10 次输出应均不相同

## 3. 接入 birthplace（Phase C）

- [ ] 3.1 修改 `backend/womb/birthplace.py` 的 `_build_birthplace_dict`：调用 `geo_sampler.sample_point_by_population(country['code'])`，None 时回退 `country.get('coordinates', {})`
- [ ] 3.2 更新 `birthplace.py` 头部 `[INPUT]` 行追加 `geo_sampler`
- [ ] 3.3 跑一次 `POST /conceive species=human` 验证 SSE 返回的 `birthplace.coordinates` 不再是固定 35.86/104.2
- [ ] 3.4 连续 conceive 5 个 human baby，观察坐标分布大致落在城市附近（而非戈壁/荒漠）

## 4. 测试（Phase D）

- [ ] 4.1 新建 `backend/tests/test_geo_sampler.py`：
  - [ ] `test_sample_in_china_polygon` — 100 次采样全在中国境内（shapely 二次校验）
  - [ ] `test_population_weighting_china` — CN 1000 次采样中 ≥ 80% 落在东部人口带 bbox `[lng 100-122, lat 20-42]`
  - [ ] `test_gobi_low_hit` — CN 1000 次采样中 < 5% 落在戈壁核心 bbox `[lng 85-95, lat 40-45]`
  - [ ] `test_us_metro_concentration` — US 1000 次采样 ≥ 25% 落在 NY/LA/CHI 任一 bbox
  - [ ] `test_city_jitter_spread` — 固定 seed 下同一 city 抽 100 次坐标去重 = 100
  - [ ] `test_sample_no_duplicates_same_country` — CN 100 次去重 = 100
  - [ ] `test_japan_no_ocean` — JP 100 次采样 0 个落海
  - [ ] `test_unknown_iso_returns_none` — `sample_point_by_population('ZZ')` 返回 None
  - [ ] `test_small_country_fallback_to_l2` — mock 城市表空，验证走 L2 均匀采样仍合法
  - [ ] `test_seed_reproducibility` — seed(42) 两次字节相等
  - [ ] `test_chile_long_country` — CL 50 次合法且 < 5s
  - [ ] `test_shapely_unavailable_returns_none` — monkeypatch `_SHAPELY_AVAILABLE=False` 返回 None
  - [ ] `test_cities_csv_missing_fallback` — cities.csv 缺失时，自动走 L2 polygon 均匀采样
- [ ] 4.2 扩展或新建 `backend/tests/test_birthplace.py`：
  - [ ] `test_diverse_coordinates_same_country` — `resolve_birthplace('human', 'CN') × 50` 去重 = 50
  - [ ] `test_fallback_when_sampler_returns_none` — monkeypatch sampler，验证回退到 country.coordinates
  - [ ] `test_birthplace_schema_unchanged` — 顶层键完全匹配
- [ ] 4.3 `pytest backend/tests/` 全绿

## 5. 文档同步（Phase E · 强制）

- [ ] 5.1 `backend/womb/CLAUDE.md`：
  - 「地理维度」段加：`geo_sampler.py: GeoJSON+城市人口的分层采样器（城市加权+高斯抖动 → polygon 均匀 → regions.yaml 中心点兜底）`
  - 「数据」段 `data/` 补 `countries.geojson`、`cities.csv`、`iso_alpha2_to_numeric.json`、`CITIES_LICENSE.txt`
- [ ] 5.2 `backend/womb/geo_sampler.py` 头部 L3 注释（已在 2.1 完成）
- [ ] 5.3 `backend/womb/birthplace.py` 头部 `[INPUT]` 同步（已在 3.2 完成）
- [ ] 5.4 根 `README.md` GeoNames 归属（已在 1.5 完成）
- [ ] 5.5 检查根 `CLAUDE.md` / `backend/CLAUDE.md` 是否需要变更（预计不需要，确认即可）

## 6. 四 Gate 验证（强制产物 · 写进 commit message）

- [ ] 6.1 **Gate 1**：`pytest backend/tests/test_geo_sampler.py backend/tests/test_birthplace.py` 全绿
- [ ] 6.2 **Gate 2**：`sample_point_by_population('CN')` 返回 dict schema 与 `regions.yaml.coordinates` 一致（`{"lat": float, "lng": float}`）
- [ ] 6.3 **Gate 3**（分布形状）：
  - 对 CN / US / JP 各跑 1000 次采样，输出如下数据写进 commit message：
    - `CN: 去重数/1000, 东部人口带命中率, 戈壁核心命中率, lng 均值, lat 均值`
    - `US: 去重数, NY+LA+CHI 命中率, lng 均值`
    - `JP: 去重数, 日本海命中率（应 = 0%）`
  - 人口带 ≥ 80% / 戈壁 < 5% / metro ≥ 25% / 海面 = 0% 全部通过才算 Gate 3 过
- [ ] 6.4 **Gate 4**（反向测试 / 用户视角）：
  - "CN 1000 次中 `lng < 100`（人口稀疏西部）的占比 < 20%" — pass
  - "CN 1000 次中 `lat > 50`（黑龙江以北）的占比 < 10%" — pass
  - "同胎三胞胎三个 coordinates 两两不等" — pass
  - "删除 `countries.geojson` 后 conceive 不 raise，coordinates 退化为 35.86/104.2" — pass
  - "删除 `cities.csv` 后 conceive 不 raise，coordinates 分布退化为 polygon 均匀（仍比国家中心进步）" — pass

## 7. 设计模式三问回答（强制产物 · 写进 commit message）

- **主角**：`Baby.birthplace.coordinates`，每个 baby 独立的地理标识
- **核心不变量**：同国 N 个 baby → N 个不同坐标 ∧ 每个坐标严格落在该国境多边形内 ∧ 整体分布匹配真实人口密度
- **spec 元字段使用情况**：
  - 用了：
    - GeoJSON `feature.id`（ISO 数字码）作为对齐键
    - GeoJSON `feature.bbox` 作为 L2 降级采样空间
    - GeoJSON `feature.geometry` (MultiPolygon) 作为合法性判定
    - GeoNames `iso2` 作为分组键
    - GeoNames `lat`/`lng` 作为抖动中心
    - GeoNames `population` 同时作为抽城市权重和抖动 σ 的 sqrt 输入
  - 忽略：
    - GeoJSON `feature.properties.name`（避免英文名分歧，用 iso2 替代）
    - GeoNames `city_ascii`/`admin_name`/`capital`/`iso3`/`id`（采样不需要）
    - `regions.yaml.population_weight`（那是抽国家用的，不参与坐标采样）

## 8. 提交与归档

- [ ] 8.1 `commit-as-prompt`：提交所有改动，commit message 含三问 + 四 Gate 输出
- [ ] 8.2 OpenSpec apply 完成后 `openspec archive add-birthplace-geo-sampling`
- [ ] 8.3 同步更新 memory：在 `MEMORY.md` 加一行指向 `project_birthplace_geo.md`，记录"2026-04-23 起 birthplace 走 GeoJSON+GeoNames 分层采样，降级链 polygon 均匀 → regions.yaml 中心；城市权重 + sqrt(pop) 高斯抖动 σ ∈ [0.01°, 0.3°]"
