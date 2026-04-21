# 技术设计：initiative-scene-library

## 1. 目录结构

```
backend/
├── scenes/                                ← 新增
│   ├── __init__.py                        加载模块（懒加载 + 缓存 + pick_scene）
│   ├── CLAUDE.md                          L2 文档
│   ├── schema.py                          InitiativeScene dataclass
│   ├── data/                              纯数据（JSON）
│   │   ├── phase_00_neonatal.json         ≥50 条
│   │   ├── phase_01_sensory_awakening.json ≥50
│   │   ├── phase_02_body_discovery.json   ≥50
│   │   ├── phase_03_object_permanence.json ≥50
│   │   ├── phase_04_locomotion.json       ≥50
│   │   ├── phase_05_first_word.json       ≥50
│   │   ├── phase_06_language_explosion.json ≥50
│   │   ├── phase_07_why_phase.json        ≥50
│   │   ├── phase_08_social_budding.json   ≥50
│   │   ├── phase_09_rule_understanding.json ≥50
│   │   ├── phase_10_abstract_beginning.json ≥50
│   │   └── phase_11_independence.json     ≥50
├── scheduler/needs.py                     改造：rule_based_need 从场景库选
├── cradle/mind.py                         改造：generate_heartbeat_evaluation few-shot
└── tests/test_scene_library.py            覆盖率 + 合法性验证
```

## 2. 数据模型（JSON Schema）

```json
{
  "id": "phase3_lonely_stranger_anxiety_01",
  "trigger": "lonely",
  "context": "妈妈走到门外看不见了",
  "expression": "*Eyes widen and fix on the doorway, lower lip trembles, fists clench the blanket*",
  "signal": "Frozen body, breath held, eyes tracking the empty doorway",
  "facial": "Eyebrows knit, lip quivering",
  "body": "Shoulders tense, both hands gripping blanket edge",
  "intent": "寻找妈妈、希望她回来",
  "parent_hint": "Separation anxiety — Baby 需要妈妈回到视线内",
  "default_tags": ["phase:3", "arousal:sensitive", "stranger_anxiety"]
}
```

### InitiativeScene dataclass（scenes/schema.py）

```python
@dataclass
class InitiativeScene:
    id: str                          # 唯一，形如 "phase{N}_{trigger}_{slug}_NN"
    trigger: str                     # 必在 initiative_needs.TRIGGER_URGENCY 枚举
    context: str                     # 情境描述（场景发生的前置条件）
    expression: str                  # 主动行为的表达（必须符合该 phase 的 expression_mode）
    signal: str                      # 身体信号（可观测行为）
    facial: str = ""                 # 面部
    body: str = ""                   # 躯体
    intent: str                      # 婴儿内心意图（中文）
    parent_hint: str                 # 给家长的提示（用于前端展示）
    default_tags: list[str] = []     # 默认 cause_tags（phase:N + 额外）
```

## 3. 12 阶段 trigger 分布矩阵（D2）

每阶段 50 条的 trigger 配额，按 WHO 婴幼儿发育里程碑 + 本项目 `phases.py` 的 capabilities 反推：

| phase | name | expr_mode | 生理 | 情绪 | 社交/探索 | autonomy | 说明 |
|---|---|---|---|---|---|---|---|
| 0 | neonatal | cry_only | **45** | **5** | 0 | 0 | 纯生理主导：hunger×12 sleepy×10 wet/soiled×10 gas/hiccup/too_cold/too_hot×13 + pain×5 |
| 1 | sensory_awakening | coo_and_gaze | 35 | **10** | **5** | 0 | + fear×5 overstimulated×5 + curious×3 lonely×2 |
| 2 | body_discovery | babble_and_reach | 25 | 10 | **15** | 0 | + play×6 curious×6 share×3 |
| 3 | object_permanence | gesture_and_point | 18 | **12** | 15 | 5 | **stranger_anxiety / separation** 窗口期 → fear/lonely 峰值 |
| 4 | locomotion | first_words | 13 | 10 | **22** | **5** | 能爬能指 → curious×10 play×8 + autonomy×5 |
| 5 | first_word | two_word | 10 | 8 | 22 | **10** | 首个 autonomy 峰值（工具使用）|
| 6 | language_explosion | sentence | 7 | 10 | 20 | **13** | pretend_play 开启 → share/secret |
| 7 | why_phase | sentence | 5 | **15** | **18** | 12 | 情绪风暴 + 无尽为什么 → curious/bored/overstimulated |
| 8 | social_budding | narrative | 3 | 12 | **22** | 13 | peer_awareness → share/lonely |
| 9 | rule_understanding | reasoning | 2 | 10 | 18 | **20** | boundary_testing 峰值 → autonomy/boundary/secret |
| 10 | abstract_beginning | reasoning | 2 | 8 | 22 | 18 | hypothetical_thinking → curious 大量 |
| 11 | independence | independent | 2 | 8 | 18 | **22** | 独立巅峰：autonomy + share + secret |

