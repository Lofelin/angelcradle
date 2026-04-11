# 技术设计：自驱动生命系统

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────┐
│                   EventScheduler（常驻进程）                │
│                                                          │
│  全局优先级队列（按模拟时间排序）                              │
│  ┌──────────────────────────────────────────────────┐    │
│  │ (baby_A, sim_07:00, wake_up)                     │    │
│  │ (baby_B, sim_07:30, wake_up)                     │    │
│  │ (baby_A, sim_08:30, school_class)                │    │
│  │ (baby_C, sim_09:00, home_play)                   │    │
│  └──────────────────────────────────────────────────┘    │
│                         │                                │
│                    取队首事件                              │
│                         │                                │
│           ┌─────────────┴─────────────┐                  │
│           ▼                           ▼                  │
│    日常事件（规则引擎）          有"事"事件（LLM）            │
│    状态微调，不调 LLM          生成时段总结 + 记忆            │
│           │                           │                  │
│           └─────────────┬─────────────┘                  │
│                         ▼                                │
│                  生成后续事件                               │
│              ┌──────────┴──────────┐                     │
│              ▼                    ▼                       │
│        下一个日程事件         涌现事件（掷骰）               │
│        （确定的）            （随机的，可能没有）             │
│              │                    │                       │
│              └──────┬─────────────┘                       │
│                     ▼                                    │
│               插回优先级队列                                │
│                     │                                    │
│                     ▼                                    │
│             写入事件流 + 推 SSE                             │
└──────────────────────────────────────────────────────────┘
```

## 2. 模块结构

```
backend/
├── scheduler.py              ← DES 调度器（常驻进程，管理所有 Agent 生命线）
├── world.py                  ← 世界层（日程模板 + 事件路由 + 涌现事件掷骰）
├── events/                   ← 共享事件系统（从 cradle/events.py 拆出）
│   ├── __init__.py           ← Event 数据模型 + 事件路由函数
│   ├── definitions.py        ← 所有事件定义（含时间窗口 + life context）
│   └── modifiers.py          ← 权重调制器（身份亲和度 + 阶段修正 + 压力修正）
├── heartbeat.py              ← 现有心跳引擎（不变）
├── cradle/
│   ├── events.py             ← 改为 thin wrapper，导入 events/ 并补充摇篮专属逻辑
│   └── ...
└── api/
    └── cradle.py             ← heartbeat/stream 对接调度器
```

## 3. 共享事件系统

### 3.1 Event 数据模型扩展

```python
@dataclass
class Event:
    name: str
    category: str                    # daily / environment / critical
    display_name: str
    description: str
    sensory_channels: list[str]
    intensity: float                 # 0-1
    requires_parent: bool
    phase_range: tuple[int, int]     # 阶段范围（inclusive）

    # ── 新增字段 ──
    hour_range: tuple[int, int]      # 时间窗口，如 (8, 16) 表示 8:00-16:00
    requires_tags: list[str]         # 前置条件标签，如 ["enrolled_school"]
    excludes_tags: list[str]         # 排斥标签，如 ["home_schooled"]
    duration_hours: float            # 事件持续时长（模拟小时），影响下一事件间隔
    generates_next: str | None       # 固定后续事件名（日程链），如 wake_up → breakfast

    weight: float = 1.0
    parent_choices: list[dict] = field(default_factory=list)
```

### 3.2 事件路由

```python
def route_events(
    sim_hour: float,               # 当前模拟时间（小时，0-24）
    phase_index: int,              # 当前阶段
    life_tags: set[str],           # Agent 的生活上下文标签
    identity=None,                 # 先天身份（权重调制）
    state=None,                    # 当前状态（压力等修正）
    category: str = "all",         # 过滤类别
) -> list[Event]:
    """
    根据时间 + 阶段 + 标签过滤可用事件。
    返回符合条件的事件列表（未加权选择）。
    """
```

### 3.3 向后兼容

`cradle/events.py` 改为 thin wrapper：
- `DAILY_EVENTS`, `ENVIRONMENT_EVENTS`, `CRITICAL_EVENTS` 从 `events/definitions.py` 导入
- `roll_events()` 保持原签名不变，内部调用 `route_events()` + 加权选择
- 现有的 `nanny.py` 调用完全不受影响

## 4. Agent 生活上下文（Life Context）

### 4.1 BabyState 扩展

```python
@dataclass
class BabyState:
    # ... 现有字段 ...

    # ── 新增 ──
    life_tags: set[str] = field(default_factory=set)
    last_active_ts: float = 0.0        # 上次活跃的 Unix 时间戳
    sim_time: float = 0.0              # 当前模拟时间（自出生以来的模拟小时数）
    time_scale: str = "normal"         # slow / normal / fast
