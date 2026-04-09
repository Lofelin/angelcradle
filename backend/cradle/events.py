"""
Random event system.

Three event categories: daily (rule engine), environment (LLM-driven), critical (pause for parent).
Each event is filtered through the baby's sensory_profile, producing differentiated reactions.

[INPUT]: Depends on cradle/state.py SensoryProfile
[OUTPUT]: Event dataclass, roll_events() function
[POS]: Event generation layer in cradle/, consumed by nanny.py
[PROTOCOL]: Update this header on change, then check CLAUDE.md
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class Event:
    """A growth event."""
    name: str
    category: str                   # daily / environment / critical
    display_name: str
    description: str
    sensory_channels: list[str]     # sensory channels involved
    intensity: float                # 0-1, stimulus intensity
    requires_parent: bool           # whether parent intervention is needed
    phase_range: tuple[int, int]    # phase range where event can occur (inclusive)
    weight: float = 1.0             # probability weight
    parent_choices: list[dict] = field(default_factory=list)  # parent action choices


# ============================================================
# Daily events — handled by rule engine, no LLM needed
# ============================================================

DAILY_EVENTS = [
    Event(
        name="feeding_difficulty",
        category="daily",
        display_name="Feeding Difficulty",
        description="Baby has trouble feeding, needs position adjustment or soothing.",
        sensory_channels=["touch", "smell"],
        intensity=0.3,
        requires_parent=False,
        phase_range=(0, 3),
    ),
    Event(
        name="sleep_disruption",
        category="daily",
        display_name="Sleep Disruption",
        description="Baby wakes up during sleep, cannot self-soothe.",
        sensory_channels=["touch"],
        intensity=0.2,
        requires_parent=False,
        phase_range=(0, 7),
    ),
    Event(
        name="body_discomfort",
        category="daily",
        display_name="Body Discomfort",
        description="General discomfort (gas, wet diaper, etc.), handled by nanny.",
        sensory_channels=["touch"],
        intensity=0.2,
        requires_parent=False,
        phase_range=(0, 5),
    ),
    Event(
        name="routine_sound",
        category="daily",
        display_name="Routine Sound",
        description="Everyday household sounds (faucet, doorbell, phone, TV).",
        sensory_channels=["hearing"],
        intensity=0.15,
        requires_parent=False,
        phase_range=(0, 5),
    ),
    Event(
        name="gentle_touch",
        category="daily",
        display_name="Gentle Touch",
        description="Nanny or family member gently stroking, hugging.",
        sensory_channels=["touch"],
        intensity=0.1,
        requires_parent=False,
        phase_range=(0, 4),
    ),
    Event(
        name="toy_interaction",
        category="daily",
        display_name="Toy Interaction",
        description="Interacting with hanging toys or rattles.",
        sensory_channels=["vision", "touch", "hearing"],
        intensity=0.2,
        requires_parent=False,
        phase_range=(1, 6),
    ),
    Event(
        name="outdoor_walk",
        category="daily",
        display_name="Outdoor Walk",
        description="Taken outside, feeling wind, sunlight, new sounds.",
        sensory_channels=["touch", "vision", "hearing", "smell"],
        intensity=0.3,
        requires_parent=False,
        phase_range=(1, 11),
    ),
]

# ============================================================
# Environment events — require LLM to process baby's reaction
# ============================================================

ENVIRONMENT_EVENTS = [
    Event(
        name="thunderstorm",
        category="environment",
        display_name="Thunderstorm",
        description="Sudden thunder and lightning. Windows rattle, ozone smell in the air.",
        sensory_channels=["hearing", "vision"],
        intensity=0.8,
        requires_parent=False,
        phase_range=(0, 7),
        weight=0.3,
    ),
    Event(
        name="music_first_time",
        category="environment",
        display_name="First Music",
        description="Music fills the room — melody, rhythm, harmony enter perception for the first time.",
        sensory_channels=["hearing"],
        intensity=0.5,
        requires_parent=False,
        phase_range=(0, 3),
        weight=0.8,
    ),
    Event(
        name="sunbeam_on_floor",
        category="environment",
        display_name="Sunbeam on Floor",
        description="A beam of sunlight through the window, dust dancing in the light.",
        sensory_channels=["vision"],
        intensity=0.3,
        requires_parent=False,
        phase_range=(1, 5),
        weight=0.6,
    ),
    Event(
        name="pet_encounter",
        category="environment",
        display_name="Pet Encounter",
        description="The family cat or dog approaches the baby for the first time. Animal smell, fur, sounds.",
        sensory_channels=["vision", "touch", "smell", "hearing"],
        intensity=0.6,
        requires_parent=False,
        phase_range=(1, 6),
        weight=0.4,
    ),
    Event(
        name="mirror_discovery",
        category="environment",
        display_name="Mirror Discovery",
        description="Baby sees themselves in a mirror for the first time. Who is that moving figure?",
        sensory_channels=["vision"],
        intensity=0.5,
        requires_parent=False,
        phase_range=(2, 6),
        weight=0.5,
    ),
    Event(
        name="water_play",
        category="environment",
        display_name="Water Play",
        description="During bath or water play — splashing, temperature, flow.",
        sensory_channels=["touch", "vision", "hearing"],
        intensity=0.4,
        requires_parent=False,
        phase_range=(2, 7),
        weight=0.5,
    ),
    Event(
        name="new_food_taste",
        category="environment",
        display_name="New Food",
        description="First encounter with solid food. New taste, texture, temperature.",
        sensory_channels=["smell", "touch"],
        intensity=0.5,
        requires_parent=False,
        phase_range=(3, 6),
        weight=0.6,
    ),
    Event(
        name="loud_argument",
        category="environment",
        display_name="Loud Argument",
        description="Nearby people arguing loudly. Sharp sounds, emotional tension.",
        sensory_channels=["hearing"],
        intensity=0.7,
        requires_parent=False,
        phase_range=(0, 11),
        weight=0.2,
    ),
    Event(
        name="stranger_visit",
        category="environment",
        display_name="Stranger Visit",
        description="An unfamiliar person appears — strange voice and smell.",
        sensory_channels=["vision", "hearing", "smell"],
        intensity=0.5,
        requires_parent=False,
        phase_range=(2, 8),
        weight=0.5,
    ),
    Event(
        name="other_baby_cry",
        category="environment",
        display_name="Other Baby Crying",
        description="Another baby's cry reaches them. A fellow creature's distress signal.",
        sensory_channels=["hearing"],
        intensity=0.5,
        requires_parent=False,
        phase_range=(0, 5),
        weight=0.3,
    ),
    Event(
        name="darkness",
        category="environment",
        display_name="Darkness",
        description="Room goes dark suddenly, or waking in complete darkness for the first time.",
        sensory_channels=["vision"],
        intensity=0.6,
        requires_parent=False,
        phase_range=(1, 7),
        weight=0.4,
    ),
    Event(
        name="falling_object",
        category="environment",
        display_name="Falling Object",
        description="An object falls from a table, making a crash. First experience of cause and effect.",
        sensory_channels=["hearing", "vision"],
        intensity=0.4,
        requires_parent=False,
        phase_range=(2, 5),
        weight=0.4,
    ),
    Event(
        name="peer_encounter",
        category="environment",
        display_name="Peer Encounter",
        description="Another child of similar age appears. First sight of 'someone like me'.",
        sensory_channels=["vision", "hearing"],
        intensity=0.5,
        requires_parent=False,
        phase_range=(5, 11),
        weight=0.5,
    ),
    Event(
        name="drawing_discovery",
        category="environment",
        display_name="Drawing Discovery",
        description="Hand grabs a crayon or brush, leaves marks on paper. They can change the world.",
        sensory_channels=["vision", "touch"],
        intensity=0.5,
        requires_parent=False,
        phase_range=(5, 9),
        weight=0.5,
    ),
    Event(
        name="story_heard",
        category="environment",
        display_name="Story Heard",
        description="Someone is telling a story — with characters, plot, and conflict.",
        sensory_channels=["hearing"],
        intensity=0.4,
        requires_parent=False,
        phase_range=(6, 11),
        weight=0.6,
    ),
]

# ============================================================
# Critical events — pause, wait for parent intervention
# ============================================================

CRITICAL_EVENTS = [
    Event(
        name="high_fever",
        category="critical",
        display_name="High Fever",
        description="The baby's temperature has spiked. Face flushed, spirit listless.",
        sensory_channels=["touch"],
        intensity=0.9,
        requires_parent=True,
        phase_range=(0, 7),
        weight=0.15,
        parent_choices=[
            {"action": "comfort", "display": "Hold and comfort gently", "effect": "Enhanced sense of safety"},
            {"action": "medical", "display": "Seek medical help immediately", "effect": "Learns that asking for help works"},
            {"action": "observe", "display": "Observe and wait", "effect": "Self-recovery awareness"},
        ],
    ),
    Event(
        name="prolonged_crying",
        category="critical",
        display_name="Prolonged Crying",
        description="The baby has been crying for over an hour. The nanny cannot soothe them.",
        sensory_channels=["hearing", "touch"],
        intensity=0.8,
        requires_parent=True,
        phase_range=(0, 4),
        weight=0.2,
        parent_choices=[
            {"action": "hold_and_rock", "display": "Hold and rock gently", "effect": "'Being responded to' → secure attachment foundation"},
            {"action": "let_cry", "display": "Let them cry it out", "effect": "Self-soothing ability / or feeling ignored"},
            {"action": "sing", "display": "Sing a lullaby", "effect": "Sound becomes a source of comfort"},
        ],
    ),
    Event(
        name="first_fall",
        category="critical",
        display_name="First Fall",
        description="The baby fell while trying to crawl or stand. Startled but not seriously hurt.",
        sensory_channels=["touch", "proprioception"],
        intensity=0.6,
        requires_parent=True,
        phase_range=(3, 5),
        weight=0.5,
        parent_choices=[
            {"action": "rush_over", "display": "Rush over and pick up", "effect": "'Falling = danger' memory reinforced"},
            {"action": "encourage", "display": "Encourage them to get up", "effect": "'I can recover' → resilience"},
            {"action": "calm_check", "display": "Calmly check for injuries", "effect": "'Falling isn't scary' → safe exploration"},
        ],
    ),
    Event(
        name="first_word_moment",
        category="critical",
        display_name="First Word",
        description="The baby uttered their first meaningful word — perhaps 'mama', 'dada', or a familiar object.",
        sensory_channels=["hearing"],
        intensity=0.7,
        requires_parent=True,
        phase_range=(5, 6),
        weight=0.9,
        parent_choices=[
            {"action": "celebrate", "display": "Celebrate and repeat the word", "effect": "Language = gets attention and response"},
            {"action": "teach_more", "display": "Teach more words", "effect": "Accelerates language development"},
            {"action": "gentle_smile", "display": "Smile and respond gently", "effect": "Language = natural communication"},
        ],
    ),
    Event(
        name="nightmare",
        category="critical",
        display_name="Nightmare",
        description="The baby woke screaming in the night. Clearly terrified, hard to soothe.",
        sensory_channels=["hearing", "touch"],
        intensity=0.8,
        requires_parent=True,
        phase_range=(3, 8),
        weight=0.25,
        parent_choices=[
            {"action": "hold_tight", "display": "Hold tight and reassure safety", "effect": "'Someone is there when scared' → secure base"},
            {"action": "light_on", "display": "Turn on the light", "effect": "'Seeing = safe' → visual dependence"},
            {"action": "stay_nearby", "display": "Stay nearby, let them calm down", "effect": "'I can recover from fear'"},
        ],
    ),
    Event(
        name="naming_ceremony",
        category="critical",
        display_name="Naming Ceremony",
        description="It's time to give this child a name.",
        sensory_channels=[],
        intensity=0.5,
        requires_parent=True,
        phase_range=(1, 6),
        weight=0.0,
        parent_choices=[
            {"action": "name", "display": "Give them a name", "effect": "Starting point of self-awareness"},
        ],
    ),
    Event(
        name="first_defiance",
        category="critical",
        display_name="First Defiance",
        description="The baby said 'no' for the first time — shaking head, pushing away, or speaking the word.",
        sensory_channels=["hearing"],
        intensity=0.6,
        requires_parent=True,
        phase_range=(6, 8),
        weight=0.7,
        parent_choices=[
            {"action": "respect", "display": "Respect their choice", "effect": "'My will matters' → autonomy"},
            {"action": "insist", "display": "Insist firmly", "effect": "'Rules override will' → compliance or rebellion"},
            {"action": "negotiate", "display": "Offer alternatives", "effect": "'After refusal, negotiation is possible' → negotiation ability"},
        ],
    ),
    Event(
        name="emotional_storm",
        category="critical",
        display_name="Emotional Storm",
        description="The baby erupted over something small — screaming, throwing things, rolling on the floor.",
        sensory_channels=["hearing", "touch"],
        intensity=0.8,
        requires_parent=True,
        phase_range=(7, 9),
        weight=0.6,
        parent_choices=[
            {"action": "validate", "display": "Kneel down: 'I know you're upset'", "effect": "Emotion acknowledged → emotional regulation"},
            {"action": "distract", "display": "Redirect attention", "effect": "'Avoid bad feelings' → avoidance strategy"},
            {"action": "boundary", "display": "Set calm but firm boundary", "effect": "'Emotions OK, but behavior has limits'"},
            {"action": "ignore", "display": "Wait it out in silence", "effect": "Self-regulation / or emotional suppression"},
        ],
    ),
    Event(
        name="first_lie",
        category="critical",
        display_name="First Lie",
        description="The baby told an obvious untruth to avoid punishment or get something.",
        sensory_channels=["hearing"],
        intensity=0.5,
        requires_parent=True,
        phase_range=(8, 11),
        weight=0.4,
        parent_choices=[
            {"action": "curious", "display": "Ask curiously: 'Really? What happened?'", "effect": "'Honesty can be guided, not feared'"},
            {"action": "confront", "display": "Point out the truth directly", "effect": "'Lies will be discovered' → honesty pressure"},
            {"action": "discuss_why", "display": "Discuss why they wanted to lie", "effect": "Understanding motive → moral reasoning"},
        ],
    ),
    Event(
        name="separation_test",
        category="critical",
        display_name="Separation Test",
        description="Parent needs to leave for a while. The baby faces their first prolonged absence.",
        sensory_channels=["vision", "hearing"],
        intensity=0.7,
        requires_parent=True,
        phase_range=(3, 7),
        weight=0.3,
        parent_choices=[
            {"action": "explain_return", "display": "Explain you'll return, then leave", "effect": "Predictable separation → secure attachment"},
            {"action": "sneak_away", "display": "Sneak away while distracted", "effect": "Unpredictable disappearance → anxious attachment"},
            {"action": "gradual", "display": "Start with short absences, then extend", "effect": "Gradual adaptation → separation tolerance"},
        ],
    ),
]

# ============================================================
# All events combined
# ============================================================

ALL_EVENTS = DAILY_EVENTS + ENVIRONMENT_EVENTS + CRITICAL_EVENTS

_EVENT_MAP = {e.name: e for e in ALL_EVENTS}


def get_event(name: str) -> Event | None:
    """Get an event by name."""
    return _EVENT_MAP.get(name)


def _compute_affinity(event: Event, identity) -> float:
    """
    Compute baby's affinity to an event — identity-modulated weight.

    High sensitivity channels → related events more likely to be "noticed".
    High arousal baseline → all event probabilities increase.

    Uses weighted average instead of max: a deaf baby won't trigger hearing events
    just because their vision is good.
    """
    sp = identity.sensory_profile

    # Sensory affinity: weighted average across all event channels
    if event.sensory_channels:
        channel_scores = [getattr(sp, ch, 0.5) for ch in event.sensory_channels]
        sensory_affinity = sum(channel_scores) / len(channel_scores)
    else:
        sensory_affinity = 0.5

    # Arousal modifier
    arousal_mod = {"high": 1.4, "moderate": 1.0, "low": 0.7}
    arousal = arousal_mod.get(identity.arousal_baseline, 1.0)

    return round(sensory_affinity * arousal, 3)


def roll_events(phase_index: int, identity=None,
                count_daily: int = 3, count_env: int = 2) -> dict:
    """
    Generate events for a phase, with identity-modulated weights.

    Returns:
        {"daily": [...], "environment": [...], "critical": [...],
         "traces": [...]}

    traces record each event's selection/rejection process for frontend display.
    """
    result: dict = {"daily": [], "environment": [], "critical": [], "traces": []}

    # Daily events: identity-modulated weights
    available_daily = [e for e in DAILY_EVENTS
                       if e.phase_range[0] <= phase_index <= e.phase_range[1]]
    if available_daily:
        if identity:
            weights = [e.weight * _compute_affinity(e, identity) for e in available_daily]
        else:
            weights = [e.weight for e in available_daily]
        chosen = random.choices(available_daily, weights=weights,
                                k=min(count_daily, len(available_daily)))
        result["daily"] = chosen

        for e in available_daily:
            affinity = _compute_affinity(e, identity) if identity else 1.0
            result["traces"].append({
                "category": "daily",
                "event_name": e.name,
                "event_display": e.display_name,
                "base_weight": e.weight,
                "affinity": affinity,
                "final_weight": round(e.weight * affinity, 3),
                "selected": e in chosen,
            })

    # Environment events: identity-modulated weights
    available_env = [e for e in ENVIRONMENT_EVENTS
                     if e.phase_range[0] <= phase_index <= e.phase_range[1]]
    if available_env:
        if identity:
            weights = [e.weight * _compute_affinity(e, identity) for e in available_env]
        else:
            weights = [e.weight for e in available_env]
        chosen = random.choices(available_env, weights=weights,
                                k=min(count_env, len(available_env)))
        result["environment"] = chosen

        for e in available_env:
            affinity = _compute_affinity(e, identity) if identity else 1.0
            result["traces"].append({
                "category": "environment",
                "event_name": e.name,
                "event_display": e.display_name,
                "base_weight": e.weight,
                "affinity": affinity,
                "final_weight": round(e.weight * affinity, 3),
                "selected": e in chosen,
            })

    # Critical events: independent roll, identity-modulated probability
    available_critical = [e for e in CRITICAL_EVENTS
                         if e.phase_range[0] <= phase_index <= e.phase_range[1]
                         and e.weight > 0]
    for event in available_critical:
        affinity = _compute_affinity(event, identity) if identity else 1.0
        prob = min(event.weight * 0.3 * affinity, 0.95)  # cap at 95%
        roll = random.random()
        hit = roll < prob
        if hit:
            result["critical"].append(event)
        result["traces"].append({
            "category": "critical",
            "event_name": event.name,
            "event_display": event.display_name,
            "base_weight": event.weight,
            "affinity": affinity,
            "probability": round(prob, 3),
            "roll": round(roll, 3),
            "selected": hit,
        })

    return result
