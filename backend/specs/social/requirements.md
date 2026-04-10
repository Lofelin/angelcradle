# Requirements: Multi-Baby Social -- Multi-Agent Conversation

## Overview

Enable babies (Phase 8+) to engage in multi-turn social conversations where **each baby is an independent LLM agent**. A social session is a shared conversation history where agents take turns responding. Parents can inject messages at any time. State changes accumulate during the session and are settled when the session ends.

This replaces the previous single-LLM-call design. The core insight: social interaction is not a single snapshot -- it is an evolving multi-turn dialogue with emergent dynamics.

---

## User Stories

### US-1: Start Social Session

**As a** parent with multiple babies in the cradle,
**I want to** start a social session by selecting 2+ babies,
**so that** they can engage in an ongoing multi-turn conversation.

**Acceptance Criteria (EARS):**

- **When** the parent submits a social start request with a list of baby_ids, **the system shall** validate that every baby has `current_phase >= 8`.
- **Where** any baby has `current_phase < 8`, **the system shall** reject with HTTP 400 identifying which babies are ineligible and their current phase.
- **When** the list contains fewer than 2 baby_ids, **the system shall** reject with HTTP 400.
- **When** any baby_id has an active `_grow_lock`, **the system shall** reject with HTTP 409 identifying locked babies.
- **Where** any baby is already in an active social session, **the system shall** reject with HTTP 409 identifying which babies are occupied.
- **When** all validations pass, **the system shall** create a session with a unique session_id, load all participants' states, and return session metadata including each participant's name and expression_mode.
- **When** the parent includes an optional `context` field, **the system shall** store it as the scene setting for the session.

### US-2: Advance Conversation Turn

**As a** parent observing a social session,
**I want to** advance the conversation by one turn,
**so that** the next baby responds and the interaction progresses naturally.

**Acceptance Criteria (EARS):**

- **When** the parent requests a turn advance, **the system shall** select the next speaker using the turn strategy (default: round-robin, modified by social dynamics).
- **When** a speaker is selected, **the system shall** make one LLM call with that baby's identity as system context and the full shared conversation history.
- **When** the LLM returns, **the system shall** append the response to the shared history and return the baby's response, emotional tone, and pending state changes.
- **Where** the LLM call fails, **the system shall** return a fallback reaction appropriate to that baby's expression_mode.
- **When** calculating speaker order, **the system shall** consider arousal baseline (high-arousal babies more likely to speak next) and temperament (shy babies may skip turns).

### US-3: Parent Message Injection

**As a** parent participating in a social session,
**I want to** send a message into the conversation,
**so that** I can mediate, guide, or participate in the social dynamics.

**Acceptance Criteria (EARS):**

- **When** the parent sends a message to an active session, **the system shall** append it to the shared history as a parent utterance.
- **When** the parent message is appended, **the system shall** automatically trigger the next baby's turn and return that baby's response.
- **When** selecting which baby responds after a parent message, **the system shall** prioritize babies who are directly addressed or most likely to react based on temperament.

### US-4: View Session History

**As a** parent,
**I want to** view the complete conversation history of an active session,
**so that** I can review what happened.

**Acceptance Criteria (EARS):**

- **When** the parent requests session history, **the system shall** return all messages in chronological order with speaker identity, response text, emotional tone, and timestamps.
- **The** history **shall** include both baby responses and parent messages in their original order.

### US-5: End Session with State Settlement

**As a** parent,
**I want to** end a social session and have all developmental effects applied,
**so that** the interaction produces lasting impact on each baby's growth.

**Acceptance Criteria (EARS):**

- **When** the parent ends a session, **the system shall** aggregate all pending state_changes per baby accumulated during the session.
- **When** settling state changes, **the system shall** apply them to each baby independently (new_preference, new_comfort_source, fear_reduced, new_fear) with deduplication.
- **When** the session ends, **the system shall** persist each baby's updated state via `save_state()`.
- **When** the session ends, **the system shall** append the full session record to each baby's `interactions.jsonl` (type: `social_session`) and `events.jsonl` (event: `social_session`).
- **When** the session ends, **the system shall** return a summary of the session and per-baby accumulated changes.
- **When** a session has been idle for 30 minutes, **the system shall** automatically end it and settle state changes.

### US-6: Expression Mode Fidelity

**As a** parent,
**I want** each baby's responses to strictly follow their expression_mode,
**so that** social interaction remains developmentally accurate.

**Acceptance Criteria (EARS):**

- **When** generating a baby's turn response, **the system shall** enforce that baby's expression_mode in the system prompt -- a Phase 8 baby (narrative) and a Phase 9 baby (reasoning) must respond in their respective formats.
- **When** generating a baby's turn response, **the system shall** enforce that baby's identity constraints (temperament, sensory profile, arousal baseline, defects).

### US-7: Concurrent Session Isolation

**As a** system operator,
**I want** social sessions to be isolated from other operations,
**so that** state integrity is maintained.

**Acceptance Criteria (EARS):**

- **While** a baby is in an active social session, **the system shall** reject `grow/stream` requests for that baby with HTTP 409.
- **While** a baby is in an active social session, **the system shall** reject individual `interact` requests for that baby with HTTP 409.
- **While** a baby has an active `_grow_lock`, **the system shall** reject social session start requests involving that baby with HTTP 409.

### US-8: Frontend Social Mode

**As a** parent using the web interface,
**I want** a group-chat-like UI for social sessions,
**so that** I can observe and participate in the multi-turn conversation.

**Acceptance Criteria (EARS):**

- **Where** the parent has at least 2 babies with `current_phase >= 8`, **the system shall** display a "Social" button in the Cradle interface.
- **When** the parent clicks the Social button, **the system shall** show a baby selector listing only eligible babies (Phase 8+).
- **When** a session is active, **the system shall** display a group-chat interface where each baby's messages have a distinct color/icon.
- **When** a session is active, **the system shall** provide a "Next Turn" button to advance the conversation.
- **When** a session is active, **the system shall** provide a text input for parent message injection.
- **When** a session is active, **the system shall** provide an "End Session" button that triggers settlement and displays results.
- **Where** fewer than 2 babies are eligible, **the system shall** hide the Social button entirely.

---

## Constraints

1. Minimum 2 babies per session. No enforced upper limit, but UI should recommend 2-4 for best quality.
2. All participating babies must be Phase 8+ (social_budding). No exceptions.
3. One LLM call per turn per baby -- NOT one call for all babies.
4. Turn and message endpoints are synchronous POST (not SSE). Each turn is a few seconds.
5. State changes are deferred -- accumulated during session, applied only on end.
6. Sessions are in-memory (dict). Server restart kills active sessions (acceptable for MVP).
7. A baby can only be in one social session at a time.

---

## Out of Scope (MVP)

- Persistent social relationships / friendship tracking between babies
- SSE streaming for individual turns
- Cross-user baby social interactions
- Automatic turn progression (always user-triggered)
- Session persistence across server restarts
- Complex speaker selection algorithms (MVP uses round-robin with simple arousal modifier)
