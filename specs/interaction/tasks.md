# Plan: interaction

## Tasks

- [ ] 1. State layer: ParentProfile + persistence functions
  - [ ] 1.1 Add `interaction_count: int = 0` to `ParentProfile` in `cradle/state.py`, update `to_dict()` and `from_dict()` (backward compatible default)
  - [ ] 1.2 Add `append_interaction(baby_id, record)` function in `cradle/state.py` -- writes to `nursery/{baby_id}/interactions.jsonl`
  - [ ] 1.3 Add `load_interactions(baby_id, limit=5)` function in `cradle/state.py` -- reads JSONL, returns last N records
  - [ ] 1.4 Export `append_interaction`, `load_interactions` from `cradle/__init__.py`

- [ ] 2. Mind layer: LLM interaction response
  - [ ] 2.1 Add `generate_interaction_response(state, parent_message, recent_interactions)` in `cradle/mind.py`
  - [ ] 2.2 Build prompt template: infant profile + constraints + expression_mode enforcement + recent 3 memories + recent 5 interactions + parent message
  - [ ] 2.3 Implement degradation fallback: expression_mode-specific minimal reactions when LLM fails
  - [ ] 2.4 Update `generate_phase_summary()` prompt to include `interaction_count` in parent engagement context

- [ ] 3. API layer: concurrency lock + endpoint
  - [ ] 3.1 Add `_grow_locks: dict[str, bool] = {}` module-level dict in `api/cradle.py`
  - [ ] 3.2 Wrap `grow()` endpoint: set lock before generator starts, clear on stream end / error / paused / growth_complete (use a wrapper generator with try/finally)
  - [ ] 3.3 Add `InteractRequest(BaseModel)` with `message: str` field
  - [ ] 3.4 Add `POST /{baby_id}/interact` endpoint: check lock -> load state -> load interactions -> call mind -> dual-write -> increment interaction_count -> save state -> return response
  - [ ] 3.5 Update `cradle/__init__.py` imports if needed for new exports used by API

- [ ] 4. Frontend: chat UI
  - [ ] 4.1 Add `interactionSending` to reducer INIT state, add `INTERACTION_SENDING`, `INTERACTION_DONE`, `INTERACTION_ERROR` action types to reducer
  - [ ] 4.2 Add chat input component at bottom of right panel: text input + send button, disabled when `running && !paused`
  - [ ] 4.3 Add `sendInteraction(message)` async function: POST to API, dispatch reducer actions
  - [ ] 4.4 Handle 409 response: show brief inline toast/notice "Baby is growing, please wait"
  - [ ] 4.5 Add interaction bubble rendering in `renderLog`: parent message (right-aligned) + baby response (left-aligned, italic)
  - [ ] 4.6 Ensure interaction events from `events.jsonl` history load correctly on page refresh (they have `event: "interaction"`)
  - [ ] 4.7 Add i18n keys in `i18n.js`: "Talk to {name}...", "Growing...", "Send", interaction-related labels

- [ ] 5. Documentation update
  - [ ] 5.1 Update `cradle/CLAUDE.md`: add interaction functions to member list, update data flow diagram
  - [ ] 5.2 Update L3 headers in modified files (`state.py`, `mind.py`, `api/cradle.py`)
