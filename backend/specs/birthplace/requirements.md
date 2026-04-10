# Requirements: Birthplace System

## 功能概述

为 Angel Cradle 的子宫模块引入「出生地」维度。每个生命在孕育时被分配一个出生国家，该国家的地理、医疗、环境条件影响母体环境参数生成，同时概率性地决定种族（race）表型。第一版仅支持 human 物种。

同时重构流产机制：从前置一刀切判定改为逐阶段累积风险模型，使流产发生在发育过程中而非发育开始前。

---

## 用户故事

### US-1: 随机出生地分配

**As a** 用户执行 conceive 操作时，
**I want** 系统基于真实世界人口分布自动掷骰一个出生国家，
**So that** 每个生命的诞生地点具有统计真实性。

**Acceptance Criteria (EARS):**

- **AC-1.1** When the user calls `conceive()` without specifying a birthplace, the system SHALL select a country from `regions.yaml` using population-weighted random sampling.
- **AC-1.2** When the system selects a birthplace, the result SHALL include the country name, ISO 3166-1 alpha-2 code, and coordinates (latitude, longitude).
- **AC-1.3** Where a species other than "human" is specified, the system SHALL skip birthplace assignment and return `birthplace = None`.

### US-2: 用户指定出生地

**As a** 用户，
**I want** 能够通过 API 参数指定出生国家（ISO code 或国家名），
**So that** 我可以模拟特定地域的生命孕育。

**Acceptance Criteria (EARS):**

- **AC-2.1** When the user provides a valid `birthplace` parameter (ISO alpha-2 code or country name), the system SHALL use the matching country from `regions.yaml` instead of random sampling.
- **AC-2.2** When the user provides an invalid `birthplace` value that does not match any entry in `regions.yaml`, the system SHALL fall back to random sampling and include a warning in the fate_log.

### US-3: 出生地影响母体环境

**As a** 系统，
**I want** 出生国家的环境基线修正 `generate_environment()` 的输出，
**So that** 不同国家的医疗水平、营养条件、毒素暴露差异能反映在孕育过程中。

**Acceptance Criteria (EARS):**

- **AC-3.1** When a birthplace is determined, the system SHALL apply the country's `environment_modifiers` (nutrition_baseline, toxin_baseline, healthcare_baseline, stress_baseline) to bias the environment generation weights.
- **AC-3.2** Where a country's `healthcare_baseline` is high (>= 0.7), the system SHALL shift nutrition and toxin distributions toward more favorable outcomes.
- **AC-3.3** Where a country's `healthcare_baseline` is low (< 0.3), the system SHALL shift nutrition and toxin distributions toward less favorable outcomes.
- **AC-3.4** While environment modifiers are applied, the system SHALL NOT override explicit user-provided environment parameters (nutrition, stress, toxin_exposure, maternal_age_factor). User overrides take precedence.

### US-4: 出生地概率性影响种族

**As a** 系统，
**I want** 出生国家的种族分布概率替代当前的均匀随机 race 选择，
**So that** 例如在日本出生的婴儿大概率为 East Asian，但仍有小概率为其他种族。

**Acceptance Criteria (EARS):**

- **AC-4.1** When a birthplace is determined and the species is "human", the system SHALL use the country's `race_distribution` as weights for race selection instead of uniform random choice.
- **AC-4.2** When the user explicitly specifies a phenotype/race override, the system SHALL use the override regardless of birthplace distribution.
- **AC-4.3** Where the birthplace has no `race_distribution` defined, the system SHALL fall back to uniform random selection from the species blueprint's races list.

### US-5: 出生地信息记录与输出

**As a** 用户，
**I want** Baby 输出中包含完整的出生地信息，
**So that** 前端可以展示出生地并在未来映射到地球仪/地图。

**Acceptance Criteria (EARS):**

- **AC-5.1** When a baby is successfully born, the Baby data model SHALL include a `birthplace` field containing `{name, code, coordinates: {lat, lng}}`.
- **AC-5.2** When the conceive stream emits events, the `environment` event SHALL include the resolved birthplace information.
- **AC-5.3** When the `fate_log` is generated, it SHALL include the birthplace selection result (selected country, method: random/specified).

### US-6: 地区数据独立存放

**As a** 开发者，
**I want** 地区数据存放在独立的 `womb/data/regions.yaml` 文件中，
**So that** 地区数据与物种蓝图解耦，可以独立维护和扩展。

**Acceptance Criteria (EARS):**

- **AC-6.1** The system SHALL load region data from `womb/data/regions.yaml`, separate from species blueprints.
- **AC-6.2** Where `regions.yaml` is missing or malformed, the system SHALL fall back to uniform random race selection and no environment modification, logging a warning.
- **AC-6.3** The `regions.yaml` file SHALL contain 20-30 representative countries covering all major world regions, with remaining countries covered by regional defaults.

### US-7: 逐阶段流产判定

**As a** 系统，
**I want** 流产判定从前置一刀切改为在每个发育阶段开头逐步评估，
**So that** 流产原因与发育阶段的主导风险因子关联，产生更真实的孕育叙事。

**Acceptance Criteria (EARS):**

