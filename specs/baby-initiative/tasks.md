# Plan: baby-initiative (Heartbeat Mode - Cross-Module)

## Scope

**Current implementation: cradle stage only** (world module does not exist yet).
Architecture is designed for cross-module extensibility -- tasks marked `[GENERIC]` are module-agnostic, `[CRADLE]` are cradle-specific. When world module is added, only new `[WORLD]` tasks are needed; no `[GENERIC]` tasks require changes.

## Tasks

- [ ] 1. `[GENERIC]` Heartbeat Engine Core (heartbeat.py -- new top-level file)
  - [ ] 1.1 Create `heartbeat.py` at project root with L3 header
  - [ ] 1.2 Implement `InitiativeState` dataclass with fields: `last_initiative_ts`, `last_interact_ts`, `pending_initiative_id`, `pending_initiative_ts`, `pending_initiative_type`, `pending_behavior_type`, `consecutive_ignores`, `total_initiatives`, `total_responded`, `total_ignored`, plus `to_dict()` and `from_dict()`
  - [ ] 1.3 Implement `BehaviorSpace` dataclass with `verbal`, `physical`, `avoidance` lists and `to_prompt_section()` method
  - [ ] 1.4 Define `MonologueProvider` Protocol class with methods: `build_inner_monologue`, `get_behavior_space`, `get_expression_mode`, `get_expression_constraints`, `get_attachment_style`, `get_caregivers`, `get_stress_state`, `save_state`
  - [ ] 1.5 Implement `frequency_gate(initiative_state: InitiativeState) -> bool`: hard minimum interval (2 min) + post-interact cooldown (60s)
  - [ ] 1.6 Implement `_check_and_process_ignore(state, provider, initiative_state, now) -> dict | None`: detect pending initiative timeout (5 min), update responsiveness via provider, escalation on 3+ ignores via provider
  - [ ] 1.7 Implement `evaluate_heartbeat(state, provider, initiative_state) -> dict | None`: orchestrate ignore check + frequency gate + provider.build_inner_monologue + provider.get_behavior_space + LLM call + fallback

- [ ] 2. `[CRADLE]` Data Model Extension (cradle/state.py)
  - [ ] 2.1 Import `InitiativeState` from `heartbeat.py`
  - [ ] 2.2 Add `initiative: InitiativeState` field to `BabyState` (default factory)
  - [ ] 2.3 Update `BabyState.to_dict()`: include `initiative.to_dict()`
  - [ ] 2.4 Update `BabyState.from_dict()`: use `.get("initiative", {})` for backward compatibility

- [x] 3. `[CRADLE]` Cradle Monologue Provider (cradle/heartbeat_provider.py -- new file)
  - [x] 3.1 Create `cradle/heartbeat_provider.py` with L3 header
  - [x] 3.2 Define `CRADLE_BEHAVIORS_BY_PHASE` dict: behavior space per phase range (0-1, 2-3, 4-5, 6-7, 8-9, 10-11), including avoidance behaviors expanding with age
  - [x] 3.3 Implement `CradleMonologueProvider` class:
    - [x] 3.3.1 `build_inner_monologue(state: BabyState) -> str`: construct inner state from physiological signals, recent memories, emotional state, interaction timing, expression constraints, capabilities, avoidance posture
    - [x] 3.3.2 `get_behavior_space(state: BabyState) -> BehaviorSpace`: lookup from `CRADLE_BEHAVIORS_BY_PHASE` by `current_phase`
    - [x] 3.3.3 `get_expression_mode`, `get_expression_constraints`, `get_attachment_style`, `get_caregivers`, `get_stress_state`, `save_state`: delegate to BabyState fields and cradle/state.save_state

