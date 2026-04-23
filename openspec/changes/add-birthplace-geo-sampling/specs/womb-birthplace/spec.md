# Delta for Womb Birthplace

## ADDED Requirements

### Requirement: 出生地坐标的个体唯一性

`Baby.birthplace.coordinates` SHALL 表示该 baby 个体的出生坐标，而非国家几何中心。同一国家分配的多个 baby MUST 获得各自不同的坐标值。

#### Scenario: 同国多 baby 坐标差异
- GIVEN 调用 `resolve_birthplace(species="human", birthplace_input="CN")` 50 次
- WHEN 收集所有 50 次返回的 `coordinates`
- THEN 50 个坐标 dict 去重后 size MUST 等于 50
- AND 每个 `coordinates` MUST 满足 schema `{"lat": float, "lng": float}`

#### Scenario: 同一会话内多胎
- GIVEN 一次 conceive 触发 `roll_multiples` 命中三胞胎
- WHEN 三个 baby 的 birthplace 由同一个 country 派生
- THEN 三个 baby 的 `birthplace.coordinates` MUST 两两字节不相等

#### Scenario: 同一城市抖动
- GIVEN 固定 `random.seed`，直接调用 `geo_sampler.sample_point_by_population("CN")` 100 次
- AND 抽样过程恰好每次都抽中同一个城市（通过 mock random.choices 固定）
- WHEN 收集 100 次返回的 `coordinates`
- THEN 去重后 size MUST 等于 100（高斯抖动保证个体独立）

### Requirement: 坐标分布匹配人口密度

`geo_sampler.sample_point_by_population(alpha2)` 产出的坐标分布 MUST 大致匹配真实人口密度——人口密集区概率高，人口稀疏区概率低。

#### Scenario: 中国东部人口带命中率
- GIVEN 调用 `sample_point_by_population("CN")` 1000 次
- WHEN 统计落在东部人口带 bbox `lng ∈ [100, 122] ∧ lat ∈ [20, 42]` 的次数
- THEN 次数 MUST ≥ 800（即 ≥ 80%）

#### Scenario: 中国戈壁低命中率
- GIVEN 调用 `sample_point_by_population("CN")` 1000 次
- WHEN 统计落在戈壁核心 bbox `lng ∈ [85, 95] ∧ lat ∈ [40, 45]` 的次数
- THEN 次数 MUST < 50（即 < 5%）

#### Scenario: 美国大都市聚集
- GIVEN 调用 `sample_point_by_population("US")` 1000 次
- WHEN 统计落在 NY bbox、LA bbox、CHI bbox 任一内的次数
- THEN 次数 MUST ≥ 250（即 ≥ 25%）

### Requirement: 坐标落在国境多边形内

非兜底路径（L1 城市抖动、L2 polygon 均匀）产出的 `coordinates` MUST 严格落在该国 `countries.geojson` 多边形 (`MultiPolygon`) 内部。

#### Scenario: 中国采样不出境
- GIVEN `sample_point_by_population("CN")` 调用 100 次（非 None 返回）
- WHEN 用 shapely 对每个返回点做 `china_polygon.contains(Point(lng, lat))` 校验
- THEN 100 / 100 MUST 返回 True
- AND 0 个点的纬度 MUST > 53.56（中国 bbox 北界）
- AND 0 个点的经度 MUST < 73.61（中国 bbox 西界）

#### Scenario: 日本采样不入海
- GIVEN `sample_point_by_population("JP")` 调用 50 次（非 None 返回）
- WHEN 用 shapely 校验
- THEN 50 / 50 MUST 落在日本 `MultiPolygon` 内部（自动包含本州、北海道、九州、四国、冲绳等所有岛屿）
- AND 0 个点 MUST 落在日本海 / 太平洋的 ocean tile

#### Scenario: 大都市抖动越界降级到 city 中心
- GIVEN 某个海滨大都市（如 Shanghai）的 `σ = 0.3°` 抖动 10 次均落入东海
- WHEN `sample_point_by_population` 的 L1 路径处理此边界
- THEN MUST 返回该城市的中心点 `(lat, lng)`（城市坐标自身已在境内）
- AND 返回值 MUST 仍满足 `polygon.contains`

### Requirement: 分层降级链

采样链路 MUST 按"城市加权抖动 → polygon 均匀 → `regions.yaml` 中心点"的三级降级顺序执行，任一级失败自动向下级跌落，整条链路 MUST NOT raise 中断 conceive 流程。

#### Scenario: 无城市数据的国家降级到 L2
- GIVEN 某国在 `cities.csv` 中没有任何 iso2 匹配（如数据未覆盖的微国）
- WHEN 调用 `sample_point_by_population(alpha2)`
- THEN MUST 检测到 `_POLY_INDEX[alpha2]['cities']` 为空
- AND MUST 内部调用 `sample_point_in_country(alpha2)`（L2 polygon 均匀拒绝采样）
- AND 返回的坐标 MUST 仍落在该国 polygon 内

#### Scenario: cities.csv 文件缺失
- GIVEN `backend/womb/data/cities.csv` 被删除
- WHEN 服务启动并调用 `sample_point_by_population("CN")`
- THEN 函数 MUST 不 raise
- AND 所有 `_POLY_INDEX[*]['cities']` MUST 为空列表
- AND 每次调用 MUST 自动走 L2 polygon 均匀采样
- AND log MUST warn 一次（不每次调用都 warn）

