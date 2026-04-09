# 子宫（Womb）设计文档

> Angel Cradle 核心模块 — 从虚无到第一声啼哭的发育模拟系统

---

## 1. 子宫是什么

子宫是 Angel Cradle 的起点。它模拟从受精到出生的完整过程——不是"生成一个角色"，是让一个生命在 7 个发育阶段中逐层涌现。

输入一个物种名，输出一个 Baby。这个 Baby 不是模板填充的产物，而是环境、概率、资源竞争和 LLM 逐层叠加的结果。

```
species → 环境生成 → 命运掷骰 → 7 阶段发育 → Baby{genes, gestation_log, first_cry}
```

**核心信念**：没有两个 Baby 是一样的。不是因为随机数不同，而是因为每一步的资源分配、环境约束、缺陷累积和母体反馈都在把发育推向不同的方向。

## 2. 设计原则

### 2.1 不可重来（No Retries）

子宫没有"重试"按钮。LLM 调用失败 = 发育失败。资源分配超标 = 代码强制缩减。先天缺陷 = 终生携带。

这不是技术偷懒，是设计哲学：**真实的发育没有存档点**。流产、死胎、缺陷——这些不是 bug，是概率的忠实执行。

### 2.2 代码执法，不靠 LLM 自觉（Code Enforcement）

LLM 是叙事引擎，不是规则引擎。子宫的三层执法机制：

1. **预算执法**（`_enforce_budget`）：LLM 输出的资源分配超过预算？代码等比缩减，不问 LLM 的意见
2. **语义校验**（`validate_resource_semantics`）：分配了 10% 资源却描述为"高度发达"？标记矛盾
3. **缺陷一致性**（`validate_defect_consistency`）：Baby 有先天心脏缺陷，LLM 却写"心脏功能正常"？注入纠正标记

**LLM 负责想象，代码负责真实。**

### 2.3 环境不是标签，是乘数（Quantitative Environment）

母体环境不是一句"营养良好"的标签。每个环境因素都映射到精确的数值修正：

```
有效预算 = 基础预算 × 营养修正 × 压力修正 × 毒素修正 × 年龄修正 × 多胎系数
```

营养严重缺乏（×0.70）+ 重度压力（×0.80）+ 毒素暴露（×0.70）= 有效预算仅为基础的 39%。这个 Baby 的每个发育阶段都在资源匮乏中挣扎——不是 LLM 被告知要"写得悲惨一点"，是数学上它就只有这么多资源可分配。

### 2.4 逐层涌现，不是一步到位（Layered Emergence）

一次 LLM 调用生成一个完整角色？那不是发育，那是捏人。

子宫用 7 个阶段，每个阶段一次 LLM 调用，上一阶段的输出是下一阶段的输入。受精卵决定体质底色，早期器官形成奠定感官偏向，神经发育塑造反射和本能，胎动建立行为模式，出生时一切汇聚为第一声啼哭。

**复杂性不是设计出来的，是涌现出来的。**

### 2.5 母体反馈环（Maternal Feedback Loop）

胎儿改变母体，母体的改变影响下一阶段的胎儿。每个发育阶段完成后，系统生成一次母体生理反应（激素变化、营养重分配、应激反应），注入下一阶段的 prompt。

这不是装饰——母体皮质醇升高会向上调节胎儿唤醒基线，营养重分配会改变资源分配格局。

---

## 3. 系统架构

### 3.1 模块职责

```
womb/
├── __init__.py       ← conceive() 入口：编排完整受孕流程
├── baby.py           ← 数据模型：Baby/ConceptionResult + ID 生成 + 性别/表型决定
├── environment.py    ← 母体环境：随机生成 + 量化修正系数计算
├── fate.py           ← 命运引擎：基于真实医学数据的概率掷骰 + LLM 输出校验
├── genetics.py       ← 发育引擎：7 阶段 prompt + LLM 调用 + 预算执法 + 流式输出
└── species/
    ├── human.yaml    ← 人类蓝图：生理/心理/繁殖/风险/遗传全谱数据
    ├── dog.yaml      ← 犬类蓝图
    └── cat.yaml      ← 猫类蓝图

api/conceive.py       ← 4 个 API 端点（受孕/流式受孕/物种蓝图/婴儿查询）
```