**总计验证**：每列横向总和 = 50；trigger 大类分布随阶段单调演化。

## 4. 表达校验规则（对照 EXPRESSION_MODES）

```
cry_only (0)           → 禁止字母成词，允许 *asterisk actions* + onomatopoeia
coo_and_gaze (1)       → 禁止音节（ba-da），允许元音 (ah, oo, mm) + *actions*
babble_and_reach (2)   → 音节可以重复 (ba-da, ma-ma)，但不能是真实词
gesture_and_point (3)  → 和 2 类似 + 更明确的指点描述
first_words (4)        → 必须含真实中文词（妈妈/爸爸/要/抱抱/水...），1 词为主
two_word (5)           → 2-3 词中文短语（妈妈抱 / 要喝水）
sentence (6-7)         → 完整英文/中文短句，5-10 词，可有 why
narrative (8)          → 2-4 句英文/中文，"then ... and then"
reasoning (9-10)       → 含 because/so/if，逻辑有瑕疵
independent (11)       → 几段表达立场，带简单理由
```

复用 `cradle/mind.py:_validate_expression_output` 做单测断言。

## 5. 加载模块 API

```python
# backend/scenes/__init__.py
from .schema import InitiativeScene

def load_scenes_for_phase(phase: int) -> list[InitiativeScene]: ...
def pick_scene(
    phase: int,
    trigger: str | None = None,            # 若指定，仅从该 trigger 候选选
    exclude_ids: set[str] = frozenset(),   # 排除最近使用过的，避免重复
    rng: random.Random | None = None,
) -> InitiativeScene | None: ...
def count_scenes(phase: int) -> int: ...
def all_scenes() -> dict[int, list[InitiativeScene]]: ...  # 单测用
```

缓存策略：进程级单例，首次调用 `load_scenes_for_phase(N)` 时加载 `data/phase_{N:02d}_*.json` 并解析；后续命中返回 list 引用。

## 6. 接入点改造

### 6.1 `scheduler/needs.py:rule_based_need`（完整替换）

```python
def rule_based_need(state, day: int) -> dict | None:
    # ... 原有冷却/概率逻辑保持不变 ...
    from scenes import pick_scene
    from initiative_needs import TRIGGER_URGENCY, URGENCY_TIMEOUT

    phase = state.current_phase
    # trigger 候选限缩：从场景库里**当前阶段的** trigger 分布自然约束
    scene = pick_scene(phase=phase)
    if scene is None:
        return None

    urgency = TRIGGER_URGENCY.get(scene.trigger, NeedUrgency.SOCIAL)
    return {
        "trigger": scene.trigger,
        "urgency": urgency,
        "timeout_sec": URGENCY_TIMEOUT[urgency],
        "expression": scene.expression,
        "signal": scene.signal,
        "facial": scene.facial,
        "body": scene.body,
        "behavior_type": _behavior_type_from_trigger(scene.trigger, phase),
        "intent_id": f"rule-{day}-{scene.id}",
        "parent_hint": scene.parent_hint,
        # 记忆 tags 透传
        "cause_tags": list(scene.default_tags),
    }
```

废弃写死的 `vocalizations` 3 档 if/else。

### 6.2 `cradle/mind.py:generate_heartbeat_evaluation`（prompt 注入）

