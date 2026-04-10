# Plan: birthplace

## Tasks

- [ ] 1. 数据层：创建 regions.yaml
  - [ ] 1.1 创建 `womb/data/` 目录
  - [ ] 1.2 编写 `womb/data/regions.yaml`，包含 9 个区域默认值和 25 个代表性国家（含 population_weight, coordinates, race_distribution, environment_modifiers）
  - [ ] 1.3 应用数据修正：Brazil 种族分布、India/South Africa/Pakistan/Nigeria/DR Congo/Ethiopia 人口、US European 比例、Saudi Arabia South Asian 比例、South Korea stress、South Africa Indian/Asian 补充（见 design.md 1.2 数据修正记录）
  - [ ] 1.4 验证所有 race_distribution 的 race 名与 `human.yaml` 中 `birth_attributes.races` 列表一致
  - [ ] 1.5 验证所有 race_distribution 概率总和近似 1.0（容差 0.01）

- [ ] 2. 核心模块：创建 womb/birthplace.py
  - [ ] 2.1 实现 `load_regions()` -- 加载 regions.yaml 并缓存到模块级变量 `_REGIONS_CACHE`
  - [ ] 2.2 实现 `roll_birthplace(species)` -- 人口加权 `random.choices`，非 human 返回 None
  - [ ] 2.3 实现 `resolve_birthplace(species, birthplace_input)` -- 解析用户输入（ISO code/name，case-insensitive），无效输入 fallback 到 roll 并 log warning
  - [ ] 2.4 实现 `get_race_weights(birthplace)` -- 提取 race_distribution dict
  - [ ] 2.5 实现 `get_environment_bias(birthplace)` -- 提取 environment_modifiers dict
  - [ ] 2.6 添加 L3 文件头注释（INPUT/OUTPUT/POS/PROTOCOL）

- [ ] 3. 环境修正：修改 womb/environment.py
  - [ ] 3.1 `generate_environment()` 签名新增 `birthplace: dict | None = None` 参数
  - [ ] 3.2 实现 `_bias_weights(levels, favorable_bias)` 函数 -- 根据 baseline 值偏移权重分布
  - [ ] 3.3 在 `generate_environment()` 中，当 birthplace 存在且用户未显式传入对应参数时，使用 `_bias_weights` 调整 nutrition/stress/toxin 的权重分布
  - [ ] 3.4 在返回的 env dict 中附带 birthplace 简化信息（name/code/coordinates）
  - [ ] 3.5 更新 L3 文件头注释

- [ ] 4. 表型联动：修改 womb/baby.py
  - [ ] 4.1 `determine_phenotype()` 签名新增 `race_weights: dict | None = None` 参数
  - [ ] 4.2 实现加权 race 选择逻辑：有 race_weights 时用 `random.choices` 加权选择，无则退回 `random.choice` 均匀选择
  - [ ] 4.3 `Baby` dataclass 新增 `birthplace: dict = field(default_factory=dict)` 字段
  - [ ] 4.4 `Baby.to_dict()` 输出中添加 `birthplace` 字段
  - [ ] 4.5 `ConceptionResult` dataclass 新增 `miscarriage_stage: str = ""` 和 `miscarriage_cause: str = ""` 字段
  - [ ] 4.6 更新 L3 文件头注释

- [ ] 5. 逐阶段流产引擎：修改 womb/fate.py
  - [ ] 5.1 新增 `HUMAN_STAGE_MISCARRIAGE_RATES` 字典（6 个阶段的基础概率）
  - [ ] 5.2 新增 `STAGE_RISK_FACTORS` 字典（阶段 -> 主导风险因子类别映射）
  - [ ] 5.3 实现 `roll_stage_miscarriage(species, stage_name, env, defects, placenta, hormones, immune_risks, nutrient_effects, teratogen_risk)` 函数
  - [ ] 5.4 实现阶段特定风险修正逻辑：zygote(遗传)、early_organogenesis(遗传+叶酸)、late_organogenesis(胎盘+致畸)、early_neural(压力+免疫)、late_neural(胎盘+激素)、fetal_movement(累积)
  - [ ] 5.5 实现全局 healthcare 修正（healthcare_baseline 越高风险越低）
  - [ ] 5.6 `roll_miscarriage()` 添加 deprecation 注释，保留用于非 human 物种
  - [ ] 5.7 更新 L3 文件头注释

