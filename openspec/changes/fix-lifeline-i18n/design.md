## Context

英文 UI 下 lifeline / world snapshot / phase age_range 混入中文。根因是 baby 创建时前端 `lang` 未透传到后端，后端生成链路（world prompt、phase 字段）硬编码中文。

现有代码里已经存在部分双语基础设施：
- `backend/scenes/schema.py::localized(lang)` —— scenes 已用 `_zh/_en` 双字段约定
- `backend/cradle/graph_emit.py:309-310 node_phase_dim(...)` —— phase 节点已接受 `age_range_zh` / `age_range_en` 两个 kwargs
- `backend/cradle/graph_story.py::PHASE_DIM_META` —— per-dim phase 的双语元数据已存在

outlier 是 `backend/cradle/phases.py::Phase.age_range: str`（12 条数据硬编码中文），以及 `backend/world.py::_build_snapshot_prompt`（prompt 硬编码 "MUST be in Chinese"）。

baby state 结构：`backend/cradle/state.py:425 BabyState`（摇篮期），有 persistent archive（`state.json`）。womb 期有独立的 baby data JSON。两者都需要写入 `lang`。

stakeholders：前端 `App.jsx` + `Cradle.jsx`（发起 conceive / cradle start）；后端 `api/conceive.py` + `api/cradle.py`（接收请求）；生成链路 `world.py` + `cradle/phases.py` + `scheduler/handlers.py`（消费 lang）。

## Goals / Non-Goals

**Goals:**

- baby 创建时 `lang` 随请求写入 state，并持久化到 archive
- world snapshot LLM 生成内容（weather/family_arc/event）语言跟随 baby.lang
- phase age_range 文本在 lifeline 事件与 LLM prompt 中按 baby.lang 本地化
- 前端 UI 语言切换不影响已创建 baby 的后端生成语言（防 archive 混语）
- 老 archive（无 lang 字段）零回归，默认中文

**Non-Goals:**

- 不做全站静态文案 i18n 重构（frontend/i18n.js 保持原样）
- 不翻译已生成的老 archive 内容（不做运行时翻译层）
- 不引入第三方 i18n 库（后端生成走 prompt 分支就够）
- 不支持第三种语言（仅 `zh` / `en`）
- 不改图谱拓扑结构、不改 SSE 事件 schema 字段

## Decisions

### D1：`lang` 字段挂在 `BabyState`（摇篮态）+ womb baby data（孕育态）

**选择**：在 `backend/cradle/state.py::BabyState` 新增 `lang: str = "zh"`；womb 期的 baby JSON（`archive/{id}/baby.json` 等入口数据）同步持久化 `lang`，在 `admit()` 拷贝到 `BabyState.lang`。

**备选**：全局线程局部（flask `g` / contextvar）携带 lang。**否**：world snapshot 生成是 DES 调度器异步触发，没有请求上下文；必须持久化。

**备选**：独立 `BabyMeta` dataclass。**否**：过度设计，单字段不值得拆。

**理由**：baby 的语言是"创建时锁定"语义，和 birthplace / identity 同性质，天然属于 state。

### D2：`Phase.age_range` 拆为 `age_range_zh` + `age_range_en`

**选择**：`phases.py::Phase` dataclass 字段 rename：`age_range: str` → `age_range_zh: str` + `age_range_en: str`；删除原字段，12 条 PHASES 数据全部补齐。

下游消费改造：
- `mind.py` × 3 + `conversation.py` × 1 的 LLM prompt：改为 `phase.age_range_en if state.lang == "en" else phase.age_range_zh`
- `scheduler/handlers.py:113` 的 `"age_range": phase.age_range` → 按 baby.lang 选字段（建议同时塞 `age_range_zh` + `age_range_en` 两份，前端按需选）
- `graph_emit.py:309-310 node_phase_dim` 已接受双字段，无需改

**备选**：保留 `age_range` 做中文，加一个 `age_range_en`，lang=en 时优先英文。**否**：不对称，容易漏改。直接拆干净。

**备选**：`phase.age_range(lang)` 函数调用式。**否**：dataclass 访问要一致性，不混函数字段。

**风险**：12 条数据漏改某一条 → 单元测试断言每个 phase 两字段均非空（对应 spec 的 "全量 12 阶段覆盖" scenario）。

### D3：world snapshot 双 prompt 模板

**选择**：`world.py::_build_snapshot_prompt(state, prev)` 内部按 `state.lang` 走两条完全独立的 f-string 分支（CN / EN），不做参数化模板拼装。

Rule 10 对应改写：
- lang=zh：`display_name and description MUST be in Chinese.` + JSON placeholder 中文
- lang=en：`display_name and description MUST be in English.` + JSON placeholder 英文（`"weather description"` / `"family story arc"` / `"display name"` / `"description"`）

Rule 11（`Inside JSON values, NEVER use ASCII double quotes`）保留；EN 模式下把 `「」` 换成 `'...'`（英文单引号）。

**备选**：一份模板 + `{language_instruction}` 等多个占位变量。**否**：LLM prompt 微小差异（标点、例子）很难参数化，分叉更清晰。维护成本两个字符串 vs 一个复杂模板——字符串更轻。

