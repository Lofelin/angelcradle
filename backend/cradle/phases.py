"""
12 个成长阶段定义。

每个阶段包含：能力解锁、表达形式、脆弱窗口。
阶段不是时间轴，是能力检查点——有的婴儿快，有的慢。

[INPUT]: 无外部依赖
[OUTPUT]: PHASES, EXPRESSION_MODES, Phase 数据类
[POS]: cradle/ 的静态数据层，被 nanny.py 和 mind.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Phase:
    """一个成长阶段。"""
    index: int
    name: str                       # 阶段代号
    display_name: str               # 中文名
    age_range: str                  # 人类等效年龄
    age_days: tuple[int, int]       # (起始天, 结束天)
    description: str                # 阶段描述
    capabilities: list[str]         # 此阶段解锁的能力
    expression_mode: str            # 表达形式代号
    vulnerability: str              # 脆弱窗口描述
    sensory_focus: list[str]        # 此阶段最活跃的感官通道


# 表达形式：婴儿在每个阶段如何"说话"
EXPRESSION_MODES = {
    "cry_only": {
        "description": "Can only cry. Cry patterns (frequency, intensity, rhythm) reflect internal state.",
        "format": "Describe with movements and sounds only. No words. Only cries, body reactions, facial expressions.",
        "example": "*Body jolts rigid, limbs stiffen, then erupts into sharp sustained wailing, face turning red*",
    },
    "coo_and_gaze": {
        "description": "Cooing and gazing. Begins tracking with eyes, producing vowel sounds.",
        "format": "Mostly action descriptions, may include cooing sounds (ah, oo, mm), but no words. Gaze direction matters.",
        "example": "*Head slowly turns toward sound source, eyes widen, mouth opens with a soft 'ahhh—', arms wave toward the sound*",
    },
    "babble_and_reach": {
        "description": "Complex babbling and reaching. Syllable combinations appear, with rhythm.",
        "format": "Action descriptions + babble syllables (ba-ba, da-da, ma-ma etc. meaningless repetition), actively exploring with hands.",
        "example": "*Both hands grab the hanging toy, shaking hard, mouth going 'ba-da-ba' nonstop, suddenly lets go, freezes, then laughs*",
    },
    "gesture_and_point": {
        "description": "Pointing and gestures. Can point with index finger, combined with gaze to request attention.",
        "format": "Action descriptions + gestures + some babbling, beginning intentional vocalizations (using sounds to get attention).",
        "example": "*Index finger firmly points at the bird outside, turns back to look at you, urgent 'ah! ah!', points back*",
    },
    "first_words": {
        "description": "First words. Usually names and high-frequency nouns, one word at a time.",
        "format": "Single words + lots of action descriptions. Words may be mispronounced.",
        "example": "*Walks over carrying stuffed animal, holds it up to you: 'Doggy!' Then presses it against your leg, looking up expectantly*",
    },
    "two_word": {
        "description": "Two-word phrases. Noun+verb, simple combinations to express needs.",
        "format": "Two to three word phrases + action descriptions. Grammar incomplete but intent clear.",
        "example": "*Pulls your hand toward the door: 'Go play!' After being refused, sits down: 'Want... go...'*",
    },
    "sentence": {
        "description": "Full sentences. Can express cause-effect, time, emotions. Starts asking 'why'.",
        "format": "Simple sentences with grammatical structure. Lots of questions. Direct emotional expression.",
        "example": "'Why does the sun go home when it gets dark? Where is the sun's home? Can I go there?'",
    },
    "narrative": {
        "description": "Narrative ability. Can recount events, make up stories, role-play.",
        "format": "Multi-sentence paragraphs with narrative structure. Begins using metaphors (may misuse them). Can distinguish reality from imagination.",
        "example": "'Today that big dog looked at me, and I wasn't scared! Then it walked away. I think maybe it was scared of me too.'",
    },
    "reasoning": {
        "description": "Reasoning expression. Can understand rules, make analogies, express abstract concepts.",
        "format": "Complex sentences with logical connectors (because, so, if). Begins expressing hypotheticals.",
        "example": "'If I were a bird, I'd fly really really high up to look around, because things look smaller from above, right?'",
    },
    "independent": {
        "description": "Independent expression. Has own opinions, preferences, arguments. Can disagree.",
        "format": "Full paragraphs with points and arguments. Can express disagreement. Has self-awareness.",
        "example": "'I don't want to wear this shirt. Not because it's ugly, but because it makes me itchy. You don't have to like the one I picked, but my skin, I know.'",
    },
}


PHASES: list[Phase] = [
    Phase(
        index=0,
        name="neonatal",
        display_name="Neonatal",
        age_range="0-1个月",
        age_days=(0, 30),
        description="Only reflexes, can only cry, completely dependent on caregiver. The world is a blur of sensations.",
        capabilities=["startle_reflex", "sucking_reflex", "crying", "sleep_wake_cycle"],
        expression_mode="cry_only",
        vulnerability="All sensory channels are calibrating. Overstimulation can cause lasting sensitization.",
        sensory_focus=["touch", "hearing"],
    ),
    Phase(
        index=1,
        name="sensory_awakening",
        display_name="Sensory Awakening",
        age_range="1-3个月",
        age_days=(30, 90),
        description="Begins tracking sounds and light, social smile appears. The world starts to have direction.",
        capabilities=["social_smile", "visual_tracking", "sound_localization", "head_control"],
        expression_mode="coo_and_gaze",
        vulnerability="Initial window for attachment. Primary caregiver's response patterns begin shaping sense of security.",
        sensory_focus=["vision", "hearing"],
    ),
    Phase(
        index=2,
        name="body_discovery",
        display_name="Body Discovery",
        age_range="3-6个月",
        age_days=(90, 180),
        description="Discovers own hands, can grasp objects, learns to roll over. The body is the first tool.",
        capabilities=["grasping", "rolling", "hand_discovery", "laugh", "reach_for_objects"],
        expression_mode="babble_and_reach",
        vulnerability="First integration of body ability and cognition. Motor limitations (e.g. congenital defects) affect cognitive exploration paths.",
        sensory_focus=["touch", "proprioception"],
    ),
    Phase(
        index=3,
        name="object_permanence",
        display_name="Object Permanence",
        age_range="6-9个月",
        age_days=(180, 270),
        description="Understands objects still exist after disappearing. Begins stranger anxiety. The world has memory.",
        capabilities=["object_permanence", "stranger_anxiety", "sitting", "babbling_syllables"],
        expression_mode="gesture_and_point",
        vulnerability="Sensitive period for separation anxiety. How caregiver leaves profoundly impacts security model.",
        sensory_focus=["vision", "hearing"],
    ),
    Phase(
        index=4,
        name="locomotion",
        display_name="Locomotion",
        age_range="9-12个月",
        age_days=(270, 365),
        description="Crawls to explore the world, points at objects to request attention. Intentional behavior emerges.",
        capabilities=["crawling", "pointing", "intentional_action", "simple_cause_effect"],
        expression_mode="gesture_and_point",
        vulnerability="Balance of exploration and safety. Overprotection inhibits exploration drive, neglect leads to frequent injury memories.",
        sensory_focus=["proprioception", "vision", "touch"],
    ),
    Phase(
        index=5,
        name="first_word",
        display_name="First Word",
        age_range="12-18个月",
        age_days=(365, 540),
        description="Language sprouts, begins using tools. The first meaningful word is born.",
        capabilities=["first_words", "tool_use", "walking", "imitation"],
        expression_mode="first_words",
        vulnerability="Preparation for language explosion. Quality of language input directly affects vocabulary and expression patterns.",
        sensory_focus=["hearing", "vision"],
    ),
    Phase(
        index=6,
        name="language_explosion",
        display_name="Language Explosion",
        age_range="18-24个月",
        age_days=(540, 730),
        description="Two-word phrases emerge, pretend play appears, recognizes self in mirror.",
        capabilities=["two_word_sentences", "pretend_play", "self_recognition", "running"],
        expression_mode="two_word",
        vulnerability="Self-awareness sprouts. Naming ceremony has greatest significance in this phase.",
        sensory_focus=["hearing", "vision"],
    ),
    Phase(
        index=7,
        name="why_phase",
        display_name="Why Phase",
        age_range="2-3岁",
        age_days=(730, 1095),
        description="Full sentences, endless 'why' questions, frequent emotional storms. The world needs explanation.",
        capabilities=["full_sentences", "why_questions", "emotional_storms", "basic_counting"],
        expression_mode="sentence",
        vulnerability="Critical window for emotional regulation. How parents respond to emotional storms determines regulation strategy (suppression/expression/regulation).",
        sensory_focus=["hearing", "vision"],
    ),
    Phase(
        index=8,
        name="social_budding",
        display_name="Social Budding",
        age_range="3-4岁",
        age_days=(1095, 1460),
        description="Becomes aware of peers, role-play games, moral sense sprouts.",
        capabilities=["peer_awareness", "role_play", "moral_sense", "sharing_concept"],
        expression_mode="narrative",
        vulnerability="First learning of social rules. Rejection experiences form lasting social strategies.",
        sensory_focus=["hearing", "vision"],
    ),
    Phase(
        index=9,
        name="rule_understanding",
        display_name="Rule Understanding",
        age_range="4-5岁",
        age_days=(1460, 1825),
        description="Understands rules exist and begins testing boundaries. Knows 'should' but doesn't always comply.",
        capabilities=["rule_following", "boundary_testing", "negotiation", "basic_empathy"],
        expression_mode="reasoning",
        vulnerability="Tug-of-war between authority and autonomy. Whether rules are consistently enforced determines attitude toward rules (respect/fear/contempt).",
        sensory_focus=["hearing", "vision"],
    ),
    Phase(
        index=10,
        name="abstract_beginning",
        display_name="Abstract Beginning",
        age_range="5-6岁",
        age_days=(1825, 2190),
        description="Begins analogical thinking, understands time (yesterday/tomorrow), can do simple hypothetical reasoning.",
        capabilities=["analogy", "time_concept", "hypothetical_thinking", "reading_readiness"],
        expression_mode="reasoning",
        vulnerability="Cognitive leap period. Quality of abstract thinking affected by prior language foundation and exploration experience.",
        sensory_focus=["hearing", "vision"],
    ),
    Phase(
        index=11,
        name="independence",
        display_name="Independence",
        age_range="6-7岁",
        age_days=(2190, 2555),
        description="'I'll do it myself.' Has own opinions, can argue back, ready to enter the world.",
        capabilities=["independent_opinion", "self_advocacy", "complex_emotion", "future_planning"],
        expression_mode="independent",
        vulnerability="Final balance of independence and security. Overcontrol produces compliance or rebellion, appropriate letting go produces confidence.",
        sensory_focus=["hearing", "vision"],
    ),
]

# 进入世界的能力检查
WORLD_READINESS = {
    # 硬性条件 — 缺一不可
    "hard": {
        "language": "Can express needs and feelings in full sentences",
        "self_concept": "Knows who they are, has a name, can distinguish self from others",
        "theory_of_mind": "Understands others may have different thoughts and feelings",
        "emotional_regulation": "Can recover from moderate-intensity emotions without relying on parents",
    },
    # 软性条件 — 影响世界中的表现
    "soft": {
        "curiosity": "Actively explores the unknown",
        "social_skill": "Can initiate and maintain interactions",
        "resilience": "Recovery speed when facing setbacks",
        "independence": "Can make simple decisions independently",
    },
}
