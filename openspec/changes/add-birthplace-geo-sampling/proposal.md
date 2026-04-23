# 变更提案：出生地坐标按人口密度 + 国境多边形随机采样

## 动机

当前 `backend/womb/birthplace.py` 在 `_build_birthplace_dict` 中直接把 `regions.yaml` 里每国的单点 `coordinates`（国家几何/人口中心）原样塞进 birthplace dict。当多个 baby 被分配到同一个国家时，他们拿到的 `coordinates` 字节完全一致——例如所有「中国宝宝」全部坐标都是 `{lat: 35.86, lng: 104.2}`（甘肃中部）。

这违反了"出生地"的语义本意：

1. **拓扑误导**：未来若图谱可视化要把 baby 节点按地理位置布点，所有同国宝宝会重叠成一个像素点。
2. **统计偏差**：基于坐标做"邻近 baby"分析时，同国必然 100% 邻近，分析结果失真。
3. **叙事单调**：LLM 生成出生场景时拿不到差异化的地理信号（沿海/内陆/高原/平原）。
4. **不符合"实体稳定 + 个体独立"原则**：每个 baby 是独立 continuant，关键标识属性（出生地坐标）必须个体独立。
5. **分布失真**：若只在国境 polygon 内做均匀采样，戈壁滩婴儿概率会和北京一样高，与真实人口分布完全脱钩；同样对叙事/统计毫无价值。

用户已下载 Natural Earth 的 GeoJSON 国境多边形（`countries.geojson`，3.8MB，241 国）。本提案在其基础上叠加 **GeoNames World Cities Basic** 城市人口数据集（免费 CC BY 4.0，~44k 城市，~5MB），做**分层加权采样**：按人口加权抽一个城市 → 在城市附近做小高斯抖动 → 用国境 polygon 做合法性兜底。无城市数据的小国降级为 README 推荐的 `shapely` bbox 均匀拒绝采样。

## 目标

- **G1 同国不同坐标**：同一次会话内多个 baby 即便分配到同一国家，`birthplace.coordinates` 不得字节相等。
- **G2 国境严格约束**：产出的坐标必须落在该国 GeoJSON 多边形内部，不得落海或落到邻国。
- **G3 分布匹配人口**：大国内部的采样分布 MUST 大致反映真实人口密度——中国东部带概率远高于西部戈壁、美国 NY/LA/CHI 概率远高于蒙大拿。
- **G4 向后兼容**：`Baby.birthplace` 数据结构不变（仍为 `{lat, lng}` 形式），只是数值由"国家中心"变为"城市附近的随机点"；下游所有消费者（前端、archive、LLM prompt）零改动。
- **G5 回退安全**：城市表缺失 / GeoJSON 加载失败 / shapely 未安装 / 采样 N 次失败等任一异常，MUST 按降级链回退（城市均匀→境内均匀→`regions.yaml` 国家中心点），**不得 raise 中断 conceive 流程**。
- **G6 国家匹配稳健**：用 ISO 3166-1 alpha-2 作为主键对齐 `regions.yaml.code` / GeoNames `iso2` / GeoJSON（通过 `iso_alpha2_to_numeric.json` 中转）。
- **G7 可缓存高性能**：GeoJSON、polygon 对象、城市分组索引在进程内缓存（按文件 mtime 失效），首次加载后单次采样在 < 2ms 量级。
- **G8 测试可复现**：通过 `random.seed` 固定种子时，采样结果确定可重现。

## 范围

### 包含

- **依赖**：
  - `backend/pyproject.toml` 新增 `shapely>=2.0`。
- **数据**：
  - `backend/womb/data/countries.geojson`（**新增**，从 `/Users/lifulin/Downloads/fileswww/countries.geojson` 拷贝，3.8MB）。
  - `backend/womb/data/cities.csv`（**新增**，GeoNames World Cities Basic v1.77+，~5MB，~44k 城市，字段 `city, lat, lng, country, iso2, iso3, population`）。
  - `backend/womb/data/iso_alpha2_to_numeric.json`（**新增**，~250 行静态表，alpha-2 ↔ ISO 3166-1 数字码双向映射）。
  - `backend/womb/data/CITIES_LICENSE.txt`（**新增**，GeoNames CC BY 4.0 归属声明）。
  - `frontend/README.md` 或 `README.md`（**修改**，加一行 "City data © GeoNames, CC BY 4.0"）。
  - `backend/womb/data/regions.yaml`（**不修改**），现有 `coordinates` 字段保留作为最后一级回退值。