```

### 4.2 标签来源

| 来源 | 示例 | 触发时机 |
|------|------|---------|
| 阶段自动 | `enrolled_school`（学龄期） | 进入阶段 9+ 时自动添加 |
| 阶段自动 | `can_walk`（运动爆发期后） | 解锁 walk_first_steps 能力时 |
| 父母决策 | `has_pet` | 关键事件 pet_encounter 中父母选择养宠物 |
| 事件后果 | `lives_suburban` | 经历 moving_house 事件后 |
| 移除 | 移除 `sleep_regression_active` | 睡眠回归期结束时 |

### 4.3 时间比例

| 模式 | 映射 | `time_scale` |
|------|------|-------------|
| 慢养 | 1 现实小时 = 1 模拟天 | `"slow"` |
| 正常 | 1 现实小时 = 7 模拟天 | `"normal"` |
| 快养 | 1 现实小时 = 30 模拟天 | `"fast"` |

## 5. 世界层（World）

### 5.1 日程模板

根据阶段和 life_tags 生成每日日程骨架：

```python
SCHEDULE_TEMPLATES = {
    # 新生儿（phase 0-1）：吃睡循环
    "infant": [
        ("wake_up",    6.0, 1.0),   # (事件名, 模拟小时, 持续小时)
        ("feeding",    7.0, 0.5),
        ("nap",        9.0, 1.5),
        ("feeding",   12.0, 0.5),
        ("nap",       13.0, 1.5),
        ("feeding",   17.0, 0.5),
        ("bath",      19.0, 0.5),
        ("sleep",     20.0, 10.0),
    ],
    # 学龄前（phase 5-8, 无 enrolled_school）：家庭活动
    "preschool_home": [
        ("wake_up",    7.0, 0.5),
        ("breakfast",  7.5, 0.5),
        ("morning_play", 9.0, 2.0),
        ("lunch",     12.0, 0.5),
        ("nap",       13.0, 1.0),
        ("afternoon_activity", 15.0, 2.0),
        ("dinner",    18.0, 0.5),
        ("family_time", 19.0, 1.0),
        ("sleep",     20.5, 10.5),
    ],
    # 学龄（phase 9+, enrolled_school）：上学作息
    "school_age": [
        ("wake_up",    6.5, 0.5),
        ("breakfast",  7.0, 0.5),
        ("school_morning", 8.5, 3.5),
        ("lunch",     12.0, 0.5),
        ("school_afternoon", 13.0, 2.5),
        ("after_school", 16.0, 2.0),
        ("dinner",    18.0, 0.5),
        ("homework",  19.0, 1.0),
        ("family_time", 20.0, 0.5),
        ("sleep",     21.0, 9.5),
    ],
}

def select_template(phase: int, life_tags: set[str]) -> str:
    """根据阶段和标签选择日程模板。"""
```

### 5.2 涌现事件

每个日程事件处理完后，掷骰决定是否插入涌现事件：

```python
def roll_emergent_event(
    current_event: Event,          # 刚处理完的事件
    state: BabyState,              # 当前状态
    sim_hour: float,               # 当前模拟时间
) -> Event | None:
    """
    基于当前情境掷骰，可能产生涌现事件。

    规则：
    1. 从 route_events() 获取当前时间+标签下的候选事件
    2. 排除 daily 类（日程已覆盖），只取 environment/critical
    3. 加权随机，概率约 20-30%（可被压力/情绪调制）
    4. 命中 → 返回事件；未命中 → 返回 None
    """
```

### 5.3 事件处理分层

```python
def process_event(event: Event, state: BabyState) -> dict:
    """
    处理一个事件，返回结果。

    日常事件（daily）→ 规则引擎：
      - 状态微调（压力/情绪/饱腹感等）
      - 不调 LLM
      - 返回 {"type": "routine", "changes": {...}}

    有"事"事件（environment/critical）→ LLM：
      - 生成时段总结（发生了什么、宝宝怎么反应）
      - 产出 Memory
      - 返回 {"type": "story", "summary": "...", "memory": {...}, "changes": {...}}
    """
```

## 6. DES 调度器

### 6.1 核心数据结构

```python
@dataclass(order=True)
class ScheduledEvent:
    sim_time: float                    # 排序键：模拟时间（小时）
    baby_id: str = field(compare=False)
    event_name: str = field(compare=False)
    event: Event | None = field(compare=False, default=None)

class EventScheduler:
    def __init__(self):
        self.queue: list[ScheduledEvent] = []   # heapq 优先级队列
        self.agents: dict[str, BabyState] = {}  # 已注册 Agent
        self.running: bool = False
        self.llm_semaphore = asyncio.Semaphore(3)  # LLM 并发限制
        self.sse_channels: dict[str, list] = {}    # baby_id → SSE 订阅者列表
```

### 6.2 Agent 注册

```python
def register_agent(self, baby_id: str):
    """
    注册 Agent 到调度器。
    1. 加载 BabyState
    2. 根据当前 sim_time 和日程模板生成第一批事件
    3. 插入优先级队列
    """
```

### 6.3 主循环

```python
async def run(self):
    """
    DES 主循环。永不停止。

    while True:
        1. 取队首（最早的事件）
        2. 推进该 Agent 的模拟时间到事件时间
        3. 处理事件：
           a. 日常 → 规则引擎 → 状态更新
           b. 有事 → LLM（受 semaphore 限流）→ 时段总结 + 状态更新
        4. 生成后续事件：
           a. generates_next → 插入日程下一事件
           b. roll_emergent_event() → 可能插入涌现事件
        5. 如果当日日程结束（sleep 事件），生成次日日程
        6. 写入事件流（append_event）
        7. 推 SSE（如果有订阅者）
        8. 如果队列为空或最早事件在未来，sleep 等待
    """