在已有 prompt 里追加：

```
## Example Scenes for This Phase (few-shot)
- Trigger: {s1.trigger} — Context: {s1.context}
  Expression: {s1.expression}
  Intent: {s1.intent}
...(3-5 条同 phase 随机抽取)
```

让 LLM 看到**当前阶段应有的表达风格**，降低违规率。

### 6.3 `scheduler/needs.py:handle_need` → 自动写 LifeMoment

`rule_based_need` 或 LLM 返回 need 后，在 handle_need 内（或上游统一点）：

```python
from memory import record_moment
record_moment(
    state, baby_id,
    actor="self",
    trigger=need["trigger"],
    action=need["expression"],
    intensity=_intensity_from_urgency(urgency),
    cause_tags=need.get("cause_tags", []) + [f"phase:{state.current_phase}"],
    is_first=(need["trigger"] not in state.triggered_events),
    outcome="pending",
)
```

实际上 `post_baby_message` 已经做了这件事（PR-3 改造）。这里再确认通路通即可。

## 7. 单测矩阵（tests/test_scene_library.py）

```python
def test_each_phase_has_at_least_50_scenes():
    for phase in range(12):
        assert count_scenes(phase) >= 50

def test_all_triggers_in_enum():
    from initiative_needs import TRIGGER_URGENCY
    for phase, scenes in all_scenes().items():
        for s in scenes:
            assert s.trigger in TRIGGER_URGENCY

def test_expression_mode_compliance():
    """每条场景的 expression 必须符合对应 phase 的 expression_mode"""
    from cradle.phases import PHASES
    from cradle.mind import _validate_expression_output
    for phase, scenes in all_scenes().items():
        expr_mode = PHASES[phase].expression_mode
        for s in scenes:
            result = _validate_expression_output(s.expression, expr_mode)
            # result is None = 合法；非 None 是修正版本
            if result is not None and result != s.expression:
                raise AssertionError(
                    f"{s.id} expression 违反 {expr_mode}: {s.expression!r} → {result!r}"
                )

def test_ids_unique_across_phases():
    seen = set()
    for phase, scenes in all_scenes().items():
        for s in scenes:
            assert s.id not in seen, f"重复 id: {s.id}"
            seen.add(s.id)

def test_trigger_distribution_reasonable():
    """phase=0 不能有 autonomy，phase=11 不能有 teething"""
    s0 = all_scenes()[0]
    assert not any(s.trigger == "autonomy" for s in s0)
    s11 = all_scenes()[11]
    assert not any(s.trigger == "teething" for s in s11)

def test_pick_scene_rotates():
    """pick_scene 配合 exclude_ids 不会无限重复同一条"""
    ...
```

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| JSON 人工写 600 条有 typo | 单测强校验（trigger 枚举 / expression_mode 合法 / id 唯一） |
| 场景覆盖不到某些 trigger | 矩阵预先定义配额（见 §3），按配额产出 |
| 重复场景只是换了标点 | context 字段在同阶段内做 Jaccard 相似度检查（CI 可选） |
| 单阶段 JSON 文件过大（50 条 × ~400 字）| 按阶段分文件，单文件约 20KB，可读可编辑 |
| 老 baby 的 `triggered_events` 与新 scene id 不一致 | `is_first` 判定用 trigger 而非 scene_id，复用 old set 逻辑 |
| 加载性能 | 懒加载 + 单例缓存，首次加载 12 文件 < 50ms |

## 9. 分形同构检查

- **L1**：`backend/` 无 L1 CLAUDE.md（现状）
- **L2**：`backend/scenes/CLAUDE.md` 新建，含成员清单 + 对外 API + trigger 分布矩阵链接
- **L3**：`scenes/schema.py` / `scenes/__init__.py` 头部 `[INPUT]/[OUTPUT]/[POS]/[PROTOCOL]`
- 更新 `scheduler/CLAUDE.md` needs.py 条目，说明 rule_based_need 改造
- 更新 `cradle/CLAUDE.md` mind.py 条目，说明 generate_heartbeat_evaluation few-shot