- **后端**：
  - `backend/womb/geo_sampler.py`（**新增**，约 180 行）：GeoJSON + cities.csv + ISO 映射表加载（mtime 缓存）、polygon 预构建、alpha2→cities 分组、`sample_point_by_population` 主入口、`sample_point_in_country` fallback 入口、降级链。
  - `backend/womb/birthplace.py`（**最小修改**）：`_build_birthplace_dict` 调用 `geo_sampler.sample_point_by_population(country['code'])`，失败回退到 `country.get('coordinates', {})`。
- **测试**：
  - `backend/tests/test_geo_sampler.py`（**新增**）：采样落国境、同国去重、人口权重验证（大都市命中率）、反向（戈壁低命中）、未知 ISO 回退、随机种子可复现、狭长国家兜底、无城市数据国家降级。

### 不包含

- **人口栅格级精度（WorldPop / NASA SEDAC GPWv4）**：1km 网格级别的人口密度栅格能给出最精细的分布（包括城市建成区内部的人口梯度），但数据量 100MB-1GB+，本期不接入。当前的"城市点 + 高斯抖动"方案在视觉和叙事层面已足够，栅格级精度属于后续独立变更。
- **`regions.yaml.coordinates` 字段重构**：保留作为兜底，不重命名为 `fallback_coordinates`，避免上下文断层。
- **前端地图渲染**：本期只解决坐标多样性与分布真实性，前端是否在 `LifeGraph` 或新视图里按经纬度可视化，由后续独立变更推进。
- **海上/南极洲等边界争议地区**：直接采用 Natural Earth 的国境定义，不做政治校正。
- **`countries-lite.geojson` / `china.geojson` 接入**：后端 3.8MB 数据可接受，无需 lite；中国专用文件不接入，统一走 `countries.geojson`。
- **跨进程持久化采样结果**：每次调用都现采，不建立"baby_id → coordinates"持久缓存（archive 即缓存）。
- **城市别名/本地化名称匹配**：GeoNames 只用英文标准名，不处理"Beijing vs 北京 vs Peking"别名表。本期不做城市名搜索，采样阶段只用 iso2 分组。
- **历史人口（时间维度）**：GeoNames 的 `population` 是一个快照值，不区分 2000 / 2020 / 2050。本期不做历史人口建模。

## 成功标准

- ✅ 连续 conceive 100 个 species=human 的 baby，其 `birthplace.coordinates` 去重后 size = 100（不重复）。
- ✅ 强制 `birthplace_input="CN"` 连续 conceive 50 个 baby，所有坐标 MUST 经度 ∈ [73.61, 134.75] 且纬度 ∈ [18.22, 53.56]（中国 bbox），且经 shapely 验证 100% 落在中国多边形内部。
- ✅ 强制 `birthplace_input="CN"` 1000 次采样，**≥ 80% 落在东部人口带 bbox（经度 ∈ [100, 122], 纬度 ∈ [20, 42]）**；**< 5% 落在戈壁核心 bbox（经度 ∈ [85, 95], 纬度 ∈ [40, 45]）**——人口权重生效的硬指标。
- ✅ 强制 `birthplace_input="US"` 1000 次采样，≥ 25% 落在 NY/LA/CHI 三大都市圈任一 bbox 内。
- ✅ 强制 `birthplace_input="JP"` 50 次采样，0 个点落入日本海 / 太平洋。
- ✅ 同一个城市（如 Shanghai）抖动采样 100 次，坐标去重 = 100（高斯抖动保证个体独立）。
- ✅ 强制 `birthplace_input="ZZ"`（不存在 ISO）conceive 不 raise，落到 `roll_birthplace` 的随机国家流程，且坐标仍合法。
- ✅ 梵蒂冈（VA，无城市数据或仅 1 个）采样不 raise，走降级链仍返回合法点（若 polygon 可用则 polygon 均匀，否则 `regions.yaml` 中心）。
- ✅ 删除 `countries.geojson` 文件后启动服务，conceive 不 raise，所有 baby 回退到 `regions.yaml` 国家中心点（行为退化为变更前状态），并在 log 中 warn 一次。
- ✅ 删除 `cities.csv` 文件后启动服务，conceive 不 raise，降级为 polygon 均匀采样（仍比"国家中心"进步），log warn 一次。
- ✅ 固定 `random.seed(42)`，连续两次跑同一脚本，所有 baby 的 `birthplace.coordinates` 字节相等（确定性）。
- ✅ pytest 通过；`backend/womb/CLAUDE.md` 与 `backend/CLAUDE.md`（如需）同步更新；`birthplace.py` / `geo_sampler.py` 头部 L3 注释完整。
- ✅ archive 中 2026-04-22 之前生成的老 `birth.json` 仍能被 `registry` 正常读取（`coordinates` schema 未变）。

