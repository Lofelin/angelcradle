# Plan: womb-upgrade

## Tasks

### Phase 0: genetics.py 拆分（前置依赖，所有后续任务的基础）

- [x] 1. 拆分 genetics.py 为独立模块
  - [x] 1.1 创建 `womb/prompts.py`：迁移所有 STAGE_*_PROMPT 模板和 MATERNAL_RESPONSE_PROMPT (~250行)
  - [x] 1.2 创建 `womb/llm.py`：迁移 PROVIDERS、_create_client、_call_llm、_parse_json、_is_inside_object (~130行)
  - [x] 1.3 创建 `womb/stages.py`：迁移 express()、express_stream()、build_stage_prompts()、_enforce_budget、_build_env_constraint、blueprint loading、STAGE_NAMES、STAGE_DURATIONS、RESOURCE_BUDGET (~250行)
  - [x] 1.4 将 `womb/genetics.py` 改写为薄包装层：仅 re-export express、express_stream 及必要常量，保持所有 import 路径不变 (~30行)
  - [x] 1.5 验证：运行现有调用路径（`from womb.genetics import express_stream` 等）确认无 ImportError
  - [x] 1.6 更新 womb/ 目录 L2 文档

---

### Phase 1: P0 改进（动态环境 + 母体反馈 + 营养细分 + 致畸窗口）

- [x] 2. 营养素系统 (US-03)
  - [x] 2.1 创建 `womb/nutrients.py`：NUTRIENT_STAGE_SENSITIVITY 配置、NUTRITION_WEIGHTS、NUTRITION_THRESHOLDS 常量
  - [x] 2.2 实现 `generate_nutrients(overrides: dict | None) -> dict`：正态分布生成 5 个营养素值，支持覆盖
  - [x] 2.3 实现 `compute_nutrition_label(nutrients: dict) -> str`：加权计算 → 四档映射
  - [x] 2.4 实现 `get_stage_nutrient_effects(nutrients: dict, stage: str) -> dict`：返回当前阶段的营养素风险和 budget 惩罚
  - [x] 2.5 实现 `format_nutrients_for_prompt(nutrients: dict, stage: str) -> str`：生成 LLM prompt 注入文本
  - [x] 2.6 实现 `get_overall_nutrient_risk_effects(nutrients: dict) -> dict`：全阶段聚合风险用于发育前缺陷掷骰

- [x] 3. 致畸时间窗口 (US-04)
  - [x] 3.1 创建 `womb/teratogen.py`：TERATOGEN_STAGE_RISK 矩阵（6 种毒素 x 7 阶段）
  - [x] 3.2 实现 `assign_toxin_types(toxin_level: str) -> list[str]`：根据暴露等级随机选取 1-2 种毒素
  - [x] 3.3 实现 `get_teratogen_risk(toxin_types: list[str], stage: str) -> float`：查询当前阶段最大风险倍数
  - [x] 3.4 实现 `format_teratogen_for_prompt(toxin_types: list[str], stage: str) -> str`：生成 LLM prompt 注入文本
  - [x] 3.5 实现 `get_overall_teratogen_risk(toxin_types: list[str]) -> float`：全阶段聚合风险用于发育前缺陷掷骰

- [x] 4. 动态环境引擎 (US-01)
  - [x] 4.1 创建 `womb/dynamic_env.py`：ENV_CHANGE_TYPES 配置、等级移位规则
  - [x] 4.2 实现 `roll_env_change(env: dict, probability: float = 0.20) -> tuple[dict, dict | None]`：掷骰判定环境变化，返回更新后的 env 和事件记录
  - [x] 4.3 实现 `_shift_level(current: str, direction: str, scale: list) -> str`：等级单步移动工具函数

- [x] 5. 母体反馈数值化 (US-02)
  - [x] 5.1 在 `womb/dynamic_env.py` 中实现 `apply_maternal_feedback(env: dict, maternal_response: dict) -> tuple[dict, dict | None]`：解析关键词、调整 budget_multiplier、clamp、返回调整记录

- [x] 6. 集成 P0 到 environment.py
  - [x] 6.1 修改 `generate_environment()`：新增 nutrients 参数，调用 nutrients.py 生成营养素，调用 compute_nutrition_label 填充 nutrition 字段
  - [x] 6.2 修改 `generate_environment()`：调用 teratogen.py 的 assign_toxin_types，写入 env["toxin_types"]
  - [x] 6.3 修改 `compute_modifiers()`：集成营养素阶段惩罚（在 stages.py 阶段循环中叠加）
  - [x] 6.4 修改 `format_environment()`：追加毒素类型信息

- [x] 7. 集成 P0 到阶段循环
  - [x] 7.1 修改 `womb/stages.py` 的 express() 和 express_stream()：每阶段开始时调用 roll_env_change()
  - [x] 7.2 修改阶段循环：母体反馈后调用 apply_maternal_feedback()
  - [x] 7.3 修改阶段循环：每阶段计算 nutrient_effects 并叠加到 budget
  - [x] 7.4 修改阶段循环：每阶段查询 teratogen_risk 并叠加到 defect_risk
  - [x] 7.5 修改 build_stage_prompts()：注入营养素状态和致畸窗口信息到 prompt
  - [x] 7.6 修改 gestation_log 记录：追加 env_snapshot、env_event、nutrient_effects、teratogen_risk、feedback_applied

- [x] 8. 集成 P0 到 fate.py
  - [x] 8.1 修改 `roll_congenital_defects()`：接受 nutrient_risk_effects 参数，叶酸缺乏时 neural_tube_defect 概率 x3.0
  - [x] 8.2 修改 `roll_congenital_defects()`：接受 teratogen_risk 参数，叠加阶段致畸风险

