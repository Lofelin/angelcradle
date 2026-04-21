# 摇篮（Cradle）设计文档

> Angel Cradle 核心模块 — 从新生到独立的发育模拟系统

---

## 1. 摇篮是什么

摇篮是子宫（Womb）和世界（World）之间的桥梁。

子宫产出一份 Baby 数据——一团基因、反射和感官灵敏度。摇篮接过这团数据，用 12 个阶段的模拟，让它从只会哭的新生儿长成能说"我自己来"的独立个体。

**核心信念**：每个 Baby 的 `gestation_log` 不是一份没人读的 JSON。它是性格的源头、行为的约束、命运的底色。摇篮的使命是让这份数据**活**起来。

```
子宫 → Baby{genes, gestation_log} → 摇篮 → 独立个体 → 世界
```

## 2. 设计原则

### 2.1 出生即命运（Identity Locking）

Baby 入摇篮时，系统从 `gestation_log` 编译出一份**身份约束**（Identity）——感官画像、唤醒基线、气质、反射、行为规则。编译完成后，终身锁定。

这不是限制，是个性的根基。一个听觉主导的 Baby 永远会对声音更敏感；一个高唤醒基线的 Baby 终生容易过度刺激。后天经历塑造表现，但先天底色不变。

### 2.2 同一事件，不同灵魂（Perceptual Filtering）

雷暴来了。听觉主导的 Baby 被雷声震撼；视觉主导的 Baby 被闪电吸引；高唤醒的 Baby 吓哭了；低唤醒的 Baby 只是皱皱眉。

这通过感知过滤公式实现：

```
感知强度[通道] = 事件强度 × 感官灵敏度[通道]
总感知 = Σ(各通道感知) × 唤醒修正系数
```

**不是 LLM 随机编，是数学决定差异，LLM 只负责表达。**

### 2.3 表达能力即牢笼（Expression Mode Enforcement）

阶段 0 的 Baby 只能哭。不是"建议只哭"，是**强制只哭**。LLM prompt 明确写死：

> "当前表达模式：cry_only。只能输出身体反应和哭声描述。不能出现任何词语。"

这是摇篮最重要的约束之一。没有这个约束，LLM 会让新生儿说出完整句子——那不是 Baby，那是戴婴儿面具的成人。

10 种表达模式严格随阶段递进：

| 阶段 | 模式 | 允许的输出形式 |
|------|------|---------------|
| 0 | cry_only | 身体动作 + 哭声，零词语 |
| 1 | coo_and_gaze | 元音（啊、呜）+ 注视方向 |
| 2 | babble_and_reach | 叠音（ba-ba）+ 伸手抓握 |
| 3-4 | gesture_and_point | 指向 + 手势 + 急迫发音 |
| 5 | first_words | 单词 + 动作（发音可能不准） |
| 6 | two_word | 2-3 词句（语法不完整） |
| 7 | sentence | 完整句子 + 追问 |
| 8 | narrative | 多句叙事 + 想象力 |
| 9-10 | reasoning | 带逻辑连接词的复杂句 |
| 11 | independent | 段落论述 + 独立观点 |

### 2.4 父母不是观众（Parent as Co-author）

关键事件（高烧、第一次摔倒、噩梦）发生时，模拟暂停，等待父母介入。父母不是在看一部动画片——每一次选择都真实地改变 Baby 的心理状态：

- **安抚**（comfort, hold）→ 安全依恋
- **忽视**（let_cry, ignore）→ 回避依恋
- **不一致** → 焦虑依恋

父母的行为被持续追踪为画像（responsiveness, intervention_style, teaching_frequency, emotional_tone），影响长期依恋形成。

### 2.5 LLM 是笔，不是脑（LLM as Expression, Not Decision）

摇篮的核心决策全部由规则引擎驱动：
- 事件掷骰 → 随机数 + 权重
- 感知过滤 → 数学公式
- 能力解锁 → 阶段对照表
- 依恋更新 → 行为分类规则

