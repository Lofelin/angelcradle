# Requirements: Parent-Child Interaction (interaction)

## Overview

Parents can talk to their baby at any time during the cradle phase. The baby responds according to its current expression mode, innate identity, and accumulated memories. Interactions are persisted independently and also recorded in the main event log.

---

## User Stories

### US-1: Parent sends a message to the baby

**As a** parent,
**I want to** type a message and send it to my baby in the cradle,
**so that** I can interact with the baby and influence its development.

**Acceptance Criteria (EARS):**

1. **When** the parent submits a text message via the chat input, **the system shall** send the message to `POST /cradle/{baby_id}/interact` and display the parent's message immediately as a sent bubble.
2. **When** the API returns a baby response, **the system shall** display the baby's reaction as a received bubble, respecting the current `expression_mode` format.
3. **Where** `grow/stream` is actively running (not paused), **the system shall** reject the interaction request with HTTP 409 Conflict and display a brief inline notice.
4. **Where** `grow/stream` is paused (awaiting parent intervention on a critical event), **the system shall** allow the interaction request.
5. **Where** `grow/stream` has completed or has not started, **the system shall** allow the interaction request.

### US-2: Baby responds according to expression mode

**As a** parent,
**I want** the baby's response to match its current developmental stage,
**so that** the interaction feels authentic to the baby's age and capabilities.

**Acceptance Criteria (EARS):**

1. **When** the baby is in `cry_only` mode, **the system shall** generate a response using only movements, sounds, and cry patterns -- no words.
2. **When** the baby is in `first_words` or later modes, **the system shall** generate a response using the vocabulary and sentence complexity appropriate to that mode.
3. **When** the baby has innate constraints (e.g., hearing loss, high arousal baseline), **the system shall** respect those constraints in the generated response.
4. **When** the baby has accumulated fears, preferences, or comfort sources, **the system shall** incorporate relevant ones into the response context.

### US-3: Interaction history is persisted

**As a** parent,
**I want** all my conversations with the baby to be saved,
**so that** I can review them and they influence the baby's development.

**Acceptance Criteria (EARS):**

1. **When** an interaction completes, **the system shall** append both the parent message and baby response to `nursery/{baby_id}/interactions.jsonl`.
2. **When** an interaction completes, **the system shall** also append an `interaction` event to `nursery/{baby_id}/events.jsonl` for timeline continuity.
3. **When** generating the LLM prompt for a new interaction, **the system shall** include the most recent 5 interaction turns as conversation context.
4. **When** generating the LLM prompt for a new interaction, **the system shall** include the most recent 3 memories from `state.memories`.

### US-4: Interaction count is tracked

**As a** parent,
**I want** my interaction frequency to be recorded,
**so that** the phase summary LLM can assess my engagement quality.

**Acceptance Criteria (EARS):**

1. **When** an interaction completes, **the system shall** increment `parent_profile.interaction_count` in `BabyState` and save state.
2. **When** generating a phase summary, **the system shall** include the `interaction_count` in the prompt context for LLM evaluation.

### US-5: Chat UI in cradle view

**As a** parent,
**I want** a persistent chat input area at the bottom of the cradle timeline,
**so that** I can talk to my baby while watching the growth log.

**Acceptance Criteria (EARS):**

1. **When** a baby is selected and admitted to the cradle, **the system shall** display a text input with a send button at the bottom of the right panel (timeline area).
2. **Where** grow is actively running (not paused), **the system shall** disable the input and show a brief status hint (e.g., "Growing...").
3. **Where** grow is paused or idle, **the system shall** enable the input for interaction.
4. **When** the parent presses Enter or clicks the send button, **the system shall** send the message and show a loading indicator until the response arrives.
5. **When** a baby response arrives, **the system shall** render it as a chat bubble in the timeline, visually distinct from growth events.

---

## Constraints

1. **Concurrency**: Hard lock. Only one of `grow_stream` or `interact` can run at a time per baby. `grow_stream` running returns 409; paused state allows interaction.
2. **Persistence**: Dual-write to `interactions.jsonl` (detailed) and `events.jsonl` (timeline event).
3. **Context window**: Last 5 interaction turns + last 3 memories per LLM call.
4. **Expression mode enforcement**: The LLM prompt must strictly constrain output format to the baby's current `expression_mode`.
5. **No action dropdown**: Pure text input only. The baby interprets the parent's natural language.
6. **ParentProfile update**: Only `interaction_count` is incremented. No style/responsiveness changes from chat -- those are assessed holistically during phase summary.