- [x] 9. 集成 P0 到 API
  - [x] 9.1 修改 `api/conceive.py` 的 stream 端点：新增 folate/iodine/iron/dha/calcium 查询参数
  - [x] 9.2 修改 stream 事件生成：追加 env_change、nutrient_status、maternal_feedback_applied SSE 事件

- [x] 10. P0 验证与文档
  - [x] 10.1 验证全部模块导入、参数流通、风险聚合
  - [x] 10.2 验证向后兼容：不传新参数时行为与升级前一致
  - [x] 10.3 更新 L2/L3 文档

---

### Phase 2: P2 改进（并发症扩展 + 遗传模型）

- [x] 11. 并发症扩展 + 综合征 (US-05)
  - [x] 11.1 HUMAN_DEFECTS 扩展到 10 种缺陷
  - [x] 11.2 修改 `womb/fate.py`：roll_congenital_defects() 支持扩展后的 10 种缺陷
  - [x] 11.3 实现综合征共现：SYNDROME_CO_OCCURRENCE 矩阵 + 二次掷骰逻辑
  - [x] 11.4 实现严重度评分：命中后生成 severity = betavariate(2, 5)
  - [x] 11.5 修改返回格式：从 list[str] 变为 list[dict]（含 defect/severity/syndrome_origin）
  - [x] 11.6 修改 DEFECT_CONTRADICTION_KEYWORDS：补充新缺陷的矛盾关键词

- [x] 12. Baby 数据模型兼容性改造 (US-05)
  - [x] 12.1 修改 `womb/baby.py`：Baby.complications 类型从 list[str] 改为 list[dict]
  - [x] 12.2 新增 `Baby.complication_names` 属性：返回 list[str] 兼容旧消费方
  - [x] 12.3 修改 `Baby.to_dict()`：complications 输出新格式，新增 complication_names 字段
  - [x] 12.4 修改所有消费 complications 的代码路径使用新格式

- [x] 13. 遗传模型 (US-06)
  - [x] 13.1 创建 `womb/heredity.py`：ParentGenome dataclass、HUMAN_TRAITS 配置
  - [x] 13.2 实现 `random_genome(species: str) -> ParentGenome`：随机生成亲本基因组
  - [x] 13.3 实现 `crossover(father: ParentGenome, mother: ParentGenome) -> dict`：孟德尔杂交 → 子代基因型
  - [x] 13.4 实现 `genotype_to_phenotype(genotype: dict) -> dict`：基因型 → 表现型（显隐性 + 不完全显性 + 共显性）
  - [x] 13.5 实现 `format_genetics_for_prompt(child_genotype: dict) -> str`：生成 LLM prompt 注入文本

- [x] 14. 集成遗传模型
  - [x] 14.1 修改 `womb/__init__.py` conceive()：接受 father_genome/mother_genome 参数，调用 crossover
  - [x] 14.2 修改 Baby 构建：填充 parent_genomes 快照字段
  - [x] 14.3 修改 `womb/stages.py` build_stage_prompts()：注入遗传基因型信息
  - [x] 14.4 修改 `api/conceive.py`：stream 端点新增 father_genome/mother_genome 参数

- [ ] 15. P2 验证与文档
  - [x] 15.1 手动测试：验证综合征共现、严重度连续谱、遗传杂交
  - [x] 15.2 验证向后兼容：complication_names 属性、不传 genome 时随机生成
  - [x] 15.3 更新 L2/L3 文档

---

### Phase 3: P3 改进（胎盘 + 免疫）

- [x] 16. 胎盘建模 (US-07)
  - [x] 16.1 创建 `womb/placenta.py`：PLACENTA_EFFICIENCY_CURVE、PLACENTA_COMPLICATIONS 配置
  - [x] 16.2 实现 `init_placenta() -> dict`：初始化胎盘状态
  - [x] 16.3 实现 `update_placenta(state: dict, stage: str) -> dict`：更新效率（曲线 + 并发症触发）
  - [x] 16.4 实现 `get_placenta_budget_factor(state: dict) -> float`：返回当前胎盘效率乘数
  - [x] 16.5 集成到 environment.py 和 stages.py：胎盘效率作为 budget 额外乘数
  - [x] 16.6 集成到 prompts：注入胎盘状态描述

- [x] 17. 免疫交互 (US-08)
  - [x] 17.1 创建 `womb/immunity.py`：TORCH_INFECTIONS 配置、血型概率
  - [x] 17.2 实现 `generate_blood_types() -> dict`：随机生成母亲和胎儿血型
  - [x] 17.3 实现 `check_rh_incompatibility(maternal: dict, fetal: dict) -> bool`
  - [x] 17.4 实现 `roll_torch_infections() -> list[str]`：概率触发 TORCH 感染
  - [x] 17.5 实现 `get_immune_risk_modifiers(immunity: dict, stage: str) -> dict`：返回 defect_risk 和 miscarriage_risk 调整
  - [x] 17.6 集成到 environment.py：generate_environment() 填充 immunity 字段
  - [x] 17.7 集成到 stages.py：免疫风险叠加到阶段循环

- [ ] 18. P3 验证与文档
  - [x] 18.1 手动测试：验证胎盘曲线、并发症、免疫风险
  - [x] 18.2 验证向后兼容：不传免疫/胎盘参数时行为与升级前一致
  - [x] 18.3 更新 L2/L3 文档

---

## 剩余工作

**全部任务已完成。**

## 复杂度汇总

| Phase | 任务数 | 已完成 | 剩余 |
|-------|--------|--------|------|
| Phase 0 (拆分) | 6 | 6 | 0 |
| Phase 1 (P0) | 28 | 28 | 0 |
| Phase 2 (P2) | 18 | 18 | 0 |
| Phase 3 (P3) | 12 | 12 | 0 |
| **合计** | **64** | **64** | **0** |