- [ ] 6. 发育循环集成：修改 womb/stages.py
  - [ ] 6.1 在 `express()` 的 7 阶段循环开头（i < 6 时）插入 `roll_stage_miscarriage()` 调用
  - [ ] 6.2 处理 Stage 1 初始状态：placenta/hormones/immune_risks/nutrient_effects 使用默认值
  - [ ] 6.3 在循环外初始化 prev 状态变量（hormones_prev, immune_risks_prev 等），每轮末尾更新
  - [ ] 6.4 流产时返回包含 miscarriage=True, miscarriage_stage, miscarriage_cause 的 dict + 截断的 gestation_log
  - [ ] 6.5 在 `express_stream()` 的同等位置插入 `roll_stage_miscarriage()` 调用
  - [ ] 6.6 流产时 yield miscarriage 事件（含 stage/cause/rate/gestation_day），然后 return 终止生成器
  - [ ] 6.7 `express()` 和 `express_stream()` 签名新增 `defects_full: list[dict]`（含 severity 信息，供流产判定使用，区别于现有的 `defects: list[str]`）
  - [ ] 6.8 更新 L3 文件头注释

- [ ] 7. 编排层：修改 womb/__init__.py
  - [ ] 7.1 `conceive()` 签名新增 `birthplace: str | None = None` 参数
  - [ ] 7.2 在步骤 1（Parent genomes）之前插入步骤 0：调用 `resolve_birthplace()` + `get_race_weights()`
  - [ ] 7.3 将 birthplace 信息写入 `fate_log["birthplace"]`（含 selected/method）
  - [ ] 7.4 `generate_environment()` 调用传入 `birthplace=bp`
  - [ ] 7.5 `determine_phenotype()` 调用传入 `race_weights=race_weights`
  - [ ] 7.6 `Baby()` 构造传入 `birthplace=bp_summary`（name/code/coordinates）
  - [ ] 7.7 删除 human 物种的前置 `roll_miscarriage()` 调用；非 human 物种暂保留
  - [ ] 7.8 将完整 defects list（含 severity dict）传入 `express()` / `express_stream()` 的新参数 `defects_full`
  - [ ] 7.9 处理 `express()` 返回的 miscarriage result：标记 offspring 流产并跳过 Baby 构造
  - [ ] 7.10 所有 offspring 均流产时，返回 `ConceptionResult(success=False, miscarriage=True, miscarriage_stage=..., miscarriage_cause=...)`
  - [ ] 7.11 更新 L3 文件头注释

- [ ] 8. API 层：修改 api/conceive.py
  - [ ] 8.1 `POST /conceive` 新增 `birthplace: Optional[str] = None` 参数，传入 `conceive()`
  - [ ] 8.2 `GET /conceive/stream` 新增 `birthplace: Optional[str] = None` query parameter
  - [ ] 8.3 stream `event_generator()` 中：调用 `resolve_birthplace()` + `get_race_weights()`，传入 environment 和 phenotype 生成
  - [ ] 8.4 stream environment 事件中附带 birthplace 信息
  - [ ] 8.5 stream 转发 miscarriage 事件为 SSE（含 stage/cause 信息）
  - [ ] 8.6 stream born 事件中 baby dict 包含 birthplace 字段

- [ ] 9. 文档更新
  - [ ] 9.1 更新 `womb/CLAUDE.md`：成员清单新增 birthplace.py 和 data/regions.yaml；数据流新增 birthplace 步骤 + 阶段流产路径；SSE 事件新增 miscarriage 事件说明
  - [ ] 9.2 birthplace.py 的 L3 头部注释（已在 2.6 完成）
  - [ ] 9.3 检查 environment.py / baby.py / __init__.py / stages.py / fate.py 的 L3 头部注释是否需要更新 INPUT/OUTPUT 描述

- [ ] 10. 验证与测试
  - [ ] 10.1 手动测试：`conceive("human")` 不传 birthplace -- 验证随机出生地 + 加权 race + 环境偏移正常
  - [ ] 10.2 手动测试：`conceive("human", birthplace="JP")` -- 验证日本出生地 + East Asian 高概率 + 高 healthcare 环境
  - [ ] 10.3 手动测试：`conceive("human", birthplace="INVALID")` -- 验证 fallback 到随机 + warning
  - [ ] 10.4 手动测试：`conceive("dog")` -- 验证 birthplace=None，行为不变；流产使用旧 roll_miscarriage()
  - [ ] 10.5 手动测试：SSE stream 带 birthplace 参数 -- 验证事件中包含 birthplace 信息
  - [ ] 10.6 流产概率验证：运行 1000 次 human 模拟（无 LLM，仅掷骰），统计各阶段流产率和总流产率，验证总率近似 15.3% (+-2%)
  - [ ] 10.7 手动测试：高风险环境（低 healthcare、高 toxin）-- 验证流产率显著高于基线
  - [ ] 10.8 手动测试：SSE stream 中途流产 -- 验证 miscarriage 事件包含 stage/cause 信息，stream 正常终止
  - [ ] 10.9 向后兼容验证：不传任何新参数调用所有 API -- 确认输出结构兼容
  - [ ] 10.10 多胎流产测试：验证多胎妊娠中部分 offspring 流产、部分存活的场景