LLM 只在四个场景被调用，且每次都被严格约束：

| 场景 | 调用次数 | LLM 的职责 |
|------|---------|-----------|
| 身份编译 | 1 次/生 | 将发育数据编译为自然语言行为约束 |
| 环境事件反应 | 1 次/阶段 | 批量为环境事件生成符合约束的反应文本 |
| 关键事件反应 | 1 次/事件 | 为关键事件 + 父母行为生成反应 |
| 阶段总结 | 1 次/阶段 | 回顾阶段记忆，生成发育总结 |

**设计决策**：环境事件批量调用而非逐个调用。一个阶段 2 个环境事件，打包成一次 LLM 调用。省 token，降延迟，维持叙事一致性。

---

## 3. 系统架构

### 3.1 模块职责

```
cradle/
├── phases.py      ← 静态数据：12 阶段定义、表达模式、世界就绪条件
├── state.py       ← 数据模型：Identity/BabyState/Memory/Milestone + JSON 持久化
├── identity.py    ← 编译器：gestation_log → Identity（规则提取 + LLM 约束生成）
├── events.py      ← 事件库：32 种事件定义 + 掷骰引擎
├── mind.py        ← 认知层：感知过滤 + LLM prompt 构建 + 反应解析
├── nanny.py       ← 引擎层：阶段模拟循环 + 能力解锁 + 里程碑 + 依恋追踪
└── __init__.py    ← 入口：admit() + check_world_readiness()

api/cradle.py      ← 9 个 FastAPI 端点
nursery/{id}/      ← 持久化存储（每 Baby 一个 state.json）
```

### 3.2 数据流

```
                    ┌──────────────┐
                    │  子宫 (Womb) │
                    │  Baby + Log  │
                    └──────┬───────┘
                           │ admit()
                           ▼
                    ┌──────────────┐
                    │  身份编译器   │  identity.py
                    │  Log → Identity │
                    └──────┬───────┘
                           │
                           ▼
         ┌─────────────────────────────────┐
         │           阶段模拟循环            │  nanny.py
         │                                 │
         │  ┌─────────┐  ┌──────────────┐  │
         │  │ 事件掷骰 │→│ 日常事件处理  │  │  events.py → 规则引擎
         │  │ events   │  │  (无 LLM)    │  │
         │  └─────────┘  └──────────────┘  │
         │       │                          │
         │       │        ┌──────────────┐  │
         │       └───────→│ 环境事件处理  │  │  mind.py → 感知过滤 → LLM
         │                │ (批量 LLM)   │  │
         │                └──────────────┘  │
         │                                 │
         │  ┌──────────────────────────┐   │
         │  │ 关键事件 → 暂停等待父母  │   │
         │  └──────────┬───────────────┘   │
         │             │ 父母选择           │
         │             ▼                    │
         │  ┌──────────────────────────┐   │
         │  │ 关键事件处理 (单次 LLM)  │   │  mind.py → 依恋更新
         │  └──────────────────────────┘   │
         │                                 │
         │  ┌──────────────────────────┐   │
         │  │ 阶段总结 (单次 LLM)      │   │  mind.py → 发育回顾
         │  └──────────┬───────────────┘   │
         │             │ 推进下一阶段       │
         └─────────────┼───────────────────┘
                       │
                       ▼ （重复 12 次）
                ┌──────────────┐
                │  世界就绪检查  │  phases.py
                │  Hard + Soft  │
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐
                │   世界 (World) │
                └──────────────┘
```

### 3.3 状态模型

