## 1. 后端契约：baby state 持久化 lang

- [x] 1.1 `backend/cradle/state.py::BabyState` 新增 `lang: str = "zh"` 字段（紧邻 `species` / `name` 等基本信息区块）
- [x] 1.2 `BabyState.from_dict` / `load_state` 路径用 `d.get("lang", "zh")` 防御解析，保证老 archive 零回归
- [x] 1.3 `backend/cradle/__init__.py::admit()` 在构造 BabyState 时从 baby JSON 拷贝 `lang` 字段（womb 侧 baby data 若缺字段默认 `"zh"`）
- [x] 1.4 womb 侧 baby 出生 JSON 生成处（`backend/womb/baby.py::Baby` dataclass + `to_dict` + `womb/__init__.py::conceive`）写入 `lang` 字段，来源是 conceive 请求
- [x] 1.5 单元测试：新建 BabyState 无 lang 参数 → `state.lang == "zh"`；显式 `lang="en"` → 持久化到 state.json → 重新 load 后 `state.lang == "en"`（`scripts/test_baby_state_lang.py`）
- [x] 1.6 单元测试：load 老 archive（手工删除 state.json 的 lang 字段模拟）→ `state.lang == "zh"`，不抛 KeyError（同上脚本 test case [3]）

## 2. API 入口：接收 lang 并透传

- [x] 2.1 `backend/api/conceive.py` GET `/conceive/stream` + POST `/conceive` 新增 `lang: Optional[str]` 参数，非法值手工抛 `HTTPException(422)`
- [x] 2.2 conceive 入口将 `lang` 传递到 womb 生成链路（`conception_sessions.params["lang"]` → `_run_conception` → `Baby(lang=lang)` / `womb.conceive(lang=lang)`），最终落到 birth.json
- [x] 2.3 admit 端点（`api/cradle.py::admit_baby` / `admit_baby_stream`）无需改——admit 从 birth.json 读 baby_data，`admit_stream` 已调整 `BabyState(lang=baby_data.get("lang", "zh"))`
- [x] 2.4 单元测试：`_run_conception` 接受 lang，`conception_sessions.create({"lang": "en"})` 持久化到 params（`scripts/test_api_conceive_lang.py`）
- [x] 2.5 单元测试：非法 `lang="fr"` 抛 `HTTPException(422)`（同上脚本 test case [3]）
- [x] 2.6 单元测试：缺省 lang → 默认 "zh"（同上脚本 test case [2]）

## 3. phases.py 双字段拆分

- [x] 3.1 `backend/cradle/phases.py::Phase` dataclass 字段 rename：删除 `age_range: str`，新增 `age_range_zh: str` + `age_range_en: str`，并新增 helper 方法 `phase.age_range(lang)`
- [x] 3.2 12 条 PHASES 数据：将原 `age_range="0-1个月"` 等全部拆成 `age_range_zh="0-1个月"` + `age_range_en="0-1 month"`（月龄 month/months/years）
- [x] 3.3 单元测试 `test_phase_age_range_bilingual`：遍历全部 12 个 PHASES，断言 `age_range_zh` 和 `age_range_en` 均为非空字符串 + 英文字段无 CJK（`scripts/test_phase_age_range_bilingual.py`）
- [x] 3.4 `backend/cradle/mind.py` 的 3 处 `phase.age_range` 调用点（line 388 / 581 / 788）改为 `phase.age_range(state.lang)`
- [x] 3.5 `backend/cradle/mind.py:924` 的 `{phase.age_range}` 同 3.4 改造
- [x] 3.6 `backend/cradle/conversation.py:567` 的 `phase.age_range` 同 3.4 改造
- [x] 3.7 `backend/scheduler/handlers.py:113` + `backend/cradle/nanny.py` phase_start payload + `backend/api/cradle.py` /status + /complete 的 next_phase：同时塞 `age_range` + `age_range_zh` + `age_range_en` 三份字段（SSE schema 保持扩展兼容）。PhaseResult.age_range 字段使用 `phase.age_range(state.lang)` 本地化

## 4. world.py prompt 双语分叉

- [x] 4.1 `backend/world.py::_build_snapshot_prompt(state, prev_snapshot)` 开头读取 `lang = getattr(state, 'lang', 'zh')`，prompt 按 lang 分两条 f-string return 分支，公共 header 抽出
- [x] 4.2 lang=en 分支：Rule 10 改为 `"display_name and description MUST be in English."`，JSON template placeholder 改为英文（`"weather description"` / `"family story arc"` / `"ambient mood"` / `"display name"` / `"description"`）
- [x] 4.3 lang=en 分支：Rule 11 的 `「」` 替代为 ASCII 单引号说明
- [x] 4.4 lang=zh 分支：保持现有 prompt 完全不变（零回归）
- [x] 4.5 单元测试 `test_build_snapshot_prompt_zh`：state.lang="zh" → prompt 包含 `"MUST be in Chinese"` 且不含 `"MUST be in English"` / 含中文 placeholder / 含「」（`scripts/test_world_snapshot_prompt_lang.py`）
- [x] 4.6 单元测试 `test_build_snapshot_prompt_en`：state.lang="en" → prompt 包含 `"MUST be in English"` 且不含 `"MUST be in Chinese"` / 含英文 placeholder / 不含中文 placeholder（同上脚本）
- [ ] 4.7 手工跑一次英文孕育：英文 baby 完整生成一次 world snapshot，肉眼校验 family_arc / event display_name 全英文（**留给最终验收**——需启动后端 + LLM API，属 Gate 4）

