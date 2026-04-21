# Requirements: Womb Upgrade

## 概述

子宫模块从"静态环境 + 简单缺陷列表"升级为"动态环境 + 营养细分 + 致畸窗口 + 遗传模型 + 胎盘 + 免疫"的完整孕期模拟系统。8 项改进按优先级分三批交付（P0 / P2 / P3）。

---

## US-01: 动态环境 [P0]

**作为** 子宫模拟系统  
**我希望** 母体环境随发育阶段动态变化，概率触发变化事件  
**以便** 每次孕育产生真正不同的环境轨迹，而非一成不变的静态快照

### 验收标准

- **AC-01.1**: 当发育进入新阶段时，系统 SHALL 以可配置概率（默认 15%-25%/阶段）掷骰判定是否触发环境变化事件
- **AC-01.2**: 环境变化事件 SHALL 包含以下类型：压力升降（stress_increase / stress_decrease）、营养改善/恶化（nutrition_improve / nutrition_worsen）、毒素暴露开始/结束（toxin_onset / toxin_end）
- **AC-01.3**: 当环境变化事件触发时，系统 SHALL 更新 env 字典中对应字段的等级值（如 stress 从 mild 变为 moderate），并重新计算 modifiers
- **AC-01.4**: 每个阶段的 gestation_log 条目 SHALL 记录该阶段生效的环境快照和触发的变化事件（如有）
- **AC-01.5**: 当未触发任何变化事件时，系统 SHALL 继续使用上一阶段的环境状态，不做任何修改

---

## US-02: 母体反馈数值化 [P0]

**作为** 子宫模拟系统  
**我希望** 母体反馈 LLM 输出真正修改后续阶段的 budget_multiplier  
**以便** 母胎反馈环不只是叙事装饰，而是真正影响资源分配的机制

### 验收标准

- **AC-02.1**: 当 LLM 返回母体反馈中的 `updated_environment_modifier` 包含 "better" / "improved" 关键词时，系统 SHALL 将 budget_multiplier 上调 0.01~0.03（随机）
- **AC-02.2**: 当 LLM 返回母体反馈中的 `updated_environment_modifier` 包含 "worse" / "deteriorated" / "declined" 关键词时，系统 SHALL 将 budget_multiplier 下调 0.01~0.05（随机）
- **AC-02.3**: budget_multiplier 调整后 SHALL 被 clamp 在 [0.50, 1.20] 范围内，防止极端漂移
- **AC-02.4**: 当 LLM 返回 "neutral" 或无法解析时，系统 SHALL 不修改 budget_multiplier
- **AC-02.5**: 每次调整 SHALL 记录在 gestation_log 中，包含调整方向、幅度和调整后的值

---

## US-03: 营养细分 [P0]

**作为** 子宫模拟系统  
**我希望** 将 nutrition 拆分为 5 个具体营养素，各影响不同阶段的不同系统  
**以便** 营养缺乏的后果是精确的（叶酸缺乏 -> 神经管缺陷），而非笼统的

### 验收标准（方案 A：保留综合指标）

- **AC-03.1**: env 字典 SHALL 新增 `nutrients` 子字典，包含 5 个营养素：folate / iodine / iron / dha / calcium，每个值为 0.0~1.0 的连续数值
- **AC-03.2**: 原 `nutrition` 字段 SHALL 保留，其值从 5 个营养素加权计算得出：`nutrition_score = 0.25*folate + 0.20*iodine + 0.20*iron + 0.20*dha + 0.15*calcium`，然后映射到 excellent/adequate/moderate_deficiency/severe_deficiency 四档
- **AC-03.3**: 当旧代码读取 `env["nutrition"]` 时，SHALL 返回与升级前相同格式的字符串值（向后兼容）
- **AC-03.4**: 每种营养素 SHALL 有阶段敏感性配置，定义其在哪些阶段对哪些系统有额外影响：
  - folate: zygote + early_organogenesis 阶段，影响神经管发育，缺乏时 neural_tube_defect 风险 x3.0
  - iodine: early_neural + late_neural 阶段，影响甲状腺/神经发育
  - iron: late_organogenesis 起，影响造血系统
  - dha: late_neural + fetal_movement 阶段，影响脑发育
  - calcium: late_organogenesis + fetal_movement 阶段，影响骨骼发育
- **AC-03.5**: 营养素值 SHALL 可通过 API 参数覆盖，未指定时随机生成（正态分布，均值 0.65，标准差 0.15，clamp 到 [0.1, 1.0]）
- **AC-03.6**: LLM prompt 中 SHALL 注入当前阶段的营养素状态和敏感性说明

---

## US-04: 致畸时间窗口 [P0]

**作为** 子宫模拟系统  
**我希望** 不同毒素在不同阶段有不同的致畸风险倍数  
**以便** 致畸效应符合真实胚胎学（器官形成期最敏感，晚期暴露影响较小）

### 验收标准

- **AC-04.1**: 系统 SHALL 定义毒素类型枚举：alcohol / tobacco / heavy_metals / medication / radiation / infection
- **AC-04.2**: 每种毒素 SHALL 有阶段-风险倍数矩阵，定义其在每个发育阶段的致畸风险倍数。示例：alcohol 在 early_organogenesis 阶段为 4.0x，在 fetal_movement 阶段为 1.5x
- **AC-04.3**: 当 toxin_exposure 不为 "none" 时，系统 SHALL 随机选取 1-2 种毒素类型，并在每个阶段查询其对应的风险倍数
- **AC-04.4**: 致畸风险倍数 SHALL 与现有 defect_risk_multiplier 相乘，影响该阶段的缺陷掷骰
- **AC-04.5**: gestation_log 中 SHALL 记录每阶段生效的毒素类型及其风险倍数

