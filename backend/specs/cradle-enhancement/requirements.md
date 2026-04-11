# 需求：摇篮增强 (Cradle Enhancement)

六大维度补充设计，按优先级排序。所有维度必须融入现有 state.py / events.py / nanny.py 架构，不开辟平行系统。

---

## 1. 压力回退机制 (Stress Regression) -- 最高优先级

### 用户故事 1.1: 压力积累
> 作为父母，当孩子经历连续负面事件时，我希望看到压力值在上升，以便我理解孩子的心理承受状态。

**验收标准 (EARS):**
- **When** 婴儿经历一个 emotional_valence 为 negative 的事件, **the system shall** 根据事件 intensity 和依恋安全感增加压力值 (stress_level)
- **When** 婴儿经历一个 emotional_valence 为 positive 的事件且父母在场, **the system shall** 降低压力值
- **While** stress_level 低于 0.3, **the system shall** 不触发任何回退效应
- **Where** BabyState 被序列化, **the system shall** 包含 stress_level 字段且默认值为 0.0

### 用户故事 1.2: 能力回退
> 作为父母，当孩子压力值超过阈值时，我希望看到孩子出现技能退化（已会走路的要抱、已不尿床的重新尿床），因为这是真实发展心理学现象。

**验收标准 (EARS):**
- **When** stress_level 超过 0.6, **the system shall** 从最近解锁的 N 个能力中随机选择 1-2 个标记为 "regressed"
- **When** 能力被标记为 regressed, **the system shall** 在叙事和交互中表现为该能力暂时不可用
- **If** 能力属于 hard_capabilities（walking, first_words, object_permanence）, **then the system shall** 允许回退但不允许永久丧失
- **Where** 能力被标记为 regressed, **the system shall** 保留原始解锁记录，仅添加 regressed_at 时间戳

### 用户故事 1.3: 恢复与韧性
> 作为父母，当我在孩子回退期给予适当安抚和支持时，我希望看到孩子逐渐恢复，并且恢复后可能比之前更强。

**验收标准 (EARS):**
- **When** 父母在回退期选择 comfort/validate/encourage 类行为, **the system shall** 加速恢复并降低 stress_level
- **When** 能力从 regressed 状态恢复, **the system shall** 有 30% 概率标记为 "strengthened"（韧性成长）
- **When** attachment_style 为 secure, **the system shall** 将回退阈值提高 0.1（更抗压）且恢复速度加快 50%
- **When** attachment_style 为 anxious, **the system shall** 将回退阈值降低 0.1（更敏感）

### 用户故事 1.4: 回退的叙事表现
> 作为父母，我希望在成长叙事中自然地看到回退现象的描述，而不是突然的能力消失。

**验收标准 (EARS):**
- **When** 能力回退发生, **the system shall** 在下一次叙事中包含回退的行为表现（如"今天又要抱着走"）
- **When** 能力恢复, **the system shall** 在叙事中包含恢复过程描述

---

## 2. 喂养与睡眠系统 (Feeding & Sleep) -- 高优先级

### 用户故事 2.1: 喂养进阶
> 作为父母，我希望看到孩子的喂养方式随年龄自然演变，从母乳到辅食到自主进食。

**验收标准 (EARS):**
- **When** phase 为 0-2 (0-6月), **the system shall** 将喂养模式设为 breast_milk
- **When** phase 为 3 (6-9月), **the system shall** 将喂养模式过渡为 introducing_solids
- **When** phase 为 5-6 (12-24月), **the system shall** 将喂养模式设为 self_feeding_learning
- **When** phase 为 7+ (2岁+), **the system shall** 将喂养模式设为 family_meals
- **When** phase 为 7-9 (2-5岁), **the system shall** 有概率触发 picky_eating 事件

### 用户故事 2.2: 食物过敏
> 作为父母，当孩子尝试新食物时，我希望有概率遇到食物过敏事件，且我的处理方式影响后续。

**验收标准 (EARS):**
- **When** 辅食引入阶段 (phase 3-4), **the system shall** 有 15% 概率触发 food_allergy 关键事件
- **When** food_allergy 发生, **the system shall** 提供 rush_to_hospital / observe_carefully / remove_food 三个选项

### 用户故事 2.3: 睡眠回归
> 作为父母，我希望在特定月龄经历睡眠回归期，这是真实育儿中最大的焦虑来源之一。

**验收标准 (EARS):**
- **When** phase 为 2 (约4月), 3 (约8月), 6 (约18月), 7 (约2岁), **the system shall** 将睡眠回归概率提高到 80%
- **When** sleep_regression 触发, **the system shall** 增加该阶段的 stress_level（对婴儿和叙事均有影响）
- **When** 睡眠回归持续超过 1 个阶段, **the system shall** 触发 prolonged_sleep_issue 关键事件

### 用户故事 2.4: 分房睡决策
> 作为父母，我希望在合适的时机面临分房睡的决策，这影响孩子的独立性和安全感。

