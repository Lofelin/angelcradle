# 任务清单：initiative-scene-library

## 1. 骨架 + schema

- [ ] 1.1 新建 `backend/scenes/` 目录 + `data/` 子目录
- [ ] 1.2 `schema.py`：`InitiativeScene` dataclass（含 `to_dict` / `from_dict` 防御）
- [ ] 1.3 `__init__.py`：`load_scenes_for_phase` / `pick_scene` / `count_scenes` / `all_scenes`
- [ ] 1.4 `CLAUDE.md` L2 文档
- [ ] 1.5 文件头 L3 头注

## 2. 产出 600+ 条场景 JSON（按配额见 design §3）

- [ ] 2.1 phase_00_neonatal.json（50）生理×45 + 情绪×5
- [ ] 2.2 phase_01_sensory_awakening.json（50）
- [ ] 2.3 phase_02_body_discovery.json（50）
- [ ] 2.4 phase_03_object_permanence.json（50）**stranger_anxiety 窗口**
- [ ] 2.5 phase_04_locomotion.json（50）**first_words 开启**
- [ ] 2.6 phase_05_first_word.json（50）
- [ ] 2.7 phase_06_language_explosion.json（50）**sentence**
- [ ] 2.8 phase_07_why_phase.json（50）**情绪风暴 + why**
- [ ] 2.9 phase_08_social_budding.json（50）**narrative**
- [ ] 2.10 phase_09_rule_understanding.json（50）**reasoning + boundary**
- [ ] 2.11 phase_10_abstract_beginning.json（50）
- [ ] 2.12 phase_11_independence.json（50）**independent**

## 3. rule_based_need 改造

- [ ] 3.1 替换 `scheduler/needs.py:190-246` 的手工 `triggers / vocalizations` 为 `pick_scene(phase)`
- [ ] 3.2 保留原有冷却/概率/压力逻辑
- [ ] 3.3 透传 `scene.default_tags` 到返回 dict 的 `cause_tags` 字段

## 4. LLM 路径 few-shot 注入

- [ ] 4.1 `cradle/mind.py:generate_heartbeat_evaluation` prompt 追加 `## Example Scenes for This Phase` 块
- [ ] 4.2 每次随机抽 3-5 条同 phase 场景（用 `pick_scene` 或 `load_scenes_for_phase` 采样）
- [ ] 4.3 保证 prompt 长度可控（每条 few-shot 约 100 tokens，5 条 ≤ 500 tokens）

## 5. 单测

- [ ] 5.1 `tests/test_scene_library.py`：5 个测试（见 design §7）
- [ ] 5.2 每阶段 ≥50 / trigger 合法 / expression_mode 合规 / id 唯一 / trigger 分布合理
- [ ] 5.3 `pick_scene` 轮转测试

## 6. 文档 + 验证

- [ ] 6.1 更新 `scheduler/CLAUDE.md` 说明 needs.py 变更
- [ ] 6.2 更新 `cradle/CLAUDE.md` 说明 mind.py 变更
- [ ] 6.3 端到端：启动 backend + 跑通一次 scheduler day_tick 触发 rule_based_need → 产出 phase 匹配场景
- [ ] 6.4 验证老 baby（`AC-20260417-14297` / `AC-20260417-34518`）启动无崩溃
- [ ] 6.5 验证：`AC-20260417-34518`（phase=8 narrative）下一次 rule_based_need 不再产出 `*Fussing*`，而是 narrative 风格

## 死罪清单

- [ ] ❌ 禁止在 scenes/data 以外的地方写死 vocabulary 数组（如原 `scheduler/needs.py:230` 的模式）
- [ ] ❌ 禁止某阶段场景数 < 50（CI 阻断）
- [ ] ❌ 禁止 scene.trigger 不在 TRIGGER_URGENCY 枚举
- [ ] ❌ 禁止 cry_only 阶段场景的 expression 含真实词汇
- [ ] ❌ 禁止 first_words 阶段场景的 expression 不含真实中文词
- [ ] ❌ 禁止 scene id 重复
