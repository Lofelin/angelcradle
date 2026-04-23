# womb/
> L2 | 父级: /backend/CLAUDE.md

世界子宫：从物种蓝图孕育生命。7 阶段发育 + 环境量化 + 命运掷骰 + LLM 编排。

## 成员清单

__init__.py: 入口，导出 conceive()，编排遗传→表观遗传→环境→命运→发育全流程
baby.py: Baby/ConceptionResult 数据模型，ID 生成，性别/表型决定。**lang 字段（fix-lifeline-i18n）**：`Baby.lang: "zh" | "en"` 默认 `"en"`，conceive API 写入后由 registry 持久化到 archive/{id}/birth.json，admit 时拷贝到 BabyState.lang 供下游生成链路分支
environment.py: 母体环境生成 + 量化修正系数（budget/defect_risk/miscarriage_risk）
fate.py: 命运引擎——流产/多胎/死产/缺陷掷骰，基于 WHO/CDC 真实概率
stages.py: 7 阶段发育编排——prompt 构建 + 预算执法 + 确定性母体反馈 + 分层约束注入 + 跨阶段校验 + SSE 流
prompts.py: 7 阶段 prompt 模板（含跨阶段一致性约束和代码惩罚提示）
genetics.py: 向后兼容薄层，re-export stages.py 和 llm.py 的接口
llm.py: 向后兼容层，re-export 根级 llm.py 的 LLM 客户端接口

### 地理维度

birthplace.py: 出生地系统——地区数据加载/人口加权掷骰/环境修正提取（仅 human）。coordinates + city 由 geo_sampler 产出，regions.yaml 中心作为兜底
geo_sampler.py: 出生地坐标三级降级采样（add-birthplace-geo-sampling）——L1 `sample_city_and_point` 城市人口加权 + 高斯抖动 σ=clamp(sqrt(pop)·1e-4, 0.01°, 0.3°) + polygon.contains 校验（返回 {city, lat, lng}）；L2 `sample_point_in_country` polygon bbox 均匀拒绝采样（city=None）；L3 返回 None → 上游回退 regions.yaml 国家中心（city=None）。辅助函数 `nearest_city(alpha2, lat, lng)` 用于历史数据反查最近城市名

### 生物子系统

nutrients.py: 5 种营养素（folate/iodine/iron/dha/calcium）+ 阶段敏感性 + 风险聚合
teratogen.py: 6 种致畸毒素 × 7 阶段风险矩阵 + 风险聚合
dynamic_env.py: 阶段间动态环境变化（概率触发）+ 确定性母体反馈计算 + budget delta 应用
heredity.py: 简化孟德尔遗传——10 个性状的显隐性/不完全显性/共显性
epigenetics.py: 甲基化噪声模型——同基因个体产生可追溯差异（Barker 假说/叶酸甲基供体）
placenta.py: 胎盘效率曲线 + 并发症 + budget 乘数
immunity.py: 血型/Rh 不兼容 + TORCH 感染 + 免疫风险修正
hormones.py: 4 条激素通路（皮质醇/甲状腺T4/性激素/hCG）+ 环境→激素→发育因果链
vitals.py: 胎儿生命体征（心率/体重/身长/羊水/胎动/血压/血氧）+ 逐阶段可观测

### 数据

data/: 地区数据
  - regions.yaml: 国家/地区元数据 + race_distribution + 环境修正系数 + 国家中心 coordinates（fallback 用）
  - countries.geojson: Natural Earth 国境多边形（241 feature，3.8MB）——geo_sampler 合法性判定
  - cities.csv: GeoNames cities15000 裁剪后 5 列（city, lat, lng, iso2, population，33k 行 1.3MB）——geo_sampler L1 人口加权源
  - iso_alpha2_to_numeric.json: ISO 3166-1 alpha-2 ↔ 数字码静态映射（249 条）——geojson feature.id 对齐
  - CITIES_LICENSE.txt: GeoNames CC BY 4.0 归属声明
species/: 物种蓝图 YAML（human.yaml, dog.yaml, cat.yaml）

## 对外暴露

```python
from womb import conceive                    # 主入口
from womb.baby import Baby, ConceptionResult # 数据模型
from womb.genetics import express_stream     # 流式发育（向后兼容路径）
from womb.stages import express, express_stream, STAGE_NAMES, RESOURCE_BUDGET
from womb.environment import generate_environment, format_environment
from womb.fate import roll_congenital_defects, roll_miscarriage
from womb.heredity import ParentGenome, random_genome, crossover
from womb.epigenetics import generate_methylation_profile, apply_epigenetic_modification
from womb.hormones import compute_hormones, get_hormone_effects
from womb.vitals import compute_vitals, format_vitals_for_display
```

## 数据流

```
conceive()
  ├── heredity: random_genome → crossover → genotype_to_phenotype
  ├── epigenetics: generate_methylation_profile → apply_epigenetic_modification (同卵双胞胎在此分化)
  ├── environment: generate_environment (nutrients + teratogen + placenta + immunity)
  ├── fate: roll_miscarriage → roll_multiples → roll_congenital_defects (含营养素/致畸风险)
  └── stages: express/express_stream
       ├── 每阶段: roll_env_change → update_placenta → nutrient_effects → teratogen_risk
       ├── 每阶段: compute_hormones → get_hormone_effects (皮质醇/甲状腺/性激素/hCG)
       ├── 每阶段: compute_vitals (心率/体重/身长/羊水/胎动/血压/血氧)
       ├── build_stage_prompts (含遗传/表观遗传/营养/致畸/胎盘/免疫/激素注入)
       ├── _call_llm → _enforce_budget → validate_*
       ├── compute_maternal_response → 确定性母体反馈（替代 LLM 调用）
       └── apply_maternal_feedback(budget_delta) → 下一阶段
```

## SSE 流事件（前端可消费）

每个发育阶段的 `in_progress` 事件包含：
- `vitals`: 格式化的心率/体重/身长/羊水/胎动/血压/血氧/状态/告警
- `hormones`: 皮质醇/甲状腺T4/性激素/hCG 水平
- `hormone_effects`: budget 惩罚/神经修正/焦虑基线/认知上限
- `nutrient_effects`, `teratogen_risk`, `placenta_efficiency`, `immune_risks`

[PROTOCOL]: 变更时更新此文档，然后检查父级 CLAUDE.md