- **AC-7.1** When a conception begins, the system SHALL NOT perform a single upfront miscarriage roll. Instead, at the start of each development stage (1-6), the system SHALL evaluate stage-specific miscarriage probability.
- **AC-7.2** When evaluating stage miscarriage probability, the system SHALL use that stage's dominant risk factors as modifiers:
  - Stage 1 (zygote): genetic defect count and severity
  - Stage 2 (early_organogenesis): genetic defects + nutrient levels (especially folate)
  - Stage 3 (late_organogenesis): placenta efficiency + teratogen exposure
  - Stage 4 (early_neural): environmental stress + immune risks
  - Stage 5 (late_neural): placenta + hormones + cumulative risk
  - Stage 6 (fetal_movement): cumulative risk from all prior factors
- **AC-7.3** Where miscarriage occurs at any stage, the system SHALL immediately terminate the development loop for that offspring and record `miscarriage=True` with `miscarriage_stage` identifying which stage triggered the loss.
- **AC-7.4** When calculating total miscarriage probability across all stages, the conditional product `1 - product(1 - P_stage_i)` for i in [1..6] SHALL approximate the species' `overall_rate` (human: ~15.3%) under neutral environment conditions.
- **AC-7.5** When the SSE stream encounters a miscarriage event, it SHALL emit a `miscarriage` event containing the stage name, stage number, cause category, and accumulated risk, then terminate the stream for that offspring.
- **AC-7.6** Where Stage 7 (birth) is reached, the system SHALL retain the existing `roll_stillbirth()` logic unchanged. Stage 7 does not participate in the stage-miscarriage model.
- **AC-7.7** When `ConceptionResult` reports a miscarriage, it SHALL include `miscarriage_stage` (stage name) and `miscarriage_cause` (dominant risk factor category) in addition to the existing `miscarriage=True` flag.

---

## 数据需求

### regions.yaml 结构要求

每个国家条目必须包含：
- `name`: 国家英文名
- `code`: ISO 3166-1 alpha-2 代码
- `coordinates`: `{lat, lng}` -- 人口中心或首都坐标
- `population_weight`: 相对人口权重（基于真实人口数据，归一化后用于加权抽样）
- `race_distribution`: 映射到 human.yaml 中 races 列表的概率分布（总和为 1.0）
- `environment_modifiers`: 影响环境生成的基线系数
  - `nutrition_baseline`: 0.0-1.0
  - `toxin_baseline`: 0.0-1.0
  - `healthcare_baseline`: 0.0-1.0
  - `stress_baseline`: 0.0-1.0

### 区域默认值

为未列出的国家提供按大区（如 East Asia, South Asia, Europe, Sub-Saharan Africa 等）分组的默认值。

### 阶段流产基础概率 (human)

| 阶段 | 基础概率 | 主导风险因子 |
|------|---------|-------------|
| Stage 1 (zygote) | 0.050 | 遗传缺陷数量/严重度 |
| Stage 2 (early_organogenesis) | 0.030 | 遗传 + 营养（叶酸） |
| Stage 3 (late_organogenesis) | 0.020 | 胎盘效率 + 致畸物 |
| Stage 4 (early_neural) | 0.015 | 环境压力 + 免疫 |
| Stage 5 (late_neural) | 0.010 | 胎盘 + 激素 |
| Stage 6 (fetal_movement) | 0.008 | 累积风险 |

验证：1 - (0.95)(0.97)(0.98)(0.985)(0.99)(0.992) = 1 - 0.8687 = 0.1313。与 overall_rate 0.153 有差距，环境修正因子的均值效应（约 1.17x）会将实际流产率提升到目标范围。

---

## 约束条件

- **C-1** 第一版仅支持 human 物种。非 human 物种 conceive 时跳过 birthplace 逻辑。
- **C-2** regions.yaml 不超过 500 行。选取 20-30 个代表性国家 + 区域默认值。
- **C-3** birthplace 逻辑不得增加 conceive() 可感知的延迟（纯内存操作，无 I/O 阻塞）。
- **C-4** 所有概率分布必须归一化（race_distribution 各项之和 = 1.0, population_weight 用于 weighted sampling 不要求严格归一化）。
- **C-5** 逐阶段流产判定不得显著增加 conceive() 的 LLM 调用次数。流产判定是纯数学掷骰，无 LLM 参与。
- **C-6** 阶段流产概率的条件积应在中性环境下近似物种的 overall_rate（human ~15.3%，允许 +-2% 偏差）。

---

## 向后兼容

- **BC-1** `conceive()` 不传 `birthplace` 参数时行为与当前完全一致（random race, random environment），不破坏现有调用方。
- **BC-2** `Baby.to_dict()` 输出新增 `birthplace` 字段，不删除或重命名任何现有字段。
- **BC-3** `generate_environment()` 新增可选 `birthplace` 参数，不传时行为不变。
- **BC-4** `determine_phenotype()` 新增可选 `race_weights` 参数，不传时退回 uniform random。
- **BC-5** SSE stream 事件结构向后兼容：新增字段，不修改现有字段语义。
- **BC-6** API endpoint 签名向后兼容：`birthplace` 为可选 query parameter。
- **BC-7** `ConceptionResult` 保留 `miscarriage` 布尔字段的语义不变。新增 `miscarriage_stage` 和 `miscarriage_cause` 为可选字段（仅流产时有值）。
- **BC-8** `roll_miscarriage()` 函数保留但标记为 deprecated，新代码使用 `roll_stage_miscarriage()`。非 human 物种暂时保持使用旧的 `roll_miscarriage()` 直到后续扩展。
