"""
Cradle: 摇篮——从出生到进入世界的成长模拟。

保姆照料日常，随机事件塑造个性，父母在关键时刻介入。
12 个阶段，从只能哭到独立表达。

[INPUT]: 依赖 womb/ 的 Baby 数据
[OUTPUT]: admit(), advance(), intervene() 三个核心函数
[POS]: 子宫和世界之间的桥梁
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from .identity import compile_identity, extract_innate_data, generate_constraints
from .state import BabyState, Identity, save_state, load_state, list_cradle_babies, append_event, load_events, append_interaction, load_interactions
from .nanny import (
    simulate_phase, simulate_phase_stream, resolve_critical_event,
    complete_phase, grow_stream,
)
from .phases import PHASES, WORLD_READINESS


def admit(baby_id: str) -> BabyState:
    """同步版 admit，内部消费生成器。"""
    state = None
    for step in admit_stream(baby_id):
        if step.get("event") == "admitted":
            state = step["_state"]
    if state is None:
        raise RuntimeError("admit_stream did not produce a final state")
    return state


def admit_stream(baby_id: str):
    """
    流式 admit：逐步 yield 进度事件。

    事件流：
    - {"event": "loading", ...}
    - {"event": "extracting", ...}    — 规则提取（毫秒级）
    - {"event": "compiling", ...}     — LLM 编译约束（慢）
    - {"event": "admitted", ...}      — 完成
    """
    from api import registry as birth_registry

    # 1. 加载出生数据
    baby_data = birth_registry.load(baby_id)
    if baby_data is None:
        raise ValueError(f"Baby '{baby_id}' not found in birth registry")

    if not baby_data.get("alive", True):
        raise ValueError(f"Baby '{baby_id}' was stillborn and cannot be admitted to the cradle")

    existing = load_state(baby_id)
    if existing is not None:
        raise ValueError(f"Baby '{baby_id}' is already in the cradle")

    species = baby_data.get("species", "human")
    yield {"event": "loading", "baby_id": baby_id, "species": species}

    # 2. 规则提取（无 LLM，毫秒级）
    innate = extract_innate_data(baby_data)
    yield {
        "event": "extracting",
        "sensory_profile": innate["sensory"].to_dict(),
        "arousal_baseline": innate["arousal"],
        "temperament": innate["temperament"][:100],
        "reflex_count": len(innate["reflexes"]),
        "instinct_count": len(innate["instincts"]),
    }

    # 3. LLM 编译约束（慢步骤 + 计时心跳）
    yield {"event": "compiling", "message": "Compiling behavioral constraints..."}

    from concurrent.futures import ThreadPoolExecutor
    import time as _time
    _compile_executor = ThreadPoolExecutor(max_workers=1)
    _compile_future = _compile_executor.submit(generate_constraints, innate, species)
    _compile_elapsed = 0
    constraints = None
    try:
        while not _compile_future.done():
            _time.sleep(1)
            _compile_elapsed += 1
            yield {"event": "compiling", "elapsed": _compile_elapsed}
        constraints = _compile_future.result()
    except Exception:
        constraints = []
    finally:
        _compile_executor.shutdown(wait=False)

    yield {
        "event": "constraints_ready",
        "constraints": constraints,
        "count": len(constraints),
    }

    # 4. 组装身份 + 创建状态
    identity = Identity(
        sensory_profile=innate["sensory"],
        arousal_baseline=innate["arousal"],
        reflex_patterns=innate["reflexes"],
        instinct_loops=innate["instincts"],
        temperament=innate["temperament"],
        tendencies=innate["tendencies"],
        defects=innate["defects"],
        constraints=constraints,
    )

    state = BabyState(
        baby_id=baby_id,
        species=species,
        identity=identity,
        current_phase=0,
        age_days=0,
        capabilities=[],
        expression_mode="cry_only",
    )
    save_state(state)

    yield {
        "event": "admitted",
        "baby_id": state.baby_id,
        "species": state.species,
        "identity": identity.to_dict(),
        "phase": PHASES[0].display_name,
        "_state": state,  # 内部用，SSE 端点会剔除
    }


def check_world_readiness(baby_id: str) -> dict:
    """检查婴儿是否准备好进入世界。"""
    state = load_state(baby_id)
    if state is None:
        raise ValueError(f"Baby '{baby_id}' not found in cradle")

    result = {"ready": True, "hard": {}, "soft": {}}

    # 检查硬性条件
    for key, desc in WORLD_READINESS["hard"].items():
        # 简化检查：基于能力列表
        met = _check_readiness_criterion(state, key)
        result["hard"][key] = {"description": desc, "met": met}
        if not met:
            result["ready"] = False

    # 检查软性条件
    for key, desc in WORLD_READINESS["soft"].items():
        met = _check_readiness_criterion(state, key)
        result["soft"][key] = {"description": desc, "met": met}

    state.world_readiness = result
    save_state(state)
    return result


def _check_readiness_criterion(state: BabyState, criterion: str) -> bool:
    """检查单个就绪条件。"""
    capability_map = {
        "language": ["full_sentences"],
        "self_concept": ["self_recognition"],
        "theory_of_mind": ["basic_empathy"],
        "emotional_regulation": ["complex_emotion"],
        "curiosity": ["why_questions"],
        "social_skill": ["peer_awareness"],
        "resilience": ["boundary_testing"],
        "independence": ["independent_opinion"],
    }
    required = capability_map.get(criterion, [])
    return all(cap in state.capabilities for cap in required)
