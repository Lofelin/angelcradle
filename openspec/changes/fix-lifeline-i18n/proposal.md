## Why

英文模式下 lifeline 日志混入中文内容：`PHASE 1/$9 neonatal (0-1个月)` 的 age_range、`D1-31 WORLD 春季温暖,阳光充足...` 的 world snapshot、事件 display_name/description 全部中文。根因：后端从未接收前端 `lang`，`backend/world.py:717-733` prompt 硬编码 `"MUST be in Chinese"` + JSON placeholder（`"天气描述"` / `"显示名"` / `"描述"`），`backend/cradle/phases.py:93` 硬编码 `age_range="0-1个月"`。既破坏 i18n 一致性，也阻塞海外用户演示。

## What Changes

- **新增 baby state 字段 `lang: "zh" | "en"`**，默认 `"zh"` 兼容历史 archive
- **API 契约扩展**：`POST /conceive`、`POST /cradle/start` 接收可选 `lang` 并持久化到 baby state
- **world snapshot 双语 prompt**：`world.py::_build_snapshot_prompt` 按 `state.lang` 切换 CN/EN 模板，JSON placeholder 与 Rule 10（语言要求）对应本地化；事件 `display_name`/`description` 语言跟随 state
- **phase age_range 拆字段**：`PhaseDefinition.age_range` → `age_range_zh` + `age_range_en`，lifeline 输出时按 baby.lang 选择
- **前端透传 lang**：`conceive` / `cradle/start` 请求体带当前 `lang`；创建后锁定，切换 UI 语言不改变已生成内容的语言（避免 archive 混语）

## Capabilities

### New Capabilities

- `i18n-runtime`: baby 运行时语言契约——state 持久化 lang、后端 world 生成与 lifeline 事件输出按 lang 分支、跨 SSE 事件保持语言一致

### Modified Capabilities

（无——`openspec/specs/` 当前为空，此 change 建立首个 i18n 契约作为新 capability）

## Impact

- **前端**：
  - `frontend/src/App.jsx` / `frontend/src/Cradle.jsx`：conceive / cradle start fetch 请求体追加 `lang`
- **后端 API**：
  - `backend/api/conceive.py`：请求 schema 增加 `lang`；conceive 入口写入 baby state
  - `backend/api/cradle.py`：同上；确保 lifeline SSE payload 携带 lang 相关字段
- **后端 state/schema**：
  - baby state 定义处新增 `lang` 字段（默认 `"zh"`）；老 archive 读取时缺字段回退到 `"zh"`
- **后端生成链路**：
  - `backend/world.py::_build_snapshot_prompt`：按 lang 切 CN/EN prompt 版本；JSON placeholder 本地化
  - `backend/cradle/phases.py::PhaseDefinition`：`age_range` 拆成 `age_range_zh` + `age_range_en`
  - `backend/scheduler/handlers.py`：lifeline 事件构造 age_range 文本时按 baby.lang 选字段
- **向后兼容**：
  - 老 archive 无 `lang` → 默认 `"zh"`，现有行为零变更
  - SSE 事件 schema 不破坏——仅文本内容语言变化，字段结构不动
- **不影响**：前端 `i18n.js` 静态文案、图谱拓扑（womb/cradle graph）、scheduler 核心流、memory 系统