### 3.2 数据流

```
         conceive(species)
              │
              ▼
    ┌──────────────────┐
    │  环境生成         │  environment.py
    │  营养/压力/毒素/年龄 │
    └────────┬─────────┘
             │ 量化修正系数
             ▼
    ┌──────────────────┐
    │  命运掷骰         │  fate.py
    │                  │
    │  ① 流产判定       │──→ 流产？ → ConceptionResult{success=false}
    │  ② 胎数掷骰       │
    │  ③ 性别/表型      │  baby.py
    │  ④ 先天缺陷       │
    │  ⑤ 早产判定       │
    │  ⑥ 死胎判定       │
    └────────┬─────────┘
             │ 每个胎儿独立
             ▼
    ┌──────────────────────────────────────┐
    │  7 阶段发育引擎                        │  genetics.py
    │                                      │
    │  受精卵 → 早期器官 → 晚期器官 →        │
    │  早期神经 → 晚期神经 → 胎动 → 出生     │
    │                                      │
    │  每阶段：                              │
    │    prompt(蓝图 + 环境 + 前阶段 + 母体反馈) │
    │    → LLM 调用                          │
    │    → JSON 解析                         │
    │    → 预算执法 + 语义校验 + 缺陷一致性     │
    │    → 母体反馈生成                       │
    │    → 下一阶段                          │
    └────────┬─────────────────────────────┘
             │
             ▼
    ┌──────────────────┐
    │  Baby 组装        │
    │  ID + 基因表达     │
    │  + gestation_log  │
    │  + first_cry      │
    └──────────────────┘
```

### 3.3 Baby 数据模型

```python
Baby
├── id: str                    # "AC-YYYYMMDD-XXXX"
├── species: str               # "human" / "dog" / "cat"
├── sex: str                   # "male" / "female"
├── phenotype: dict            # {"race": "East Asian"} 或 {"breed": "Labrador"}
├── born_at: str               # ISO 时间戳
├── alive: bool                # False = 死胎
├── genes: dict                # {"expression": [...tendencies]}
├── first_cry: str             # 第一声啼哭（LLM 生成的意识初醒叙事）
├── gestation_log: list[dict]  # 7 阶段完整发育记录（摇篮的输入）
├── environment: dict          # 母体环境（营养/压力/毒素/年龄 + 修正系数）
├── complications: list[str]   # 先天缺陷列表
└── preterm: dict              # 早产信息（severity, weeks）
```

`gestation_log` 是子宫最重要的输出。它不只是日志——它是摇篮（Cradle）编译婴儿身份的唯一数据源。每一条记录包含：

```python
{
    "stage": "late_organogenesis",
    "gestation_day": 56,
    "duration_days": 21,
    "response": {                    # LLM 生成 + 代码校验后的结构化数据
        "primary_sense": "hearing",
        "weak_sense": "smell",
        "resource_allocation": {...},
        ...
    },
    "maternal_feedback": {...}       # 母体反馈（上一阶段末生成）
}
```

---

## 4. 七阶段发育系统

### 4.1 阶段总览

| # | 阶段名 | 人类天数 | 基础预算 | 核心任务 | 输出 |
|---|--------|---------|---------|---------|------|
| 1 | zygote | 7 | 100 | 体质底色 | 身体构成、感官偏向、神经密度、资源分配 |
| 2 | early_organogenesis | 28 | 50 | 器官原基 | 器官系统、感官前体、脆弱窗口 |
| 3 | late_organogenesis | 21 | 40 | 感官成熟 | 主导感官、次要感官、薄弱感官、感知风格 |
| 4 | early_neural | 35 | 45 | 突触与反射 | 原始反射、突触密度分布 |
| 5 | late_neural | 35 | 35 | 本能与髓鞘 | 本能回路、唤醒基线、髓鞘化优先级 |
| 6 | fetal_movement | 84 | 60 | 行为模式 | 运动特征、刺激反应、气质萌芽 |
| 7 | birth | 70 | 100 | 汇聚出生 | 先天倾向、第一声啼哭 |