## 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| `shapely` 在某些 CI/部署环境（如 musl libc Alpine）安装失败 | 中 | 在 `geo_sampler.py` 顶部 try-import shapely，import 失败时整个采样链路降级到"返回 None → 上游回退到中心点"；记录一次性 warn log。部署环境优先用 official slim Debian 镜像（已有 wheel）。 |
| GeoJSON `feature.id`（数字码）与 `regions.yaml.code` / GeoNames `iso2`（alpha-2）对不齐 | 中 | 维护静态 `iso_alpha2_to_numeric.json`（250 行，ISO 标准稳定不变），一次生成永久可用；加载时双向构建 alpha2 ↔ numeric 映射。映射缺失的国家在加载时 log warn 一次。 |
| GeoNames 城市坐标偶含脏数据（极少量城市经纬度在国境外） | 中 | 加载 `cities.csv` 时，用 `polygon.contains(city_point)` 过滤掉不在对应 iso2 国境内的城市；被过滤条目 log warn（通常 < 0.5%）。 |
| 大都市抖动可能落到海里（如上海、东京沿岸） | 中 | 抖动后用 `polygon.contains` 校验，不通过则在同一 city 再抖动最多 10 次；10 次均失败则返回 city 中心点（已保证在境内）。 |
| 小国 / 微国（梵蒂冈、摩纳哥、图瓦卢）城市表极小或空 | 中 | 降级链：城市表为空 → 退化到"polygon 内均匀拒绝采样"；polygon 也不可用 → 退化到 `regions.yaml` 国家中心。每级降级 log warn 一次。 |
| 拒绝采样在狭长国家（智利、挪威、印尼）耗时偏高 | 低 | 首选路径是城市加权（1ms 量级），与国家形状无关；仅降级到 polygon 均匀采样时才受影响，此时 `max_tries=1000` 兜底。 |
| GeoJSON + cities.csv 共 ~9MB 入库导致 git 仓库膨胀 | 低 | 单次提交 9MB 在 git 历史中可接受；如未来仓库整体大小敏感，可改用 git-lfs 或在 install 阶段动态下载（不在本期）。 |
| Polygon 预构建内存占用过高 | 低 | 241 国 MultiPolygon 在 shapely 2.x 下约 30-50MB；加上 44k 城市索引 ~5MB；总共 35-55MB 进程内存，相对 FastAPI 基线（~150MB）可接受。 |
| 同进程内 `random` 共享状态导致测试不确定 | 低 | `geo_sampler` 内部使用全局 `random.choices` / `random.gauss`，测试用例显式 `random.seed(42)` 即可复现。 |
| 前端 / 下游消费者期望 `coordinates` 是国家中心 | 低 | 全量 grep `birthplace.coordinates` / `birthplace["coordinates"]` 的使用点，确认仅用于"显示一对经纬度"目的，无下游做聚合查询。如发现，需在变更落地时同步重构。 |
| 政治敏感边界（南海九段线、克什米尔、克里米亚） | 低 | Natural Earth 数据为公共领域且不含九段线，README 已声明。本期接受此边界定义，不做政治校正。 |
| GeoNames 许可需归属 | 低 | CC BY 4.0 仅要求标注来源，在 `README.md` 或 `About` 页加一行即可。`backend/womb/data/CITIES_LICENSE.txt` 同步保留原 license 文本。 |
| GeoNames 免费版 `population` 字段对小城市可能缺失 | 低 | 加载时缺失 `population` 的城市按 `population = 1000`（下限默认值）处理，确保它们仍有机会被抽中但权重很低。 |