```

### 6.4 现实时间同步

```python
def _real_to_sim(self, baby_id: str, real_seconds: float) -> float:
    """将现实时间差转换为模拟时间差（小时）。"""
    scale = {"slow": 1/3600, "normal": 7/3600, "fast": 30/3600}
    # slow: 1 real hour = 1 sim day (24 sim hours)
    # normal: 1 real hour = 7 sim days (168 sim hours)
    # fast: 1 real hour = 30 sim days (720 sim hours)
    rate = scale.get(self.agents[baby_id].time_scale, 7/3600)
    return real_seconds * rate * 24  # 返回模拟小时数
```

调度器不按现实时间 tick，而是：
- 计算下一个事件的模拟时间
- 根据 time_scale 算出需要等待的现实时间
- `asyncio.sleep(等待时间)` 或被新事件唤醒

### 6.5 追赶模式

Agent 注册时（或 SSE 重连时），如果 `last_active_ts` 远在过去：

```python
async def catchup(self, baby_id: str):
    """
    追赶模式：快速处理离线期间的事件。

    1. 计算离线期间应推进的模拟时间
    2. 批量生成并处理日程事件（规则引擎，不调 LLM）
    3. 对涌现事件（environment/critical）暂存
    4. 批量调 LLM 处理暂存的涌现事件（限并发）
    5. 生成追赶总结推送给前端
    6. 恢复正常调度
    """
```

追赶期间日常事件用规则引擎快速跑，只有"有事的"事件才调 LLM。

## 7. 心跳 SSE 与调度器对接

### 7.1 SSE 端点改造

```python
@router.get("/{baby_id}/heartbeat/stream")
def heartbeat_stream(baby_id: str):
    """
    统一生命流 SSE。

    合并两类事件：
    1. 调度器产出的自主生命事件（autonomous_event / autonomous_routine）
    2. 心跳主动行为（heartbeat_initiative / heartbeat_ignored）

    前端通过同一个 SSE 连接接收所有生命信号。
    """
    def event_generator():
        # 注册 SSE 订阅
        channel = scheduler.subscribe(baby_id)
        try:
            while True:
                event = channel.get(timeout=SSE_HEARTBEAT_INTERVAL)
                if event:
                    yield _sse(event)
                else:
                    yield _sse_heartbeat()  # 保活
        finally:
            scheduler.unsubscribe(baby_id, channel)
```

### 7.2 SSE 事件类型

| 事件 | 来源 | 说明 |
|------|------|------|
| `autonomous_routine` | 调度器/规则引擎 | 日常活动（吃饭/睡觉），简短状态更新 |
| `autonomous_event` | 调度器/LLM | 有"事"发生，含时段总结和记忆 |
| `autonomous_catchup` | 调度器/追赶 | 离线期间的经历摘要 |
| `heartbeat_initiative` | 心跳引擎 | 宝宝主动找人（现有） |
| `heartbeat_ignored` | 心跳引擎 | 被忽略反应（现有） |

## 8. 调度器启动与生命周期

### 8.1 启动方式

```python
# main.py 或 FastAPI lifespan
scheduler = EventScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：加载所有摇篮中的宝宝，注册到调度器
    for baby in list_cradle_babies():
        scheduler.register_agent(baby["baby_id"])
    # 后台运行调度器
    task = asyncio.create_task(scheduler.run())
    yield
    # 关闭时：停止调度器
    scheduler.running = False
    task.cancel()
```

### 8.2 持久化

调度器状态通过 `BabyState.sim_time` 和 `BabyState.last_active_ts` 持久化。
进程重启时，从持久化状态恢复，通过追赶模式补跑缺失的事件。

## 9. 心跳集成

心跳评估融入调度器的事件循环：

```python
# 在每个有"事"事件处理后，额外做一次心跳评估
if event.category in ("environment", "critical"):
    heartbeat_result = evaluate_heartbeat(state, provider, state.initiative, ...)
    if heartbeat_result.get("initiative"):
        push_sse(baby_id, {"event": "heartbeat_initiative", ...})
```

心跳不再独立定时，而是**事件驱动**——有事发生后才考虑"要不要找人"。

## 10. 向后兼容

| 现有功能 | 影响 | 处理方式 |
|---------|------|---------|
| `cradle/events.py` | 事件定义迁移到 `events/` | thin wrapper 保持原 API |
| `roll_events()` | 签名不变 | 内部改为调用 `route_events()` |
| `nanny.py` simulate_phase | 不变 | 仍用于 grow_stream 手动推进阶段 |
| `heartbeat.py` | 不变 | 调度器复用其 `evaluate_heartbeat()` |
| `api/cradle.py` heartbeat/stream | 改造 | 从独立 LLM 循环改为订阅调度器 |
| 前端 SSE 处理 | 新增事件类型 | 添加 reducer case + renderLog |