```
BabyState
├── 不可变层（出生锁定）
│   ├── baby_id, species
│   └── Identity
│       ├── SensoryProfile (hearing, vision, touch, smell, proprioception)
│       ├── arousal_baseline (low / moderate / high)
│       ├── reflex_patterns, instinct_loops
│       ├── temperament, tendencies, defects
│       └── constraints（5-8 条行为规则）
│
├── 发育层（阶段递进）
│   ├── current_phase (0-11)
│   ├── age_days
│   ├── capabilities[]（已解锁能力）
│   └── expression_mode（当前表达模式）
│
├── 心理层（事件塑造）
│   ├── attachment_style (forming → secure/anxious/avoidant)
│   ├── fears[], preferences[], comfort_sources[]
│   └── memories[] → Memory{stimulus, reaction, trace, valence}
│
├── 成就层
│   ├── milestones[] → Milestone{capability_trigger, description}
│   └── phase_summaries[] → {summary, personality_notes}
│
└── 关系层
    └── ParentProfile
        ├── responsiveness (0-1)
        ├── intervention_style
        ├── teaching_frequency
        ├── emotional_tone
        └── intervention_log[]
```

---

## 4. 关键设计决策

### 4.1 为什么身份一次编译，不持续进化？

**决策**：Identity 在 `admit()` 时一次编译，之后只读。

**原因**：
1. 真实婴儿的先天气质不会改变，改变的是行为表现
2. 如果约束持续演化，LLM 输出会逐渐偏离出生设定，到第 11 阶段完全看不出是同一个 Baby
3. 固定约束让因果链可追溯——"这个 Baby 怕黑是因为 ta 听觉主导 + 高唤醒 + 阶段 2 经历了雷暴"

### 4.2 为什么日常事件不用 LLM？

**决策**：日常事件（进食、睡眠等）纯规则处理，零 LLM 调用。

**原因**：
1. 日常事件高频低叙事价值——每阶段 3 个，12 阶段就是 36 次。如果每次调 LLM，身份编译 1 + 日常 36 + 环境 12 + 关键 ~8 + 总结 12 = 69 次调用。去掉日常后 33 次。
2. 日常事件的反应可以用公式精确计算：`强度 × 灵敏度 × 唤醒修正`，不需要 LLM 的创意
3. 日常事件不产生记忆（Memory），不影响心理状态，不需要叙事深度

### 4.3 为什么环境事件批量而不逐个？

**决策**：一个阶段的 2 个环境事件打包成一次 LLM 调用。

**原因**：
1. 减少调用次数（12 次 → 12 次，但每次处理 2 个事件）
2. LLM 能看到同一阶段的多个事件，保持叙事连贯
3. 批量 prompt 能共享上下文（Identity 约束、当前能力、表达模式），避免重复 token

### 4.4 为什么关键事件必须暂停？

**决策**：关键事件触发后，模拟暂停，返回给调用方等待父母选择。

**原因**：
1. 关键事件是父母参与的唯一窗口。如果自动处理，用户变成纯观众
2. 父母选择直接影响依恋类型——这是摇篮最重要的交互性来源
3. 暂停-介入-继续的节奏创造了叙事张力

### 4.5 为什么用 JSON 文件而不是数据库？

**决策**：每个 Baby 一个 `nursery/{id}/state.json`。

**原因**：
1. 摇篮的数据模型是深度嵌套的（Identity → SensoryProfile、memories → Memory、milestones → Milestone），关系型数据库需要大量 JOIN
2. 单 Baby 数据量小（完整 12 阶段大约 50-100KB JSON）
3. 文件系统天然隔离，不存在并发冲突（一个 Baby 同一时间只会被一个请求操作）
4. 开发阶段优先。如果未来需要查询（"找出所有安全依恋的 Baby"），再引入数据库

---

## 5. 事件系统详解

### 5.1 三层事件金字塔

```
          ╱╲
         ╱  ╲        关键事件 (10种)
        ╱ 🔴 ╲       高影响 · 父母介入 · 单独 LLM
       ╱──────╲
      ╱        ╲      环境事件 (15种)
     ╱   🟡    ╲     中影响 · 产生记忆 · 批量 LLM
    ╱────────────╲
   ╱              ╲    日常事件 (7种)
  ╱      🟢       ╲   低影响 · 背景噪音 · 纯规则
 ╱──────────────────╲
```