#### Scenario: shapely 未安装
- GIVEN 运行环境中 `shapely` import 失败
- WHEN `geo_sampler` 模块加载
- THEN 模块 MUST 设置内部 `_SHAPELY_AVAILABLE = False`
- AND `sample_point_by_population(any)` MUST 返回 None
- AND `_build_birthplace_dict` MUST 把 `regions.yaml` 中的 `coordinates` 字段填入返回 dict
- AND 启动时 MUST log warn 一次

#### Scenario: countries.geojson 文件缺失
- GIVEN `backend/womb/data/countries.geojson` 不存在
- WHEN 调用 `geo_sampler.load_geo_index()`
- THEN 函数 MUST 返回 None
- AND `sample_point_by_population(any)` MUST 返回 None
- AND `_build_birthplace_dict` MUST 走 fallback 分支到 `regions.yaml` 中心
- AND log MUST warn 一次（首次加载时）

#### Scenario: 国家 alpha-2 未在 ISO 映射表 / GeoJSON 中
- GIVEN `birthplace_input="ZZ"`（无效 ISO 代码）经 `resolve_birthplace` 落入随机国家分支
- AND 假设 `roll_birthplace` 抽中的国家 alpha-2 不在 `_POLY_INDEX`
- WHEN `_build_birthplace_dict` 调用 `geo_sampler.sample_point_by_population(code)`
- THEN 返回 None
- AND 最终 birthplace dict 的 `coordinates` MUST 等于 `regions.yaml` 中该国的 `coordinates`

#### Scenario: L2 拒绝采样 max_tries 全部失败
- GIVEN 一个虚构的零面积"国家"（极端边界场景）
- WHEN `sample_point_in_country` 1000 次 bbox 采样均未落在 polygon 内
- THEN MUST 返回 None（不 raise）
- AND log MUST warn 一次（带国家代码）

### Requirement: 脏数据过滤

加载 `cities.csv` 时，经纬度落在对应 `iso2` 国境外的城市 MUST 被过滤掉，不得进入 `_POLY_INDEX`，以避免 L1 抖动时把"中国的一个城市"投影到越南境内。

#### Scenario: 城市经纬度与 iso2 不匹配
- GIVEN `cities.csv` 中有一条记录 `city=Foo, iso2=CN, lat=10.5, lng=106.8`（实际在越南）
- WHEN `load_geo_index()` 加载该行
- THEN 调用 `_POLY_INDEX["CN"]['polygon'].contains(Point(106.8, 10.5))` 返回 False
- AND 该城市 MUST 被 drop
- AND `_POLY_INDEX["CN"]['cities']` MUST NOT 包含这条记录
- AND 被 drop 的 iso2 总计数 MUST 被记录，超过 0.5% 阈值时 warn_once

### Requirement: 缓存与失效

`countries.geojson`、`cities.csv`、`iso_alpha2_to_numeric.json` 三个数据文件 SHALL 在进程内联合按 mtime 缓存。任一文件变更时缓存 MUST 自动失效重建。

#### Scenario: 缓存命中
- GIVEN `load_geo_index()` 已被调用过一次，三个文件均未修改
- WHEN 再次调用 `load_geo_index()`
- THEN MUST 直接返回缓存的索引（不重新读盘 / 不重新构建 polygon）

#### Scenario: 缓存失效
- GIVEN `load_geo_index()` 已被调用过一次
- WHEN 三个文件中任一 mtime 变化
- AND 再次调用 `load_geo_index()`
- THEN MUST 重新读取所有三个文件
- AND `_POLY_INDEX` MUST 重建

### Requirement: 确定性可复现

固定 `random.seed` 后，连续两次调用 `sample_point_by_population(same_alpha2)` MUST 返回字节相等的坐标，便于回归测试。

#### Scenario: 种子复现
- GIVEN `random.seed(42)`
- WHEN 调用 `sample_point_by_population("CN")` 一次得到 result1
- AND 重新 `random.seed(42)`
- AND 再次调用 `sample_point_by_population("CN")` 得到 result2
- THEN `result1["lat"] == result2["lat"]` AND `result1["lng"] == result2["lng"]`

### Requirement: 向后兼容

`Baby.birthplace` 数据 schema MUST 与变更前完全一致，archive 中的老 `birth.json` 文件 MUST 仍可被 `registry` 正常读取。

#### Scenario: schema 不变
- WHEN 对比变更前后的 `_build_birthplace_dict` 返回值
- THEN 顶层键集合 MUST 完全一致：`{name, code, coordinates, region, race_distribution, environment_modifiers}`
- AND `coordinates` 子键 MUST 仍为 `{lat, lng}`

#### Scenario: 老 archive 兼容
- GIVEN 一个 2026-04-22 之前生成的 `archive/{baby_id}/birth.json`，其 `birthplace.coordinates` 为国家中心点
- WHEN `registry.load_baby` 读取该文件
- THEN MUST 正常返回 Baby 对象
- AND 不得抛出 KeyError / ValidationError