**验收标准 (EARS):**
- **When** phase 为 5-7 (12月-3岁), **the system shall** 有概率触发 room_separation 关键事件
- **When** room_separation 发生, **the system shall** 提供 gradual_transition / immediate / delay 三个选项
- **When** 选择 gradual_transition, **the system shall** 对独立性有正面影响且对安全感影响中性
- **When** 选择 immediate, **the system shall** 有概率增加 stress_level 和触发 sleep_regression

### 用户故事 2.5: 噩梦与夜惊
> 作为父母，我希望在学龄前看到噩梦和夜惊的区分，并理解两者的不同。

**验收标准 (EARS):**
- **When** phase 为 8-10 (3-6岁), **the system shall** 区分 nightmare（可唤醒、记得内容）和 night_terror（无法唤醒、不记得）
- **When** nightmare 发生, **the system shall** 关联婴儿已有的 fears 列表生成内容
- **When** night_terror 发生, **the system shall** 提供不同于 nightmare 的父母选项

---

## 3. 多照护者模型 (Multi-Caregiver) -- 高优先级

### 用户故事 3.1: 照护者注册
> 作为用户，我希望能够为孩子添加多个照护者（父亲、母亲、祖辈、保姆），每个有独立的风格画像。

**验收标准 (EARS):**
- **When** 用户添加照护者, **the system shall** 创建独立的 CaregiverProfile，包含 role, responsiveness, intervention_style, emotional_tone
- **Where** BabyState 被序列化, **the system shall** 使用 caregivers: dict[str, CaregiverProfile] 替代原 parent_profile
- **When** 旧版 BabyState（含 parent_profile 字段）被加载, **the system shall** 自动迁移为 caregivers["primary_parent"] 且保留原数据
- **If** 未添加任何照护者, **then the system shall** 默认创建一个 primary_parent 照护者

### 用户故事 3.2: 差异化依恋
> 作为用户，我希望孩子对不同照护者形成不同的依恋模式，这是 Bowlby 理论的核心。

**验收标准 (EARS):**
- **When** 不同照护者处理关键事件, **the system shall** 对每个照护者独立计算依恋信号
- **Where** BabyState 中存储依恋类型, **the system shall** 为每个照护者维护独立的 attachment_style
- **When** 叙事或交互需要依恋信息, **the system shall** 根据当前照护者选择对应的依恋模式

### 用户故事 3.3: 入园适应
> 作为父母，当孩子到了 3 岁左右，我希望经历入园这个重大事件，这是照护者切换的关键时刻。

**验收标准 (EARS):**
- **When** phase 为 8 (3-4岁), **the system shall** 触发 kindergarten_entry 关键事件
- **When** kindergarten_entry 发生, **the system shall** 自动添加 teacher 类型照护者
- **When** 入园初期, **the system shall** 根据 attachment_style 决定适应难度（安全型适应快，焦虑型哭闹多）

### 用户故事 3.4: 照护者风格冲突
> 作为用户，当不同照护者的育儿风格冲突时（如母亲严格、祖辈溺爱），我希望看到孩子的困惑反应。

**验收标准 (EARS):**
- **When** 两个照护者的 intervention_style 差异超过阈值, **the system shall** 在叙事中体现孩子的困惑或利用行为
- **When** 风格冲突持续超过 2 个阶段, **the system shall** 增加 stress_level

---

## 4. 情绪调节渐进系统 (Emotional Regulation) -- 中优先级

### 用户故事 4.1: 过渡客体
> 作为父母，我希望看到孩子在 1-2 岁发展出对安抚毯/玩偶的依赖，这是从外部安抚到自我安抚的桥梁。

**验收标准 (EARS):**
- **When** phase 为 5-6 (12-24月), **the system shall** 有概率为婴儿生成一个 transitional_object（从 comfort_sources 中选取或新建）
- **When** transitional_object 存在且婴儿处于压力状态, **the system shall** 在叙事中描述孩子寻找该物品
- **When** transitional_object 被拿走（作为事件）, **the system shall** 触发强烈负面反应

### 用户故事 4.2: Tantrum 频率曲线
> 作为父母，我希望体验到发脾气频率随年龄变化的真实曲线：18 月上升，2-3 岁高峰，4 岁后下降。

**验收标准 (EARS):**
- **When** phase 为 6 (18-24月), **the system shall** 将 tantrum 事件概率设为 moderate（0.4）
- **When** phase 为 7 (2-3岁), **the system shall** 将 tantrum 事件概率设为 peak（0.7）
- **When** phase 为 8 (3-4岁), **the system shall** 将 tantrum 概率降为 0.4
- **When** phase >= 9 (4岁+), **the system shall** 将 tantrum 概率降为 0.15

### 用户故事 4.3: 情绪词汇发展
> 作为父母，我希望看到孩子从只会哭到能说"我生气因为..."的渐进发展。