**总计**：人类 280 天（40 周），与真实妊娠期一致。

### 4.2 阶段间的因果链

```
受精卵               → 体质底色（骨骼强还是神经强？）
  ↓
早期器官形成         → 哪些器官优先发育？感官前体偏向哪里？
  ↓（受精卵的资源分配决定了器官的上限）
晚期器官成熟         → 感官锁定：主导/次要/薄弱
  ↓（器官前体的偏向在这里固化）
早期神经发育         → 反射回路建立（薄弱感官 → 对应反射受损）
  ↓（感官强弱决定了突触密度分布）
晚期神经发育         → 本能固化、唤醒基线设定
  ↓（突触密度决定了哪些通路优先髓鞘化）
胎动               → 行为模式涌现（高唤醒 → 频繁激烈运动）
  ↓（所有前置发育的行为表达）
出生               → 第一声啼哭（一切的汇聚）
```

每一步都受前一步约束。一个在受精卵阶段把资源倾斜给骨骼系统的 Baby，到器官形成阶段神经系统就会欠发育，到神经阶段反射就会迟钝，到胎动阶段运动就会粗犷而不精细。

**这不是 LLM 自己"记住"了前面的设定——每一阶段的 prompt 都显式注入了所有前置阶段的完整输出。**

### 4.3 资源预算系统

每个阶段有基础预算（点数），LLM 必须在预算内分配资源给不同系统。

**预算修正**：
```
有效预算 = 基础预算 × 环境修正 × 多胎系数
```

**多胎资源竞争**：
| 胎数 | 每胎系数 | 说明 |
|------|---------|------|
| 1 | 1.00 | 独享全部资源 |
| 2 | 0.55 | 双胎各 55%（母体增加供给但不到 2 倍） |
| 3 | 0.40 | 三胎各 40% |
| 4 | 0.32 | |
| 5 | 0.27 | |
| 6 | 0.23 | |

**预算执法**：LLM 分配超过预算时，代码等比缩减：
```python
scale = budget / total_allocated
enforced[system] = round(original[system] × scale)
```

不问 LLM，不重新调用，直接裁。

### 4.4 母体反馈环

每个阶段完成后（出生阶段除外），系统调用一次 LLM 生成母体生理反应：

```
阶段 N 完成 → 母体反应（激素/营养/应激）→ 注入阶段 N+1 的 prompt
```

母体反应包含：
- 激素变化（皮质醇、孕酮、hCG）
- 子宫环境物理变化
- 营养重分配
- 应激/免疫反应
- 对下一阶段的影响评估

最近 2 个母体反应被注入下一阶段 prompt，保持上下文不膨胀。

---

## 5. 命运引擎

### 5.1 概率来源

所有概率来自真实医学数据（WHO、Lancet、CDC、PubMed），写在物种蓝图的 `pregnancy_risks` 中：

| 事件 | 人类概率 | 数据来源 |
|------|---------|---------|
| 流产 | 15.3% | Lancet 2021 |
| 死胎 | 1.43% | UNICEF 2023 |
| 双胎 | 1.2% | Human Reproduction 2021 |
| 三胎 | 0.074% | |
| 先天心脏缺陷 | 0.8% | CDC |
| 神经管缺陷 | 0.1% | |
| 唐氏综合征 | 0.143% | |
| 早产 | 10% | WHO 2020 |

### 5.2 环境对概率的修正

环境不仅影响资源预算，还直接修正风险概率：

**缺陷风险修正**：
```
调整后概率 = 基础概率 × 毒素修正 × 年龄修正
```

