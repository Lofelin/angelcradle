# Plan: social (Multi-Agent Conversation)

## Tasks

- [ ] 1. LLM Chat Support (`llm.py`)
  - [ ] 1.1 Add `call_llm_chat(system: str, messages: list[dict], client, model, provider) -> str` that sends system prompt + chat messages array to the LLM provider
  - [ ] 1.2 Add `_call_chat_and_parse(system: str, messages: list[dict]) -> dict | None` convenience wrapper (get client, call, parse JSON) in `cradle/social.py`

- [ ] 2. Session Data Model (`cradle/social.py`)
  - [ ] 2.1 Create `cradle/social.py` with L3 header
  - [ ] 2.2 Define `SocialMessage` dataclass: role, baby_id, name, content, emotional_tone, state_changes, timestamp
  - [ ] 2.3 Define `SocialSession` dataclass: session_id, participant_ids, participant_states, context, history, pending_changes, turn_index, created_at, last_activity
  - [ ] 2.4 Define module-level stores: `_social_sessions: dict[str, SocialSession]`, `_baby_session_map: dict[str, str]`
  - [ ] 2.5 Define `SESSION_TIMEOUT = 30 * 60`

- [ ] 3. Session Lifecycle (`cradle/social.py`)
  - [ ] 3.1 `start_session(baby_ids: list[str], context: str) -> dict` -- load states, create session, register in stores, return metadata
  - [ ] 3.2 `end_session(session_id: str) -> dict` -- aggregate pending_changes, apply to states, save_state, dual-write persistence, cleanup stores
  - [ ] 3.3 `get_session_history(session_id: str) -> dict` -- return full chronological history
  - [ ] 3.4 `_check_session_alive(session) -> bool` -- lazy timeout check, auto-end if expired
  - [ ] 3.5 `_aggregate_changes(changes_list: list[dict]) -> dict` -- merge multiple turns' state_changes
  - [ ] 3.6 `is_baby_in_session(baby_id: str) -> bool` -- check `_baby_session_map`

- [ ] 4. Turn Strategy (`cradle/social.py`)
  - [ ] 4.1 `_select_next_speaker(session, parent_mentioned: str | None) -> str` -- round-robin base + arousal modifier + parent-mention override
  - [ ] 4.2 Name-mention detection: scan parent message for participant names, return first match or None

- [ ] 5. LLM Agent Call (`cradle/social.py`)
  - [ ] 5.1 `_build_system_prompt(state: BabyState, other_participants: list[dict], context: str) -> str` -- baby identity + expression mode + peer descriptions + scene
  - [ ] 5.2 `_build_chat_messages(session: SocialSession, current_baby_id: str) -> list[dict]` -- map shared history to LLM chat format (own responses = assistant, others = user)
  - [ ] 5.3 `generate_social_turn(state, other_participants, history_messages, context) -> dict` -- single LLM call, parse response, fallback on failure
  - [ ] 5.4 Fallback: return `_FALLBACK_REACTIONS[expression_mode]` with neutral tone and empty state_changes

- [ ] 6. Turn & Message Orchestration (`cradle/social.py`)
  - [ ] 6.1 `advance_turn(session_id: str) -> dict` -- select speaker, build prompt, call LLM, append to history, accumulate changes, advance turn_index, update last_activity
  - [ ] 6.2 `inject_parent_message(session_id: str, message: str) -> dict` -- append parent message, detect mentioned baby, execute one baby turn, return both

- [ ] 7. API Endpoints (`api/cradle.py`)
  - [ ] 7.1 Add request models: `SocialStartRequest`, `SocialTurnRequest`, `SocialMessageRequest`, `SocialEndRequest`
  - [ ] 7.2 `POST /cradle/social/start` -- validate (count, duplicates, grow_locks, session_map, state exists, phase >= 8), call `start_session()`
  - [ ] 7.3 `POST /cradle/social/turn` -- validate session exists + alive, call `advance_turn()`
  - [ ] 7.4 `POST /cradle/social/message` -- validate session + message non-empty, call `inject_parent_message()`
  - [ ] 7.5 `GET /cradle/social/{session_id}/history` -- validate session exists, call `get_session_history()`
  - [ ] 7.6 `POST /cradle/social/end` -- validate session exists, call `end_session()`

- [ ] 8. Concurrency Guards (`api/cradle.py`)
  - [ ] 8.1 Add session check to `interact` endpoint: `if is_baby_in_session(baby_id): raise 409`
  - [ ] 8.2 Add session check to `grow/stream` endpoint: `if is_baby_in_session(baby_id): raise 409`
  - [ ] 8.3 Import `is_baby_in_session` from `cradle/social.py`

- [ ] 9. Module Exports (`cradle/__init__.py`)
  - [ ] 9.1 Export social functions: `start_session`, `advance_turn`, `inject_parent_message`, `get_session_history`, `end_session`, `is_baby_in_session`

- [ ] 10. Frontend: Social Button & Selector (`Cradle.jsx`)
  - [ ] 10.1 Compute eligible babies: `cradleBabies.filter(b => (b.current_phase || 0) >= 8)`
  - [ ] 10.2 Show "Social" button when `eligible.length >= 2`
  - [ ] 10.3 Baby selector UI: checkboxes for eligible babies (name + phase), min 2 to enable start
  - [ ] 10.4 Optional context input field
  - [ ] 10.5 "Start Session" button -> POST `/cradle/social/start`, store session in state

- [ ] 11. Frontend: Session Chat UI (`Cradle.jsx`)
  - [ ] 11.1 Add state: `socialSession`, `socialHistory`, `socialSending`
  - [ ] 11.2 Add reducer actions: `SOCIAL_START`, `SOCIAL_TURN_DONE`, `SOCIAL_MSG_DONE`, `SOCIAL_END`, `SOCIAL_ERROR`
  - [ ] 11.3 Group chat message area: chronological messages with per-baby color/icon differentiation
  - [ ] 11.4 "Next Turn" button -> POST `/cradle/social/turn`, append response to history
  - [ ] 11.5 Text input + send -> POST `/cradle/social/message`, append parent msg + baby response
  - [ ] 11.6 "End Session" button -> POST `/cradle/social/end`, display summary + per-baby changes
  - [ ] 11.7 Loading states during LLM calls (disable buttons, show spinner)

- [ ] 12. Documentation Updates
  - [ ] 12.1 Add `cradle/social.py` L3 header with INPUT/OUTPUT/POS/PROTOCOL
  - [ ] 12.2 Update `cradle/CLAUDE.md`: add social.py entry to member list
  - [ ] 12.3 Update `api/cradle.py` L3 header: add social endpoints to OUTPUT