- [ ] 4. `[CRADLE]` LLM Functions (cradle/mind.py -- extend)
  - [ ] 4.1 Implement `generate_heartbeat_evaluation(state, inner_monologue, behavior_space, expression_constraints) -> dict | None`: LLM prompt for child's subconscious decision (initiative true/false + type/behavior_type/trigger/expression/parent_hint), 30s timeout, JSON parse
  - [ ] 4.2 Implement `_HEARTBEAT_FALLBACKS` dict: preset expressions per expression_mode (10 entries, all three behavior_types represented)
  - [ ] 4.3 Implement `generate_ignored_reaction(state, provider, initiative_state) -> dict`: LLM prompt for emotional reaction to being ignored, influenced by attachment_style/expression_mode/stress_level/behavior_type
  - [ ] 4.4 Implement `_IGNORED_FALLBACKS` dict: preset reactions per (expression_mode, attachment_style) combination

- [x] 5. `[CRADLE]` Ignore Consequence System (cradle/heartbeat_provider.py)
  - [x] 5.1 Implement `shift_attachment_toward_avoidant(state: BabyState)`: forming->avoidant, secure->anxious, anxious->avoidant transition
  - [x] 5.2 Wire ignore escalation in CradleMonologueProvider: on consecutive_ignores >= 3, call `_check_stress_regression` from nanny.py + `shift_attachment_toward_avoidant`

- [ ] 6. `[CRADLE]` grow/stream Integration (cradle/nanny.py)
  - [ ] 6.1 Import `evaluate_heartbeat` from `heartbeat.py` and `CradleMonologueProvider` from `cradle/heartbeat_provider.py`
  - [ ] 6.2 In `grow_stream()`, after `phase_simulated` event: instantiate provider, call `evaluate_heartbeat(state, provider, state.initiative)`, if initiative returned yield `{"event": "heartbeat_initiative", ...}`
  - [ ] 6.3 If ignore reaction returned from heartbeat check, yield `{"event": "heartbeat_ignored", ...}`

- [ ] 7. `[CRADLE]` interact Integration (api/cradle.py)
  - [ ] 7.1 Import `evaluate_heartbeat`, `frequency_gate` from `heartbeat.py` and `CradleMonologueProvider`
  - [ ] 7.2 In `interact()`, add respond detection: if `state.initiative.pending_initiative_id` is set, clear it, reset `consecutive_ignores`, increment `total_responded`, boost `caregiver.responsiveness` (+0.03)
  - [ ] 7.3 Always update `state.initiative.last_interact_ts`
  - [ ] 7.4 After baby response: call `evaluate_heartbeat`, include result as `initiative` field in response JSON

- [ ] 8. `[CRADLE]` Poll Endpoint (api/cradle.py)
  - [ ] 8.1 Add `GET /{baby_id}/heartbeat` endpoint: load state, instantiate CradleMonologueProvider, call `evaluate_heartbeat`, return `{status, initiative, ignored_reaction}`
  - [ ] 8.2 Handle grow/stream lock: if active, return `{status: "growing", initiative: null}`

- [ ] 9. `[CRADLE]` Frontend: Poll Manager (Cradle.jsx)
  - [ ] 9.1 Add `useEffect` for idle polling: poll `GET /{baby_id}/heartbeat` every 60s when idle
  - [ ] 9.2 Stop polling when grow/stream starts; resume when it ends + 60s cooldown
  - [ ] 9.3 On receiving initiative from poll, dispatch `HEARTBEAT_INITIATIVE` to reducer

- [ ] 10. `[CRADLE]` Frontend: Response Handling (Cradle.jsx)
  - [ ] 10.1 Extend interact response handler: check `response.initiative` and `response.ignored_reaction`
  - [ ] 10.2 Extend SSE reducer to handle `heartbeat_initiative` and `heartbeat_ignored` event types
  - [ ] 10.3 Dispatch `HEARTBEAT_INITIATIVE` / `HEARTBEAT_IGNORED` to reducer when present

- [ ] 11. `[CRADLE]` Frontend: Chat Panel UI (Cradle.jsx)
  - [ ] 11.1 Render initiative messages: warm-colored border, trigger label badge, behavior_type icon (speech/hand/shield)
  - [ ] 11.2 Render avoidance initiatives: cool/muted border, avoidance indicator (lock/turned-away icon)
  - [ ] 11.3 Add "Respond" button on non-avoidance initiatives: focuses input or opens touch panel
  - [ ] 11.4 Render ignored reactions: muted gray style, ignore indicator, consecutive count
  - [ ] 11.5 Handle avoidance context in interact input (hint that child is in avoidance mode)