| 因素 | 无/最优 | 轻度 | 中度 | 重度 |
|------|--------|------|------|------|
| 毒素暴露 | ×1.0 | ×1.3 | ×2.0 | ×3.5 |
| 高龄（advanced） | — | — | ×2.0 | ×3.5 |

重度毒素暴露 + 高龄 = 缺陷风险 ×7.0。数学上精确，不是"可能会高一点"。

**流产风险修正**（更温和，因为基础概率已经很高）：
```
调整后概率 = 基础概率 × 压力修正 × 年龄修正
```

### 5.3 掷骰流程

```
1. 流产判定 → 失败则整个受孕终止
2. 胎数掷骰 → 人类通常 1，狗 4-7，猫高斯分布 μ=4
3. 对每个胎儿：
   a. 性别决定（XY 系统 → 50/50）
   b. 表型决定（从蓝图的 races/breeds 随机选取）
   c. 先天缺陷掷骰（每种缺陷独立判定）
   d. 早产判定（人类分三级：极早产/很早产/晚期早产）
   e. 死胎判定
4. 7 阶段发育
5. 组装 Baby
```

---

## 6. 物种蓝图系统

### 6.1 蓝图结构

每个物种一个 YAML 文件，包含：

| 板块 | 内容 | 用途 |
|------|------|------|
| physical | 身体特征、感官参数、寿命 | 注入发育 prompt |
| mental | 大脑、认知、情感、语言、意识 | 注入发育 prompt |
| morphology | 体型、体重、两性异形 | 表型生成 |
| reproduction | 孕期、胎数、照料模式 | 掷骰参数 |
| development | 胚胎/三阶段发育描述 | 注入发育 prompt |
| behavior | 学习、游戏、冲突、好奇心 | 注入神经阶段 prompt |
| ecology | 生态位、社会性、栖息地 | 注入胎动阶段 prompt |
| physiology | 代谢、体温调节、免疫 | 注入胎动阶段 prompt |
| pregnancy_risks | 流产/死胎/缺陷/早产概率 | 命运引擎数据源 |
| birth_attributes | 性别系统、种族/品种列表 | 性别和表型决定 |
| womb | 感知方式、表达方式、第一声啼哭格式 | 出生阶段 prompt |

### 6.2 蓝图的注入策略

不是每个阶段都注入完整蓝图——按需注入：

| 阶段 | 注入内容 |
|------|---------|
| 受精卵 | **完整蓝图**（奠基阶段需要全局视野） |
| 早期/晚期器官 | mental + physical（感官相关） |
| 早期/晚期神经 | behavior + development（行为相关） |
| 胎动 | ecology + physiology（生态相关） |
| 出生 | 仅前阶段汇总 + 并发症（不再需要蓝图） |

### 6.3 多物种差异

| 维度 | 人类 | 狗 | 猫 |
|------|------|-----|-----|
| 孕期 | 280 天 | 63 天 | 65 天 |
| 典型胎数 | 1 | 4-7 | ~4（高斯） |
| 表型维度 | 种族（9 种） | 品种 | 品种 |
| 性别系统 | XY | XY | XY |
| 第一声啼哭 | 意识初醒的自我叙事 | 物种特定 | 物种特定 |

---

## 7. LLM 集成

### 7.1 调用策略

每个 Baby 的 LLM 调用次数：

| 场景 | 调用次数 | 说明 |
|------|---------|------|
| 7 阶段发育 | 7 次 | 每阶段一次 |
| 6 次母体反馈 | 6 次 | 出生阶段无母体反馈 |
| **合计** | **13 次** | 单胎。双胎 = 26 次 |

### 7.2 Provider 支持

| Provider | API 协议 | 默认模型 | 环境变量 |
|----------|---------|---------|---------|
| deepseek | OpenAI 兼容 | deepseek-chat | DEEPSEEK_API_KEY |
| anthropic | Anthropic 原生 | claude-sonnet-4-6 | ANTHROPIC_API_KEY |