---

## US-05: 并发症扩展 + 综合征 [P2]

**作为** 子宫模拟系统  
**我希望** 扩展先天缺陷种类至 8-12 种，引入综合征共现和严重度连续谱  
**以便** 出生结果更丰富、更真实

### 验收标准

- **AC-05.1**: 人类物种 SHALL 支持至少 10 种先天缺陷（在现有 4 种基础上新增：clubfoot / gastroschisis / diaphragmatic_hernia / limb_reduction / microcephaly / hydrocephalus）
- **AC-05.2**: 每种缺陷 SHALL 有严重度评分 0.0~1.0（连续谱），在掷骰命中后随机生成
- **AC-05.3**: 系统 SHALL 定义综合征共现规则：当缺陷 A 命中时，缺陷 B 的概率提高 N 倍。示例：down_syndrome 命中时，congenital_heart_defect 概率 x5.0
- **AC-05.4**: Baby.complications SHALL 从 `list[str]` 变为 `list[dict]`，每项包含 `{"defect": str, "severity": float, "syndrome_origin": str | None}`
- **AC-05.5**: 旧格式 `list[str]` 的消费方 SHALL 通过兼容层获得等效数据（向后兼容）

---

## US-06: 简化遗传模型 [P2]

**作为** 子宫模拟系统  
**我希望** 引入 ParentGenome 作为输入参数，包含 8-12 个关键性状的显隐性等位基因  
**以便** 子代性状有遗传学基础，而非纯随机

### 验收标准（方案 B：不持久化）

- **AC-06.1**: 系统 SHALL 定义 ParentGenome 数据结构，包含 8-12 个人类关键性状的等位基因对（如 eye_color, hair_type, height_tendency, metabolism_type 等）
- **AC-06.2**: ParentGenome SHALL 作为 conceive() 和 API 的可选参数传入，未传入时随机生成
- **AC-06.3**: 系统 SHALL 根据孟德尔遗传规律（显隐性 + 不完全显性）从父母基因组合产生子代基因型
- **AC-06.4**: 子代基因型 SHALL 影响 Baby.phenotype 和发育过程中的倾向性
- **AC-06.5**: Baby 记录 SHALL 包含 `parent_genomes` 字段，保存父母基因的快照（dict 格式）
- **AC-06.6**: ParentGenome 本身 SHALL NOT 被持久化到任何存储中
- **AC-06.7**: 遗传逻辑 SHALL 封装在独立的 `womb/heredity.py` 文件中

---

## US-07: 胎盘建模 [P3]

**作为** 子宫模拟系统  
**我希望** 模拟胎盘的发育/衰退曲线及其并发症  
**以便** 胎盘状态成为影响资源传递效率的核心变量

### 验收标准

- **AC-07.1**: 系统 SHALL 定义胎盘发育曲线：从 zygote 阶段（效率 0.3）逐渐上升到 fetal_movement 阶段峰值（效率 1.0），然后在 birth 阶段轻微下降（0.95）
- **AC-07.2**: 胎盘效率 SHALL 作为额外乘数影响 budget_multiplier（与环境乘数相乘）
- **AC-07.3**: 系统 SHALL 以概率触发胎盘并发症：前置胎盘（placenta_previa, 0.5%）、胎盘早剥（placental_abruption, 1%）、胎盘功能不全（placental_insufficiency, 3%）
- **AC-07.4**: 胎盘并发症 SHALL 降低对应阶段及后续阶段的胎盘效率（如 insufficiency 将效率降低 20-40%）
- **AC-07.5**: 胎盘状态 SHALL 记录在每个阶段的 gestation_log 中

---

## US-08: 免疫交互 [P3]

**作为** 子宫模拟系统  
**我希望** 模拟母胎免疫兼容性、Rh 血型冲突和 TORCH 感染  
**以便** 免疫因素成为影响妊娠结局的重要变量

### 验收标准

- **AC-08.1**: 系统 SHALL 为母亲和胎儿各生成血型（ABO + Rh），并判定 Rh 不兼容性
- **AC-08.2**: 当 Rh 阴性母亲怀 Rh 阳性胎儿时，系统 SHALL 在第二次及以后怀孕中增加溶血性疾病风险（首次怀孕无影响 -- 简化为概率增加）
- **AC-08.3**: 系统 SHALL 以概率触发 TORCH 感染（Toxoplasma / Rubella / CMV / HSV），每种感染在不同阶段有不同影响
- **AC-08.4**: 免疫事件 SHALL 影响 defect_risk_multiplier 和 miscarriage_risk_multiplier
- **AC-08.5**: 免疫状态 SHALL 记录在 env 字典和 gestation_log 中

---

## 跨切面约束

### C-01: 向后兼容

- 所有现有 API 端点的请求/响应格式 SHALL 保持兼容
- 新增字段为可选，旧客户端不传入时使用默认值
- `env["nutrition"]` 字段 SHALL 继续返回字符串值
- `Baby.complications` 的 `list[str]` 格式 SHALL 通过属性/方法继续可用

### C-02: 可测试性

- 每项改进 SHALL 可通过 API 参数覆盖随机值进行确定性测试
- 环境变化事件的随机种子 SHALL 可注入

### C-03: 性能

- 新增的计算逻辑（营养素加权、毒素窗口查询、胎盘曲线）SHALL NOT 增加超过 5ms 的额外延迟（纯 CPU 计算）
- LLM 调用次数 SHALL NOT 增加（母体反馈已有，不新增额外 LLM 调用）

### C-04: 文件规模

- 每个新文件 SHALL NOT 超过 400 行
- genetics.py（当前 961 行）SHALL 在改进过程中拆分为更小的模块