**验收标准 (EARS):**
- **When** expression_mode 为 cry_only 到 gesture_and_point, **the system shall** 用身体反应表达情绪
- **When** expression_mode 为 first_words 到 two_word, **the system shall** 使用基础情绪词（"不要"、"怕怕"）
- **When** expression_mode 为 sentence 到 reasoning, **the system shall** 使用情绪描述 + 原因（"我生气因为..."）

### 用户故事 4.4: 共情发展
> 作为用户，我希望看到孩子从自我中心逐步发展出真正的共情能力。

**验收标准 (EARS):**
- **When** phase 为 0-4, **the system shall** 对他人情绪无反应或仅有情绪传染（别人哭自己也哭）
- **When** phase 为 5-7, **the system shall** 开始出现原始共情（给哭泣的人递玩具）
- **When** phase 为 8-11, **the system shall** 展现真正共情（理解他人感受并作出适当回应）

---

## 5. 游戏与想象力系统 (Play & Imagination) -- 中优先级

### 用户故事 5.1: 游戏类型进阶
> 作为用户，我希望看到孩子的游戏方式随发展阶段自然演变。

**验收标准 (EARS):**
- **When** phase 为 0-4 (0-12月), **the system shall** 生成功能性游戏事件（敲打、摇晃、投掷）
- **When** phase 为 5-7 (12月-3岁), **the system shall** 生成建构游戏事件（堆积木、排列）
- **When** phase 为 7-9 (2-4岁), **the system shall** 生成象征游戏事件（过家家、假装打电话）
- **When** phase 为 9-11 (4-7岁), **the system shall** 生成规则游戏事件（棋类、比赛）

### 用户故事 5.2: 想象伙伴
> 作为父母，我希望看到 3-7 岁的孩子可能创造想象伙伴，这是认知发展的标志。

**验收标准 (EARS):**
- **When** phase 为 8-11 (3-7岁), **the system shall** 有 40% 概率为婴儿生成一个 imaginary_friend
- **When** imaginary_friend 存在, **the system shall** 在叙事和交互中让孩子提及该朋友
- **When** 父母对 imaginary_friend 的反应为 curious/accepting, **the system shall** 对创造力有正面影响

### 用户故事 5.3: 创造性表达
> 作为用户，我希望看到涂鸦→画圈→画人（头足人）→画场景的绘画发展。

**验收标准 (EARS):**
- **When** phase 为 5-6 且 drawing_discovery 事件触发, **the system shall** 生成涂鸦阶段描述
- **When** phase 为 7-8, **the system shall** 生成画圈/头足人阶段描述
- **When** phase 为 9-11, **the system shall** 生成场景画阶段描述

---

## 6. 体格生长曲线 (Physical Growth) -- 标准优先级

### 用户故事 6.1: 身高体重
> 作为父母，我希望看到孩子的身高和体重随年龄增长，提供直观的物理锚点。

**验收标准 (EARS):**
- **When** 每个阶段完成, **the system shall** 根据标准生长曲线 + 随机偏差更新 height_cm 和 weight_kg
- **Where** BabyState 被序列化, **the system shall** 包含 height_cm 和 weight_kg 字段

### 用户故事 6.2: 出牙时间线
> 作为父母，我希望在合适的时期看到出牙事件及其带来的不适。

**验收标准 (EARS):**
- **When** phase 为 3-7 (6月-3岁), **the system shall** 有概率触发 teething 日常事件
- **When** teething 发生, **the system shall** 增加 irritability 并影响 feeding 和 sleep

### 用户故事 6.3: 如厕训练
> 作为父母，我希望在 2-3 岁经历如厕训练这个重要里程碑。

**验收标准 (EARS):**
- **When** phase 为 7-8 (2-3岁), **the system shall** 触发 toilet_training 关键事件
- **When** toilet_training 发生, **the system shall** 提供 patient_encourage / strict_schedule / wait_for_readiness 三个选项
- **When** 如厕训练成功, **the system shall** 解锁 toilet_trained 里程碑

### 用户故事 6.4: 常见疾病
> 作为父母，我希望孩子偶尔生病（感冒、耳炎），这是真实育儿的一部分。

**验收标准 (EARS):**
- **When** 每个阶段, **the system shall** 有 20% 概率触发 common_illness 日常事件
- **When** common_illness 叠加其他压力事件, **the system shall** 增加 stress_level
- **When** phase < 5 (1岁前) 且 common_illness 为 high_fever, **the system shall** 升级为关键事件

---

## 跨维度约束

1. **LLM 调用预算**: 六个维度新增事件优先走规则引擎。每阶段新增 LLM 调用不超过 1 次（复用现有 narrate_phase_events 批量处理）
2. **向后兼容**: 所有新字段必须有默认值。已有 BabyState JSON 加载时不崩溃
3. **感官过滤复用**: 所有新事件必须声明 sensory_channels，复用 _compute_affinity() 和 _perceptual_filter()
4. **表达模式约束**: 所有新交互必须尊重当前 phase 的 expression_mode
5. **前端增量显示**: 新增内容通过 SSE 事件推送，前端按现有 log 模式追加显示