### 5.2 事件掷骰

每个阶段模拟时：

1. **日常**：从符合当前阶段的事件中随机抽 3 个
2. **环境**：从符合当前阶段的事件中加权随机抽 2 个（weight 越大越可能被选中）
3. **关键**：每个符合当前阶段的关键事件独立判定，概率 = `weight × 0.3`

### 5.3 事件属性

每个事件定义包含：
- `sensory_channels`：激活哪些感官通道（决定感知过滤的输入）
- `intensity`：基础刺激强度 0-1（决定反应烈度）
- `phase_range`：允许出现的阶段范围
- `weight`：出现概率权重
- `parent_choices`：父母可选行为（仅关键事件）

---

## 6. 里程碑系统

14 个发育里程碑，由能力解锁自动触发：

| 里程碑 | 触发能力 | 最早阶段 |
|--------|---------|---------|
| 第一次微笑 | social_smile | 1 |
| 第一次抓握 | grasping | 2 |
| 第一次笑 | laugh | 2 |
| 第一次翻身 | rolling | 2 |
| 发现自己的手 | hand_discovery | 2 |
| 客体恒存 | object_permanence | 3 |
| 陌生人焦虑 | stranger_anxiety | 3 |
| 第一次爬行 | crawling | 4 |
| 有意图的行为 | intentional_action | 4 |
| 第一个词 | first_words | 5 |
| 第一次行走 | walking | 5 |
| 认出自己 | self_recognition | 6 |
| 第一次说"不" | boundary_testing | 9 |
| 独立观点 | independent_opinion | 11 |

里程碑是**被动检测**，不是主动触发。每次能力解锁后扫描里程碑表，满足条件即记录。

---

## 7. 依恋模型

### 7.1 四种依恋类型

```
forming → ┬→ secure    （父母持续响应、温暖、一致）
          ├→ anxious   （父母响应不一致，时而温暖时而冷漠）
          └→ avoidant  （父母持续忽视、冷淡、回避）
```

### 7.2 更新规则

每次关键事件父母介入后，根据行为分类更新：

| 行为类别 | 代表行为 | 倾向 |
|---------|---------|------|
| 响应性 | comfort, hold, validate, explain_return | → secure |
| 回避性 | let_cry, ignore, sneak_away | → avoidant |
| 平衡性 | encourage, boundary, negotiate, gradual | → secure |
| 混合性 | 历史记录中响应/回避交替 | → anxious |

### 7.3 父母画像

持续追踪的维度：
- `responsiveness`（0-1）：响应性行为 +0.05，回避性行为 -0.05
- `intervention_style`：protective / balanced / hands_off
- `teaching_frequency`（0-1）：主动教导频率
- `emotional_tone`：warm / neutral / anxious

---

## 8. 世界就绪检查

Baby 不是自动毕业，是能力达标才能进入世界。

### 硬性条件（全部满足）

| 条件 | 要求能力 |
|------|---------|
| 语言表达 | full_sentences |
| 自我概念 | self_recognition + independent_opinion |
| 心智理论 | basic_empathy |
| 情绪调节 | complex_emotion |

### 软性条件（质量指标）

| 条件 | 来源 |
|------|------|
| 好奇心 | why_questions 能力 |
| 社交技能 | peer_awareness 能力 |
| 韧性 | emotional_storms 经历后的恢复 |
| 独立性 | independent_opinion + self_advocacy |

硬性条件未满足不允许进入世界。软性条件未满足可以进入，但带着发展缺陷。

---

## 9. API 设计

### 9.1 端点总览