**备选**：先中文生成再调 LLM 翻译。**否**：双调用成本 + 翻译劣化 + 一致性失控。

### D4：非法 `lang` 值处理：4xx 拒绝

**选择**：`api/conceive.py` + `api/cradle.py` 的请求校验拒绝非 `"zh"/"en"` 值（Pydantic `Literal["zh", "en"]`），返回 422。缺省（字段未传）视为合法，默认 `"zh"`。

**备选**：静默降级到 `"zh"`。**否**：隐藏前端 bug，违反诚实原则。

### D5：老 archive 无 `lang` → 读时默认 `"en"`（已调整为全局新默认），不做迁移脚本

**选择**：`BabyState` 的 `lang` 字段默认 `"en"`（2026-04-22 追加决定：用户倾向英文默认，全局对齐）。`state.py` 里的 `from_dict` / `load_state` 路径用 `d.get("lang", "en")` 防御解析。

**取舍**：老 archive 原本是中文生成的，默认跳成 en 后新生成事件会与历史中文内容混合。用户接受此权衡（产品定位面向国际用户）。

**备选**：写迁移脚本扫 archive 批量回填。**否**：read-time fallback 已足够，写迁移要处理未 shutdown / 多进程竞态，性价比低。

### D6：前端锁定规则：已创建 baby 的 lang 不随 UI 切换改变

**选择**：前端只在 `POST /conceive` 和 `POST /cradle/start` 的 fetch body 带 `lang`；后续 SSE 订阅 / 查询端点不带 lang 覆盖。baby.lang 在后端是单写语义。

**前端表现**：切换到英文 UI 后，之前在中文下创建的 baby 的 lifeline 仍显示中文——这是正确行为（archive 一致性 > UI 一致性）。

**优化空间**（非本 change）：未来可在 baby 列表上标 `🇨🇳 / 🇬🇧` 角标提示创建语言。

## Risks / Trade-offs

- **[数据漏改]** phases.py 12 条 age_range 只改一半 → 运行时某 phase 报 AttributeError
  - **Mitigation**：新增单元测试 `test_phase_age_range_bilingual` 断言所有 12 phase 的 `age_range_zh` / `age_range_en` 均非空
- **[LLM 不遵守语言规则]** lang=en 下 LLM 仍输出中文 event name
  - **Mitigation**：prompt Rule 10 明确措辞 + 返回后做轻量 post-check（若 display_name 含中文字符且 state.lang="en"，日志 warn 但不 raise——保持生成链路健壮）
- **[混语 archive]** 用户手工改 archive 的 `lang` 字段导致 world_snapshot 已是中文但 phase 输出英文
  - **Mitigation**：不做防御，手工篡改 archive 不在支持范围
- **[前端遗漏传 lang]** 某次 refactor 漏传 `lang` → 默认 `"zh"`
  - **Mitigation**：前端 e2e 在英文 UI 下孕育一个 baby，断言 state.lang == "en"（可在未来的 cypress 里补；本 change 仅做后端单测覆盖）
- **[prompt 双模板维护]** world.py 两份 f-string 以后可能分叉
  - **Mitigation**：放同一函数内紧邻代码块，PR review 时强制两侧同步修改；后期若模板更复杂再抽象

## Migration Plan

1. **Phase A（后端契约）**：
   - `BabyState` 加 `lang` 字段 + `state.py::from_dict` 兼容解析
   - `api/conceive.py` + `api/cradle.py` 接受 `lang: Literal["zh","en"]=zh`
   - 单测：非法 lang 返回 422；缺省 lang 默认 zh
2. **Phase B（phases.py 双字段）**：
   - `Phase` dataclass 字段拆分 + 12 条数据回填
   - `mind.py` / `conversation.py` / `scheduler/handlers.py` 的 4 处 `.age_range` 调用点改按 lang 选字段
   - 单测：全量 phase 双字段非空
3. **Phase C（world.py 双 prompt）**：
   - `_build_snapshot_prompt` 分叉 CN/EN
   - 单测：lang=en 时 prompt 包含 `"MUST be in English"`；lang=zh 时包含 `"MUST be in Chinese"`
4. **Phase D（前端透传）**：
   - `App.jsx` conceive fetch body 加 `lang`
   - `Cradle.jsx` cradle/start fetch body 加 `lang`
   - 手测：英文 UI 下新建 baby，lifeline 出现英文 age_range / world snapshot
5. **Phase E（验证）**：
   - 跑四道 Gate：pytest 绿 / 字段语义对 / lifeline 整体无中文 / 中文 UI 零回归

**回滚策略**：每个 phase 独立 commit；整体回滚只需 revert 后端 commits，前端无 lang 字段时后端默认 zh 完全兼容。

## Open Questions

1. ~~非法 lang 值是 422 还是降级？~~ → D4 已决定 422
2. ~~新 lang 字段挂哪？~~ → D1 已决定 BabyState + womb baby JSON
3. womb 期（`stages.py`）是否也有生成内容需要按 lang 切？
   - 需 tasks 阶段 audit。本 change 主要针对 cradle + world，womb 扩展可作 follow-up
4. LLM 实际返回英文效果是否达标？需先跑一轮 tasks 阶段实测再评估