## 5. 前端透传 lang

- [x] 5.1 `frontend/src/App.jsx:345` 已通过 `URLSearchParams({ species, lang })` 把 UI 语言透传给 `/conceive/stream`；不需改代码
- [x] 5.2 `frontend/src/Cradle.jsx` admit 调用仅用 `baby_id`，lang 由后端从 birth.json 读取；不需改代码
- [ ] 5.3 手测验证：英文 UI 下孕育 → 切到中文 UI → 继续查看该 baby → lifeline 文案应保持英文（**留给最终验收**）
- [ ] 5.4 手测验证：中文 UI 下已有 baby → 切英文 UI → lifeline 保持中文（**留给最终验收**）
- [ ] 5.5 前端可选：baby 列表 / 详情页增加 lang 小徽标（follow-up，非本 change 范围）

## 6. 四道 Gate 验证（四问答卷）

- [x] 6.1 **Gate 1**：所有 5 个新测试脚本（test_baby_state_lang / test_api_conceive_lang / test_phase_age_range_bilingual / test_world_snapshot_prompt_lang / test_lifeline_i18n_integration）全绿；现有 test_cradle_graph_emit / test_cradle_graph_backend_smoke / test_graph_emit 无回归
- [x] 6.2 **Gate 2 静态层**：`test_lifeline_i18n_integration` test_archive_state_json_roundtrip_preserves_lang 断言 state.json raw 字段含 `"lang": "en"` 持久化
- [x] 6.3 **Gate 3 静态层**：`test_lifeline_i18n_integration` test_en_phase_payload_has_no_chinese / test_en_world_snapshot_prompt_no_chinese_in_rules 用 `[一-鿿]` 正则断言英文 baby 事件 payload 和 prompt Rules 段无 CJK
- [x] 6.4 **Gate 4 反向断言**：`test_zh_phase_payload_is_chinese` / `test_zh_world_snapshot_prompt_chinese_rules` 断言中文 baby 行为零回归
- [ ] 6.5 **Gate 4 人工端到端**：启动后端 + 英文孕育 + 肉眼校验 lifeline 全英文（**留给最终验收**）

## 7. 收尾

- [x] 7.1 更新 `backend/cradle/CLAUDE.md` L2：state.py 说明增加 lang 运行时语言段落，phases.py 说明增加 age_range 双字段段落
- [x] 7.2 更新 `backend/womb/CLAUDE.md` L2：baby.py 说明增加 Baby.lang 字段段落
- [x] 7.3 跑 `openspec validate fix-lifeline-i18n` 通过
- [x] 7.4 4/4 artifacts complete；spec + design + tasks 齐全，实现与 spec 对齐（lang 字段、API 透传、phases 双字段、world prompt 分支、前端透传已全部验证）
- [ ] 7.5 准备 archive：等用户最终端到端确认后走 `/openspec-archive`

## 交付信息（三问回答 + 四 Gate）

**三问回答**：

- **主角**：双语（zh/en）用户——英文 UI 用户不应在 lifeline 看到中文（现象），baby 的语言在创建时锁定（本质），state.lang 是后端生成链路的唯一真源（哲学）
- **核心不变量**：baby.lang 创建后锁定 + lang 决定生成语言，UI 语言切换不改变已创建 baby 的语言
- **spec 元字段**：
  - 用到：`state.lang` / `Baby.lang` / `Phase.age_range_{zh,en}` / world prompt Rule 10 / `HTTPException(422)` 校验
  - 明确忽略：frontend/i18n.js 静态文案不动（Non-Goal），老 archive 不做运行时翻译（Non-Goal）

**四道 Gate 结果**：

- **Gate 1**：所有测试脚本全绿，5 个新脚本 + 3 个回归脚本通过
- **Gate 2**：state.json 含 `"lang": "en"` 字段；load_state 重载后 `.lang` 字段等价（脚本 test case [5]）
- **Gate 3**：lang="en" 下 `phase_start` payload 的 `age_range` / `age_range_en` 无 CJK；world prompt Rules/Output JSON 段无 CJK（脚本 [1] + [3]）
- **Gate 4 反向**：lang="zh" 下 `age_range == '0-1个月'`、world prompt 含 `MUST be in Chinese`（脚本 [2] + [4]）——中文 baby 行为零回归
- **Gate 4 人工**：留给用户最终端到端验收（启动后端 + 英文孕育 + 肉眼校验 lifeline 全英文）
