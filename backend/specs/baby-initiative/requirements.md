# Requirements: Initiative System - Heartbeat Mode (Cross-Module)

## Overview

A cross-module initiative system where the child proactively initiates interactions with parents. Instead of living inside `cradle/`, the heartbeat engine sits at the project root (`heartbeat.py`) and serves the entire lifecycle: cradle (0-7 years) and world (7+ years, future).

The LLM acts as the child's subconscious -- given full internal state via a pluggable context provider, it judges whether and how the child would initiate contact. Silent most of the time; vocal only when it matters.

### Key Architectural Principle

**Heartbeat is a top-level system, not a cradle sub-module.** It consumes state from any lifecycle module through an adapter pattern (MonologueProvider). cradle and world each provide their own context builder; the heartbeat engine is agnostic to which lifecycle stage is active.

### Behavior Space

Initiative behaviors span three types that evolve across the lifecycle:

| Type | Description | Cradle Examples | World Examples (future) |
|------|-------------|-----------------|------------------------|
| **Verbal** | Speech, vocalization, silence-as-statement | Cry, babble, "mama!", call for help | Ask "why?", first lie, refuse to answer |
| **Physical** | Body actions, gestures, object interaction | Reach, point, pull hand, hug, push away | Lock door, slam door, hide diary |
| **Avoidance** | Actively seeking distance, evading | Turn away, cover eyes, hide behind parent | Dodge questions, refuse calls, keep secrets, avoid meeting |

Avoidance is itself a form of initiative -- the child is actively choosing NOT to engage, which is developmentally significant.

## User Stories and Acceptance Criteria

### US-1: Urgent Need Initiative (Cradle)

**As a** parent, **I want** the baby to call for me when hungry, scared, in pain, or sleepy, **so that** I can attend to basic needs in time.

**Acceptance Criteria (EARS):**

1. **When** a heartbeat evaluation runs and the child's internal state contains high-stress signals (stress_level > 0.5, sleep_regression_active, known fears triggered), **the system shall** include these signals in the inner monologue context and let the LLM determine if the child initiates an urgent call.
2. **When** the LLM determines an urgent initiative, **the system shall** return an initiative event with `type: "urgent"`, a behavior_type (`verbal` / `physical`), a trigger reason, an expression conforming to the current `expression_mode`, and a hint for the parent.
3. **When** the LLM determines no initiative is needed, **the system shall** return a silent heartbeat result (null) without disturbing the user.
4. **While** grow/stream is running, **the system shall not** trigger standalone heartbeat evaluations (heartbeats are injected at the end of each phase within grow/stream itself).

### US-2: Exploratory Initiative (Cradle)

**As a** parent, **I want** the baby to reach out because of curiosity, boredom, desire to share, or desire to play, **so that** I feel the baby's personality and growth.

**Acceptance Criteria (EARS):**

1. **When** a heartbeat evaluation runs and the child's internal state has low stress, active preferences, or an imaginary friend, **the system shall** include these in the inner monologue context for the LLM to judge exploratory initiative.
2. **When** the LLM generates an exploratory initiative, **the system shall** return an initiative event with `type: "exploratory"`, `behavior_type`, trigger reason, expression, and context hint.
3. **When** the child's `expression_mode` is `cry_only` or `coo_and_gaze`, **the system shall** instruct the LLM to produce only non-verbal expressions (cry patterns, gaze, body movement) with no words.
4. **When** the LLM call fails or times out (30s), **the system shall** degrade to a preset fallback expression based on `expression_mode`.

### US-3: Avoidance Initiative (Cradle + World)

**As a** parent, **I want** the child to sometimes actively avoid me or hide things from me, **so that** I experience the realistic push-pull dynamics of child development.

**Acceptance Criteria (EARS):**

1. **When** the child's development reaches phases with autonomy capabilities (phase >= 7, `why_phase` onward), **the system shall** include avoidance behaviors in the LLM's available behavior space.
2. **When** the LLM generates an avoidance initiative, **the system shall** return an initiative event with `behavior_type: "avoidance"`, including the avoidance method (e.g., "dodge_question", "refuse_interaction", "hide_secret", "avoid_topic").
3. **When** the child is in early cradle phases (0-6), **the system shall** limit avoidance to primitive forms only (turn away, cover eyes, hide behind caregiver).
4. **When** an avoidance initiative is active, **the system shall** modify subsequent interaction responses to maintain the avoidance posture (e.g., if the child is hiding a secret, interactions should reflect evasiveness).

### US-4: Three Trigger Points and Delivery

**As a** parent, **I want** to receive child initiatives through natural channels without a separate SSE connection, **so that** the system remains simple and lightweight.

**Acceptance Criteria (EARS):**