- [ ] 12. Documentation (DocOps)
  - [ ] 12.1 Add L3 header to new `heartbeat.py`
  - [x] 12.2 Add L3 header to new `cradle/heartbeat_provider.py`
  - [x] 12.3 Update `cradle/CLAUDE.md` L2: add heartbeat_provider.py member, update data flow
  - [ ] 12.4 Update `cradle/state.py` L3 header: add InitiativeState import
  - [ ] 12.5 Update `cradle/mind.py` L3 header: add heartbeat LLM functions
  - [ ] 12.6 Update `api/cradle.py` L3 header: add heartbeat endpoint
  - [ ] 12.7 Update root `CLAUDE.md` L1: add heartbeat.py as top-level module

- [ ] 13. Testing and Verification
  - [ ] 13.1 Manual: call `GET /heartbeat` on existing baby, verify response structure `{status, initiative, ignored_reaction}`
  - [ ] 13.2 Manual: set stress_level=0.7, call heartbeat, verify LLM produces urgent initiative with behavior_type
  - [ ] 13.3 Manual: call interact, verify `initiative` field present in response
  - [ ] 13.4 Manual: set pending_initiative with ts > 5min ago, call heartbeat, verify ignored reaction
  - [ ] 13.5 Manual: run grow/stream, verify heartbeat_initiative SSE events between phases
  - [ ] 13.6 Manual: verify poll returns `{status: "growing"}` while grow/stream active
  - [ ] 13.7 Manual: advance baby to phase 8+, verify avoidance behaviors appear in initiative responses
  - [ ] 13.8 Frontend: verify initiative messages with warm style and behavior_type icon
  - [ ] 13.9 Frontend: verify avoidance initiatives with cool/muted style
  - [ ] 13.10 Frontend: verify "Respond" button focuses input
  - [ ] 13.11 Frontend: verify ignored reactions with muted style

## Task Dependency Graph

```
1 (heartbeat.py core) ──> 2 (BabyState extension)
        │                        │
        │                 3 (CradleMonologueProvider) ──> 6 (grow/stream)
        │                        │                   ──> 7 (interact)
        │                 4 (LLM functions)          ──> 8 (poll endpoint)
        │                        │
        │                 5 (ignore consequences)
        │
        └── all [GENERIC] tasks are prerequisites for [CRADLE] tasks
                                                            │
                                                    9 (frontend poll) ──┐
                                                   10 (frontend events) │──> 11 (UI)
                                                                       ──┘
                                                            │
                                                   12 (docs) -- concurrent
                                                            │
                                                   13 (testing) -- last
```

## Parallelism Notes

- **Task 1** is the foundation -- must be completed first (all others depend on it)
- **Tasks 2, 3, 4, 5** can be developed in parallel (all depend only on Task 1)
- **Tasks 6, 7, 8** can be developed in parallel (all depend on Tasks 2+3+4)
- **Tasks 9, 10** can be developed in parallel (frontend channels are independent)
- **Task 11** depends on 9+10 (needs data sources to render)
- **Task 12** sub-tasks done alongside corresponding code tasks
- **Task 13** is final verification pass

## World Extension Checklist (Future, NOT in current scope)

When `world/` module is created, add:
- [ ] W.1 `world/heartbeat_provider.py`: WorldMonologueProvider + WORLD_BEHAVIOR_SPACE
- [ ] W.2 WorldState: add `initiative: InitiativeState` field
- [ ] W.3 `world/mind.py` or equivalent: world-specific LLM functions and fallback tables
- [ ] W.4 `api/world.py`: heartbeat injection in world endpoints
- [ ] W.5 Frontend: world-specific initiative UI (if different from cradle)

Zero changes to `heartbeat.py` required.