通过 `LLM_PROVIDER` 环境变量切换。

### 7.3 JSON 解析与修复

LLM 的 JSON 输出经常有问题。`_parse_json` 实现三级修复：

1. **直接解析**：标准 `json.loads`
2. **花括号修复**：修复数组中缺失的 `{`
3. **括号平衡**：补齐未闭合的 `}` 和 `]`

全部失败 = 发育失败。不重试。

### 7.4 流式输出

`express_stream()` 生成器逐阶段 yield SSE 事件：

```
{stage: "zygote", status: "in_progress", stage_num: 1, gestation_day: 7}
{stage: "zygote", status: "done", response: {...}, budget_enforced: false}
{stage: "zygote", status: "maternal_response"}
{stage: "zygote", status: "maternal_response_done", maternal_response: {...}}
... (重复 7 阶段)
{stage: "complete", status: "done", result: {tendencies, first_cry, gestation_log}}
```

---

## 8. API 设计

### 8.1 端点总览

| 端点 | 方法 | 说明 | LLM 调用 |
|------|------|------|---------|
| `/conceive` | POST | 同步受孕 | 13 次/胎 |
| `/conceive/stream` | GET | SSE 流式受孕 | 13 次/胎 |
| `/species/{species}/blueprint` | GET | 物种蓝图概要 | 0 |
| `/babies` | GET | 列出所有 Baby | 0 |
| `/baby/{id}` | GET | 查询单个 Baby | 0 |
| `/baby/{id}/gestation` | GET | 查询发育日志 | 0 |

### 8.2 流式受孕事件序列

`GET /conceive/stream` 的完整事件流：

```
data: {"event": "environment", "result": {nutrition, stress, toxin, age_factor, modifiers}}
data: {"event": "fate_roll", "type": "miscarriage", "result": {miscarriage: false, ...}}
data: {"event": "fate_roll", "type": "offspring_count", "result": 1}

# 每个胎儿：
data: {"event": "offspring_fate", "index": 0, "sex": "female", "phenotype": {...}, "defects": [], ...}

# 7 阶段逐个流出：
data: {"event": "stage", "index": 0, "stage": "zygote", "status": "in_progress", ...}
data: {"event": "stage", "index": 0, "stage": "zygote", "status": "done", "response": {...}}
data: {"event": "stage", "index": 0, "stage": "zygote", "status": "maternal_response"}
data: {"event": "stage", "index": 0, "stage": "zygote", "status": "maternal_response_done", ...}
... (重复 7 阶段)

data: {"event": "born", "index": 0, "alive": true, "baby": {...}}
data: {"event": "complete", "total_conceived": 1, "total_born": 1, "total_alive": 1}
```

如果流产：
```
data: {"event": "environment", ...}
data: {"event": "fate_roll", "type": "miscarriage", "result": {"miscarriage": true, ...}}
data: {"event": "miscarriage", "message": "Miscarriage at early stage (rate: 15.3%)"}
```

---

## 9. 关键设计决策

### 9.1 为什么是 7 个阶段而不是 3 个或 1 个？

**决策**：受精卵 → 早期器官 → 晚期器官 → 早期神经 → 晚期神经 → 胎动 → 出生。

**原因**：
1. **1 个阶段**（一次 LLM 调用生成完整 Baby）= 捏人，不是发育。没有因果链，没有资源竞争，没有层层约束
2. **3 个阶段**（对应三个孕期）= 粒度太粗。器官形成和感官成熟是两件不同的事，但会被合并到同一个调用里
3. **7 个阶段** = 每个阶段只做一件事，输出清晰，因果链可追溯。7 次 LLM 调用 + 6 次母体反馈 = 13 次调用，成本可控

### 9.2 为什么环境在概率掷骰之前生成？

**决策**：先生成环境，再掷所有骰子。

