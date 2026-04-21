# scenes/
> L2 | 父级: /backend/ (目前无 L1 CLAUDE.md)

主动行为场景库：12 阶段各 ≥ 50 条，共 603 条 `InitiativeScene`。严格按发育生物学 + 对应 `expression_mode` 产出。
完整设计见 `../specs/initiative-scene-library/`。

## 成员清单

schema.py: `InitiativeScene` dataclass —— id / trigger / context / expression / signal / facial / body / intent / parent_hint / default_tags。trigger 必在 `initiative_needs.TRIGGER_URGENCY` 枚举，expression 必须符合对应 phase 的 `cradle.phases.EXPRESSION_MODES`。

__init__.py: 加载门面 —— `load_scenes_for_phase(phase)` 懒加载 + 单例缓存；`pick_scene(phase, trigger=?, exclude_ids=?)` 加权随机选（避免重复）；`count_scenes` / `all_scenes` / `reset_cache` 供测试。

data/: 12 个阶段 JSON 数据文件
- phase_00_neonatal.json        50 条（cry_only，纯生理 + 轻度情绪）
- phase_01_sensory_awakening.json 50（coo_and_gaze，追视追声 + stranger-warn 前兆）
- phase_02_body_discovery.json  53（babble_and_reach，抓握/翻身/首个 curious）
- phase_03_object_permanence.json 50（gesture_and_point，**stranger_anxiety 峰值**）
- phase_04_locomotion.json      50（**first_words** 关键里程碑，爬行 + 首词）
- phase_05_first_word.json      50（two_word，走+工具使用）
- phase_06_language_explosion.json 50（sentence，自我识别+假装游戏）
- phase_07_why_phase.json       50（sentence，无尽为什么+情绪风暴）
- phase_08_social_budding.json  50（narrative，同伴+道德萌芽）
- phase_09_rule_understanding.json 50（reasoning，规则+autonomy 峰值）
- phase_10_abstract_beginning.json 50（reasoning，类比+时间概念+假设）
- phase_11_independence.json    50（independent，独立意见+辩论）

## 对外暴露

```python
from scenes import (
    InitiativeScene,
    load_scenes_for_phase, count_scenes, all_scenes,
    pick_scene, reset_cache,
)
```

## 依赖关系

- `initiative_needs.TRIGGER_URGENCY`：trigger 枚举源（校验用）
- `cradle.phases.EXPRESSION_MODES`：表达模式校验源
- `cradle.mind._validate_expression_output`：测试环境的合法性断言
- **无**外部 pip 依赖（纯 JSON + stdlib）

## 数据流

```
写场景（人工）:
  手工编辑 data/phase_NN_*.json
    → 单测 tests/test_scene_library.py 校验
    → CI 阻断任何违规

读场景（业务代码）:
  scheduler/needs.py:rule_based_need
    → pick_scene(phase=state.current_phase, trigger=?)
    → 返回 InitiativeScene
    → 透传 expression / signal / default_tags 到 baby_need 事件

  cradle/mind.py:generate_heartbeat_evaluation
    → load_scenes_for_phase 随机 sample 3-4 条
    → 作为 few-shot 注入 LLM prompt
    → 降低 LLM phase 违规率
```

## 验证（全部通过 2026-04-17）

- 总 603 条 / 每阶段 ≥ 50 ✓
- 所有 trigger ∈ TRIGGER_URGENCY（19 枚举）✓
- 所有 expression 通过对应 expression_mode 静态校验 ✓
- phase 0 无 autonomy / phase 11 无 teething（发育合理性）✓
- id 全局唯一 ✓
- pick_scene 轮转测试通过 ✓

## 非目标

- 不包含多模态（图片/音频）
- 不做文化/地域差异（所有 baby 共享）
- 不做性别差异

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