## 技术路径概览

```
conceive(species="human", birthplace_input=None)
  └── resolve_birthplace
       └── roll_birthplace（人口加权抽国）  → country dict (alpha-2)
       └── _build_birthplace_dict
            ├── coordinates: geo_sampler.sample_point_by_population(country['code'])
            │     ├── [L1 首选] 城市加权 + 高斯抖动
            │     │     ├── 查 _POLY_INDEX[alpha2]['cities']
            │     │     ├── random.choices(cities, weights=[c.pop for c in cities])
            │     │     ├── σ = clamp(sqrt(city.pop) * 1e-4, 0.01°, 0.3°)
            │     │     ├── 抖动 (lat, lng) 最多 10 次 + polygon.contains 校验
            │     │     └── 10 次失败 → 返回 city 中心
            │     ├── [L2 降级] polygon 内 bbox 均匀拒绝采样（原 README 方案）
            │     │     └── 城市表空 / 抖动链路完全失败时进入
            │     └── [L3 降级] 返回 None → 上游回退 regions.yaml 中心
            │           └── shapely 不可用 / geojson 缺失 / alpha2 未映射时进入
            └── coordinates: None 时 fallback country.coordinates  ← 兼容变更前
```

`geo_sampler.py` 内部状态：

```python
_GEOJSON_PATH / _CITIES_PATH / _ISO_MAP_PATH
_LAST_MTIME: tuple[float, float, float] | None    # 三文件 mtime 联合失效
_POLY_INDEX: dict[str, dict] | None               # {alpha2: {polygon, bbox, cities: list[dict]}}
_SHAPELY_AVAILABLE: bool
```

每个 `cities[i]` 是 `{"city": str, "lat": float, "lng": float, "population": float}`。

## 与项目铁律的对齐

- **设计模式三问**：
  - 主角：`Baby.birthplace.coordinates`，每个 baby 独立的地理标识
  - 核心不变量：「同国 N 个 baby → N 个不同坐标 ∧ 每个坐标都在该国境内 ∧ 整体分布匹配真实人口密度」
  - spec 元字段：
    - 使用：GeoJSON `feature.id`（ISO 数字码）与 GeoNames `iso2` 经映射表对齐，`feature.bbox` 作为降级均匀采样空间，`MultiPolygon.contains` 作为合法性判定，GeoNames `population` 作为加权抽城市的权重
    - 忽略：GeoJSON `feature.properties.name`、GeoNames `city_ascii` / `admin_name` / `capital` / `id` 等元数据（采样不需要）
- **向后兼容铁律**：`Baby.birthplace` schema 不变；archive 老数据仍可读；所有外部数据文件缺失时分层降级，最终兜底回到变更前行为。
- **三问过滤**：
  1. 真实需求：用户两轮对话主动提出"同国坐标一样"+"希望加入人口分布"，非臆想。
  2. 更简单方案：考虑过"纯 polygon 均匀采样"，被用户否定（戈壁等同北京分布失真）；考虑过"WorldPop 栅格"，数据量过大且收益边际递减；当前城市加权 + 抖动方案是简洁度/真实度的帕累托最优。
  3. 破坏什么：仅 `coordinates` 数值变化，schema 与下游均不破坏。
- **好品味**：采样链路用降级链而非 if/else 特殊情况——L1 城市加权、L2 polygon 均匀、L3 国家中心，每一级都是独立函数，失败自然流到下一级，消除了"该国有城市吗？"、"shapely 装了吗？"这类分支判断。
- **文档分形**：本变更落地时同步更新 `backend/womb/CLAUDE.md` 成员清单（新增 `geo_sampler.py` + 三份数据文件），`geo_sampler.py` 头部带 L3 INPUT/OUTPUT/POS/PROTOCOL 注释。