1. **When** a grow/stream phase simulation completes (after `phase_simulated`, before `phase_completing`), **the system shall** inject a heartbeat evaluation and emit any initiative as an SSE event (`heartbeat_initiative`) on the existing stream.
2. **When** an interact request completes, **the system shall** run a heartbeat evaluation and return any initiative as an additional `initiative` field in the interact response JSON.
3. **When** the frontend polls `GET /{baby_id}/heartbeat` during idle periods, **the system shall** run a heartbeat evaluation and return the result.
4. **When** a heartbeat evaluation returns null, **the system shall** return `{"status": "ok", "initiative": null}` for the poll endpoint.

### US-5: Parent Response and Ignore Mechanism

**As a** parent, **I want** to be able to respond to or ignore the child's initiatives, **so that** the simulation reflects real parenting dynamics.

**Acceptance Criteria (EARS):**

1. **When** the parent interacts after receiving an initiative, **the system shall** treat it as a "response", positively update `caregiver.responsiveness` (+0.03), reset `consecutive_ignores`, and generate a positive feedback reaction.
2. **When** an initiative is emitted and the parent does not interact within 5 minutes, **the system shall** detect the timeout, mark it as "ignored", and negatively update `caregiver.responsiveness` (-0.05).
3. **When** the child is ignored, **the system shall** generate an emotional reaction via LLM influenced by `attachment_style`, `expression_mode`, and `stress_level`, delivered through the next available channel.
4. **When** the same child is ignored 3+ consecutive times, **the system shall** escalate: increase `stress_level`, potentially trigger stress regression, shift `attachment_style` toward avoidant.

### US-6: Frequency Control

**As a** parent, **I want** the child's initiative frequency to be reasonable, **so that** I am not constantly disturbed.

**Acceptance Criteria (EARS):**

1. **The system shall** enforce a hard minimum interval of 2 minutes between any two initiative events.
2. **When** the LLM evaluates a heartbeat, **the system shall** include "time since last initiative" in the context, letting the LLM self-regulate frequency.
3. **When** the parent just completed an interact, **the system shall** suppress initiative generation for 60 seconds (post-interact cooldown).
4. **When** the hard minimum interval has not elapsed, **the system shall** skip the LLM call entirely and return null immediately.

### US-7: Cross-Module Architecture (Extensibility)

**As a** developer, **I want** the initiative system to be decoupled from cradle-specific data models, **so that** the same heartbeat engine can serve the world module when it exists.

**Acceptance Criteria (EARS):**

1. **The system shall** define a `MonologueProvider` protocol (Python Protocol class) with a method `build_inner_monologue(state) -> str` that any lifecycle module can implement.
2. **The system shall** place the heartbeat engine at the project root level (`heartbeat.py`), not inside `cradle/`.
3. **The system shall** define `InitiativeState` as a standalone dataclass (in `heartbeat.py`), not coupled to `BabyState`.
4. **When** the heartbeat engine is called, **the system shall** receive a `MonologueProvider` instance and an opaque state reference, without importing cradle-specific types in the core engine.
5. **The system shall** define a `BehaviorSpace` that expands based on lifecycle stage -- cradle provides cradle-appropriate behaviors, world (future) provides world-appropriate behaviors.

### US-8: UI Presentation

**As a** parent, **I want** to clearly distinguish "child reached out to me" from "I reached out to child" in the interface, **so that** I understand who initiated each interaction.

**Acceptance Criteria (EARS):**

1. **When** a heartbeat initiative is received, **the system shall** display it with a visually differentiated style (warm-colored border, trigger label badge, behavior_type indicator).
2. **When** an initiative is displayed, **the system shall** show a "Respond" button that focuses the input or opens the action panel.
3. **When** an ignored reaction is received, **the system shall** display it with a muted/gray style and an ignore indicator.
4. **When** an avoidance initiative is displayed, **the system shall** use a distinct visual treatment (e.g., fading out, turned-away indicator) to convey the child is pulling away.

## Non-Functional Requirements

### NFR-1: Performance
- Heartbeat LLM evaluation timeout: 30 seconds. Timeout degrades to preset fallback.
- Hard minimum interval check is pure arithmetic (< 1ms), applied before any LLM call.
- Poll endpoint response time: < 50ms when no LLM call needed, < 30s when LLM call is made.

### NFR-2: Backward Compatibility
- New `initiative` field in BabyState uses default values; old state.json loads without migration.
- No new SSE connections; reuse existing grow/stream SSE + interact response + lightweight poll endpoint.
- Existing grow/stream and interact endpoints remain fully functional with no breaking changes.
- InitiativeState is stored inside each module's state file (e.g., inside state.json for cradle), not in a separate file.

### NFR-3: Data Persistence
- Initiative events appended to events.jsonl (consistent with existing event format).
- Ignore records appended to events.jsonl with type `initiative_ignored`.

### NFR-4: Degradation
- LLM failure: fall back to a rule-based preset reaction table indexed by (expression_mode, trigger_type).
- LLM timeout: same as failure.
- The system never silently fails -- either LLM produces a result or the fallback fires.

### NFR-5: Extensibility
- Adding a new lifecycle module (world) requires only: implement MonologueProvider, register it, provide behavior space definitions.
- Zero changes to `heartbeat.py` core engine when adding new lifecycle stages.
