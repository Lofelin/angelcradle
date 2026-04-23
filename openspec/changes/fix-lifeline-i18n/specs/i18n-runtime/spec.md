## ADDED Requirements

### Requirement: Baby state 持久化运行时语言

系统 MUST 在每个 baby 的 state 中持久化一个 `lang` 字段，取值 `"zh"` 或 `"en"`。该字段在 baby 创建（conceive 或 cradle start）时写入，此后 MUST NOT 被前端 UI 语言切换所改变。

#### Scenario: 创建 baby 时写入 lang

- **WHEN** 前端调用 `POST /conceive` 或 `POST /cradle/start` 且请求体带 `lang: "en"`
- **THEN** 后端 MUST 将 `lang="en"` 写入该 baby 的 state 并持久化到 archive

#### Scenario: 创建后锁定 lang

- **WHEN** baby 已创建且 state 中 `lang="zh"`，前端将 UI 切换到 `en` 并继续与该 baby 交互
- **THEN** 该 baby 的后续 world snapshot / lifeline 事件 MUST 仍以 `zh` 生成，不得混入 `en` 内容

#### Scenario: 历史 archive 无 lang 字段

- **WHEN** 读取 2026-04-22 之前的老 archive，其 state 不含 `lang` 字段
- **THEN** 系统 MUST 默认为 `"en"`（全局新默认），不得抛出 KeyError 或阻塞加载

---

### Requirement: API 接受并传播 lang

`POST /conceive` 与 `POST /cradle/start` 请求体 MUST 接受可选字段 `lang`（`"zh" | "en"`，缺省 `"en"`）。后端 MUST 将该值传递到 baby state 初始化路径，且后续 SSE lifeline 事件所引用的 state 必须与该 lang 一致。

#### Scenario: 请求带 lang=en

- **WHEN** 前端 `POST /conceive { lang: "en", ... }`
- **THEN** 返回的 baby state MUST 包含 `lang: "en"`，且 SSE stream 中生成的事件内容语言 MUST 为英文

#### Scenario: 请求不带 lang

- **WHEN** 前端 `POST /cradle/start` 请求体未带 `lang` 字段
- **THEN** 后端 MUST 默认写入 `lang: "en"`（全局新默认），行为一致（BREAKING：旧默认 `"zh"` 改为 `"en"`）

#### Scenario: 非法 lang 值

- **WHEN** 请求体 `lang: "fr"` 或其它非 `"zh"/"en"` 字符串
- **THEN** 后端 MUST 返回 4xx 错误或降级到默认 `"en"`（二选一，在 design 中明确）；不得将非法值写入 state

---

### Requirement: World snapshot 按 lang 生成内容

`backend/world.py::_build_snapshot_prompt` MUST 根据 `state.lang` 选择中文或英文 prompt 模板。生成的 `weather_pattern` / `family_arc` / `ambient_mood` / 事件 `display_name` / 事件 `description` 的语言 MUST 与 `state.lang` 一致。

#### Scenario: lang=en 的世界快照

- **WHEN** `state.lang="en"` 且触发 world snapshot 生成
- **THEN** LLM prompt MUST 包含 `"display_name and description MUST be in English"` 规则与英文 JSON placeholder；返回的 snapshot 字段值 MUST 为英文

#### Scenario: lang=zh 的世界快照

- **WHEN** `state.lang="zh"` 且触发 world snapshot 生成
- **THEN** prompt 与返回内容 MUST 保持原有中文生成行为（零回归）

#### Scenario: 事件文案本地化一致性

- **WHEN** SSE lifeline 推送包含 world event 的 payload（如 `D1-31 WORLD <family_arc>`）
- **THEN** 该 payload 中源自 LLM 生成的所有自然语言字段 MUST 与 baby.lang 一致，不得出现两种语言并存

---

### Requirement: Phase age_range 双语

`backend/cradle/phases.py::PhaseDefinition` MUST 将原 `age_range` 字段拆分为 `age_range_zh` 与 `age_range_en` 两个字段，分别以中文（如 `"0-1个月"`）与英文（如 `"0-1 month"`）表达。下游消费方（lifeline handler、phase 展示）MUST 根据 baby.lang 读取对应字段。

#### Scenario: lang=en 下显示 phase age_range

- **WHEN** baby.lang="en" 且 lifeline 输出 `PHASE 1/9 neonatal (...)` 事件
- **THEN** 括号内的 age_range 文本 MUST 为 `age_range_en` 的值（如 `"0-1 month"`），不得出现中文

#### Scenario: lang=zh 下显示 phase age_range

- **WHEN** baby.lang="zh" 且同一事件触发
- **THEN** 括号内的 age_range 文本 MUST 为 `age_range_zh` 的值（如 `"0-1个月"`）

#### Scenario: 全量 12 阶段覆盖

- **WHEN** 任一 phase（0 至 11）被访问其 age_range
- **THEN** `age_range_zh` 与 `age_range_en` 字段 MUST 均已定义且非空；缺失 MUST 在单元测试中被断言失败

---

### Requirement: 前端请求透传 lang

前端在调用 `POST /conceive` 与 `POST /cradle/start` 时 MUST 将当前 UI 语言（`lang` state）作为请求体字段透传。前端切换 UI 语言 MUST NOT 对已创建 baby 的后端生成行为产生任何影响。

#### Scenario: conceive 请求带 lang

- **WHEN** 用户在英文 UI 下点击孕育
- **THEN** 前端 fetch body MUST 包含 `lang: "en"`

#### Scenario: 切换 UI 不回改已有 baby

- **WHEN** 用户在中文 UI 下创建 baby A（state.lang="zh"），然后切换到英文 UI 继续与 baby A 交互
- **THEN** baby A 的后续 SSE 事件内容 MUST 保持中文；前端 i18n.js 控制的静态文案可以切英文，两者互不耦合
