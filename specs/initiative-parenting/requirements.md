# Requirements: Initiative Parenting (主动需求 + 限时响应)

## 概述

宝宝在自驱动生命推进过程中，会主动向用户发起需求（饿了、怕了、想玩等）。
用户需在限定时间内响应，否则保姆/照护者自动降级处理。
用户亲自响应与保姆代替响应产生不同的成长效果，形成"养育参与度"的核心循环。

---

## US-1: 宝宝主动发起需求

**作为**父母用户，**我希望**宝宝在生命推进过程中会主动表达需求，**以便**我能感受到宝宝是一个有需求的活生命体，而不是被动的模拟对象。

### 验收标准

- **When** scheduler `_run_day` 推进到需求评估点，**the system shall** 根据宝宝当前 stress、上次互动时间、阶段特征评估是否发起需求。
- **When** 评估结果为需发起需求，**the system shall** 从当前阶段的 BehaviorSpace triggers 中选取一个适合的需求类型（hunger/fear/pain/sleepy/curious/bored/share/play 等）。
- **When** 宝宝处于新生儿阶段（Phase 0-2），**the system shall** 主要发起生理需求（hunger/sleepy/pain），社交需求概率极低。
- **When** 宝宝处于大孩子阶段（Phase 5+），**the system shall** 增加社交情感需求（play/share/curious/bored）的发起概率。
- **When** 需求发起成功，**the system shall** 将需求事件写入 events.jsonl，包含需求类型、紧急度、超时时间、表达文本。

---

## US-2: 需求频率控制

**作为**父母用户，**我希望**宝宝的需求发起频率合理，**以便**不会因为需求过于频繁而感到疲惫，也不会因为太少而失去参与感。

### 验收标准

- **When** 时间倍速为 normal 模式，**the system shall** 平均每 15-30 分钟真实时间发起一次需求（约 2-4 sim days 间隔）。
- **When** 上一次需求尚未处理完毕（pending 状态），**the system shall** 不发起新的需求。
- **When** 用户刚完成一次互动（interact），**the system shall** 在冷却期内（至少 1 sim day）不发起新需求。
- **When** 宝宝 stress 较高（>0.6），**the system shall** 提高需求发起概率。
- **When** 用户长时间未互动（>5 sim days），**the system shall** 提高需求发起概率。

---

## US-3: 限时等待与日推进暂停

**作为**父母用户，**我希望**宝宝发起需求后生命推进暂停等待我响应，**以便**我有时间看到需求并做出回应。

### 验收标准

- **When** 需求事件写入后，**the system shall** 在 `_run_day` 循环中插入 `await asyncio.sleep(timeout)` 暂停日推进。
- **When** 需求为生理类型（hunger/pain），**the system shall** 设置超时时间为 120 秒（2 分钟）。
- **When** 需求为情感类型（fear/sleepy），**the system shall** 设置超时时间为 180 秒（3 分钟）。
- **When** 需求为社交类型（play/share/curious/bored），**the system shall** 设置超时时间为 300 秒（5 分钟）。
- **While** 等待用户响应，**the system shall** 不改变全局 time_scale 设置。
- **When** 用户通过 `POST /interact` 响应，**the system shall** 通过 asyncio.Event 信号立即唤醒 scheduler 继续推进。

---

## US-4: 用户响应产生积极效果

**作为**父母用户，**我希望**我的及时响应能对宝宝产生积极影响，**以便**我感到自己的养育行为有意义。

### 验收标准

- **When** 用户在超时前通过 `POST /interact` 响应需求，**the system shall** 降低宝宝 stress（-0.1）。
- **When** 用户响应需求，**the system shall** 将依恋风格向 secure 方向偏移。
- **When** 用户响应特定类型的需求（如 play/curious），**the system shall** 有概率形成新的偏好（preference）。
- **When** 用户响应需求，**the system shall** 记录到 events.jsonl 并标记为用户响应类型。
- **When** 用户响应需求，**the system shall** 重置 initiative 的 consecutive_ignores 计数。

---

## US-5: 保姆降级处理

**作为**系统，**当**用户超时未响应需求，**the system shall** 自动生成保姆/照护者的降级响应，保证宝宝需求被满足但效果减弱。

### 验收标准

- **When** 等待超时，**the system shall** 自动生成一条保姆响应事件，使用预设模板文本（不调用 LLM）。
- **When** 保姆降级处理需求，**the system shall** 降低宝宝 stress（-0.05，仅为用户响应效果的一半）。
- **When** 保姆降级处理需求，**the system shall** 不增强依恋（attachment 不变）。
- **When** 保姆降级处理需求，**the system shall** 将事件记录到 events.jsonl，前端可见（如"保姆喂了奶"、"奶奶哄了哄"）。
- **When** 连续多次保姆降级（consecutive_ignores >= 3），**the system shall** 使依恋向 avoidant 方向轻微偏移。

---

## US-6: 前端需求展示

**作为**父母用户，**我希望**在前端看到宝宝的需求请求，显示为带倒计时的可交互卡片，**以便**我能直观地知道宝宝需要什么、还有多少时间响应。

### 验收标准

- **When** 需求事件通过 lifeline SSE 推送到前端，**the system shall** 在事件数据中包含：需求类型（trigger）、紧急度（urgency）、超时秒数（timeout_sec）、宝宝表达文本（expression）、发起时间戳（ts）。
- **When** 前端收到需求事件，**the system shall** 提供足够信息使前端能渲染倒计时 UI。
- **When** 需求被响应（用户或保姆），**the system shall** 推送一条响应结果事件，包含响应类型（parent/nanny）、效果摘要。
- **When** 用户在倒计时内通过已有的 `POST /interact` 端点发送消息或 touch 动作，**the system shall** 视为对当前需求的响应。