| 端点 | 方法 | 说明 | LLM 调用 |
|------|------|------|---------|
| `/cradle/admit` | POST | 入摇篮，编译身份 | 1 次 |
| `/cradle/babies` | GET | 列出所有 Baby | 0 |
| `/cradle/{id}/status` | GET | 当前状态 | 0 |
| `/cradle/{id}/advance` | POST | 推进阶段（同步） | 1-N 次 |
| `/cradle/{id}/advance/stream` | GET | 推进阶段（SSE 流） | 1-N 次 |
| `/cradle/{id}/intervene` | POST | 父母介入关键事件 | 1 次 |
| `/cradle/{id}/complete` | POST | 完成阶段，生成总结 | 1 次 |
| `/cradle/{id}/history` | GET | 完整成长历史 | 0 |
| `/cradle/{id}/readiness` | GET | 世界就绪检查 | 0 |

### 9.2 典型交互流程

```
1. POST /cradle/admit          → Baby 入摇篮，获得 Identity
2. POST /cradle/{id}/advance   → 模拟阶段 0，返回事件和反应
   ↳ 如果有关键事件：
     3. POST /cradle/{id}/intervene  → 父母选择行为
     （重复直到所有关键事件处理完）
4. POST /cradle/{id}/complete  → 生成阶段总结，推进到阶段 1
5. 重复 2-4 直到阶段 11 完成
6. GET /cradle/{id}/readiness  → 检查是否可以进入世界
```

### 9.3 SSE 流事件序列

`GET /cradle/{id}/advance/stream` 的事件流：

```
event: phase_start        → {phase, expression_mode}
event: daily_events       → {events: [...]}
event: environment_reaction → {event, reaction, memory}  (逐个)
event: critical_event     → {event, choices}  (逐个，等待 intervene)
event: capabilities_unlocked → {new_capabilities: [...]}
event: milestones         → {new_milestones: [...]}
event: phase_simulated    → {summary}
```

---

## 10. LLM Prompt 策略

每次 LLM 调用都注入以下上下文：

```
系统角色: 你是一个婴儿发育模拟器
身份约束: [5-8 条行为规则，必须遵守]
当前阶段: phase N — {阶段名称}
表达模式: {模式名} — {格式要求}
已有能力: [能力列表]
近期记忆: [最近 5 条记忆]
先天缺陷: [缺陷列表，不可忽视]
```

**关键约束注入模式**：约束不是"参考"，是"规则"。Prompt 中使用 MUST/NEVER 级别的措辞确保 LLM 遵守。

---

## 11. 局限与未来

### 当前局限

1. **单线程模拟**：一个 Baby 的阶段推进是顺序的，不支持并行多阶段
2. **事件库有限**：32 种事件覆盖基本场景，高阶段（5-11）缺少阶段特有事件
3. **依恋模型简化**：现实中依恋是连续谱，当前是离散分类
4. **无回退机制**：阶段只能前进，不能因创伤回退发育
5. **单物种优化**：当前事件和阶段以人类婴儿为设计目标

### 未来方向

1. **阶段特有事件**：为高阶段补充学龄前特有场景（入园焦虑、友谊冲突等）
2. **多胎并行**：共享环境事件但独立反应，双胞胎互动
3. **物种适配**：狗/猫的发育阶段重定义（8 周社会化窗口等）
4. **发育回退**：重大创伤可能导致暂时性行为退行
5. **父母多角色**：区分父/母/祖父母的不同影响

---

## 附录：代码量统计

| 文件 | 行数 | 职责 |
|------|------|------|
| `cradle/phases.py` | 252 | 阶段定义 + 表达模式 |
| `cradle/state.py` | 311 | 数据模型 + 持久化 |
| `cradle/identity.py` | 355 | 身份编译器 |
| `cradle/events.py` | 492 | 事件系统 |
| `cradle/mind.py` | 415 | 认知反应 |
| `cradle/nanny.py` | 459 | 保姆引擎 |
| `cradle/__init__.py` | 95 | 入口函数 |
| `api/cradle.py` | 294 | API 端点 |
| **合计** | **~2673** | |