**原因**：环境影响一切——流产概率、缺陷概率、资源预算。如果先掷骰再生成环境，环境就变成了事后解释而不是事前约束。真实世界中，母体状况在受孕时就已经存在。

### 9.3 为什么多胎不是简单的"运行 N 次"？

**决策**：多胎共享资源池，每胎按系数分配。

**原因**：
1. 双胎不是"两个独享 100% 资源的 Baby"。母体增加供给但不到 2 倍，所以每胎 55%
2. 出生顺序影响资源——先发育的胎儿消耗更多资源（`birth_order` 参数）
3. 资源竞争导致多胎 Baby 天生比单胎小、发育可能不完全——这是生物学事实

### 9.4 为什么物种数据用 YAML 而不是硬编码？

**决策**：每个物种一个 YAML 文件，代码从中读取。

**原因**：
1. 新增物种 = 新增一个 YAML 文件，零代码改动
2. 概率数据来自医学文献，需要引用可追溯——YAML 比散落在代码里的魔法数字更可维护
3. 前端可以通过 `/species/{name}/blueprint` 直接获取展示数据

### 9.5 为什么预算执法在代码层而不是 prompt 层？

**决策**：prompt 告诉 LLM 预算是 50 点，但如果 LLM 分配了 80 点，代码直接缩减。

**原因**：
1. LLM 不擅长数学。告诉它"不要超过 50 点"它还是会超
2. 重新调用 LLM 纠正 = 多一次调用、多一次延迟、可能还是超标
3. 等比缩减是数学操作，确定性的，零延迟，不破坏相对比例

---

## 10. 与摇篮的接口

子宫的输出是摇篮的输入。接口是 `Baby.gestation_log`。

摇篮从 `gestation_log` 中提取：

| 摇篮需要 | 来源阶段 | 提取字段 |
|---------|---------|---------|
| 感官画像 | late_organogenesis | primary_sense, weak_sense, resource_allocation |
| 唤醒基线 | late_neural | arousal_baseline |
| 原始反射 | early_neural | reflexes |
| 本能回路 | late_neural | instinct_loops |
| 气质萌芽 | fetal_movement | temperament_seed |
| 先天倾向 | birth | genes.expression (tendencies) |
| 先天缺陷 | Baby.complications | — |

**gestation_log 是子宫和摇篮之间唯一的数据契约**。子宫不需要知道摇篮存在，摇篮不需要知道子宫如何运作——它只需要能解析这份日志。

---

## 11. 局限与未来

### 当前局限

1. **单次受孕**：不支持"这对父母再生一个"——没有父母基因模型，每次受孕独立
2. **环境静态**：母体环境在受孕时生成后不变。真实情况中环境会随时间变化
3. **母体反馈单向**：母体反馈注入 prompt 但不修改代码层的预算修正——是叙事影响，不是数值影响
4. **物种覆盖有限**：目前只有人/狗/猫三个蓝图
5. **无遗传模型**：没有父代基因组合——每个 Baby 是独立的概率产物

### 未来方向

1. **动态环境**：让环境因素随孕期变化（前三个月高压力，后期缓解）
2. **父代遗传**：引入父/母基因模型，让遗传产生真正的基因组合
3. **更多物种**：增加鸟类、爬行类等非哺乳动物蓝图
4. **母体反馈数值化**：让母体反馈真正修改后续阶段的预算系数
5. **并发症扩展**：更丰富的先天缺陷类型和组合效应

---

## 附录：代码量统计

| 文件 | 行数 | 职责 |
|------|------|------|
| `womb/__init__.py` | 115 | 受孕编排 |
| `womb/baby.py` | 113 | 数据模型 |
| `womb/environment.py` | 225 | 母体环境 |
| `womb/fate.py` | 260 | 命运引擎 + LLM 校验 |
| `womb/genetics.py` | 961 | 7 阶段发育引擎 |
| `womb/species/human.yaml` | 185 | 人类蓝图 |
| `api/conceive.py` | 257 | API 端点 |
| **合计** | **~2116** | |
