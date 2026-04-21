"""
主动需求系统 -- 宝宝内心驱动的需求发起 + 限时响应 + 保姆降级。

LLM 作为宝宝的潜意识判断是否发起需求（复用 heartbeat 引擎），
规则层只做频率门卫。保姆降级为纯模板处理。

[INPUT]: 依赖 heartbeat.py（引擎 + InitiativeState）、cradle/heartbeat_provider.py（CradleMonologueProvider）、cradle/mind.py（LLM 评估函数）
[OUTPUT]: NeedUrgency, URGENCY_TIMEOUT, TRIGGER_URGENCY, TRIGGER_LABELS, evaluate_need(), pick_nanny_response()
[POS]: cradle 子模块——摇篮期主动需求政策，被 scheduler/ 消费
[PROTOCOL]: 变更时更新此头部，然后检查 cradle/CLAUDE.md
"""

from __future__ import annotations

import logging
import random
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================
# 需求紧急度分类
# ============================================================

class NeedUrgency(str, Enum):
    PHYSIOLOGICAL = "physiological"   # 生理：2 min
    EMOTIONAL = "emotional"           # 情感：3 min
    SOCIAL = "social"                 # 社交：5 min


URGENCY_TIMEOUT: dict[NeedUrgency, int] = {
    NeedUrgency.PHYSIOLOGICAL: 120,
    NeedUrgency.EMOTIONAL: 180,
    NeedUrgency.SOCIAL: 300,
}

# trigger -> urgency 映射
TRIGGER_URGENCY: dict[str, NeedUrgency] = {
    # 生理需求
    "hunger":      NeedUrgency.PHYSIOLOGICAL,
    "sleepy":      NeedUrgency.PHYSIOLOGICAL,
    "wet_diaper":  NeedUrgency.PHYSIOLOGICAL,
    "soiled_diaper": NeedUrgency.PHYSIOLOGICAL,
    "gas_colic":   NeedUrgency.PHYSIOLOGICAL,
    "teething":    NeedUrgency.PHYSIOLOGICAL,
    "too_hot":     NeedUrgency.PHYSIOLOGICAL,
    "too_cold":    NeedUrgency.PHYSIOLOGICAL,
    "hiccup":      NeedUrgency.PHYSIOLOGICAL,
    "pain":        NeedUrgency.PHYSIOLOGICAL,
    # 情感需求
    "fear":        NeedUrgency.EMOTIONAL,
    "lonely":      NeedUrgency.EMOTIONAL,
    "boundary":    NeedUrgency.EMOTIONAL,
    "overstimulated": NeedUrgency.EMOTIONAL,
    # 社交需求
    "curious":     NeedUrgency.SOCIAL,
    "bored":       NeedUrgency.SOCIAL,
    "play":        NeedUrgency.SOCIAL,
    "share":       NeedUrgency.SOCIAL,
    "secret":      NeedUrgency.SOCIAL,
    "autonomy":    NeedUrgency.SOCIAL,
}

# trigger -> 人类可读标签（前端消费，翻译在 i18n 层）
TRIGGER_LABELS: dict[str, str] = {
    "hunger": "Hungry",
    "sleepy": "Sleepy",
    "wet_diaper": "Wet diaper",
    "soiled_diaper": "Dirty diaper",
    "gas_colic": "Tummy ache",
    "teething": "Teething pain",
    "too_hot": "Too hot",
    "too_cold": "Too cold",
    "hiccup": "Hiccups",
    "pain": "Pain",
    "fear": "Scared",
    "lonely": "Lonely",
    "boundary": "Needs space",
    "overstimulated": "Overstimulated",
    "curious": "Curious",
    "bored": "Bored",
    "play": "Wants to play",
    "share": "Wants to share",
    "secret": "Has a secret",
    "autonomy": "Wants independence",
}


# ============================================================
# 保姆降级模板
# ============================================================

# ============================================================
# 组合式保姆降级响应生成器
# ============================================================
# 角色 × 动作 × 结果 三段拼接
# 组合空间: ~4 角色 × ~4 动作/trigger × ~3 结果/trigger ≈ 数千种

# 角色→称谓变体
_ACTORS = {
    "nanny":       ["The nanny", "The caretaker", "The babysitter", "The helper", "The kind nanny"],
    "grandparent": ["Grandma", "Grandpa", "Grandmother", "Grandfather", "Nana", "Pop-pop"],
    "sibling":     ["The older sibling", "Big brother", "Big sister", "The eldest child", "The older one"],
    "parent":      ["Mom", "Dad", "Mama", "Papa", "Mother", "Father"],
    "self":        ["The baby", "The little one", "The child"],
}

# ── 身体信号（P1 维度）——宝宝在需求发生时的可观测行为 ──
_SIGNALS: dict[str, list[str]] = {
    "hunger": [
        "Rooting, turning the head side to side",
        "Sucking on fists frantically",
        "Smacking lips and making chewing motions",
        "Fussing that escalates to a rhythmic cry",
        "Mouth opening wide every time something passes near",
    ],
    "sleepy": [
        "Rubbing eyes with tiny fists",
        "Yawning repeatedly, eyelids drooping",
        "Pulling at ears and getting cranky",
        "Staring blankly, losing interest in everything",
        "Arching backward and fussing in short bursts",
    ],
    "wet_diaper": [
        "Squirming and kicking legs restlessly",
        "Pulling at the diaper area",
        "Whimpering with a scrunched-up face",
        "Fidgeting and refusing to settle in any position",
        "Sudden fussing after a period of calm",
    ],
    "soiled_diaper": [
        "Face turning red with effort, then a sudden wail",
        "Grunting and drawing knees up to the chest",
        "Strong unpleasant smell filling the room",
        "Squirming uncomfortably, arching the back",
        "Fussing intensely, legs kicking outward",
    ],
    "gas_colic": [
        "Drawing both knees tight against the belly",
        "Back arching sharply, face contorted",
        "Belly taut and distended to the touch",
        "High-pitched, inconsolable screaming in waves",
        "Clenching fists and stiffening the whole body",
    ],
    "teething": [
        "Gnawing on anything within reach",
        "Drool soaking through the bib",
        "One cheek flushed red, the other pale",
        "Rubbing the gums with a finger and whining",
        "Low-grade fussing that won't stop no matter what",
    ],
    "too_hot": [
        "Skin flushed and damp with sweat",
        "Kicking off the blanket repeatedly",
        "Restless, refusing to stay swaddled",
        "Hair damp at the nape of the neck",
        "Irritable, panting slightly",
    ],
    "too_cold": [
        "Hands and feet cool to the touch",
        "Skin pale or slightly mottled",
        "Curling into a tight ball",
        "Shivering faintly, lips a bit bluish",
        "Fussing that stops when held close for warmth",
    ],
    "hiccup": [
        "Rhythmic little jolts shaking the whole body",
        "A surprised look after each hiccup",
        "Tiny 'hic' sounds every few seconds",
        "Squirming between hiccups, mildly annoyed",
    ],
    "pain": [
        "A sharp, sudden cry — different from the usual fussing",
        "Guarding a specific body part, flinching when touched",
        "Face crumpled, tears streaming",
        "Refusing to move, body tense and still",
        "High-pitched wailing that doesn't pause for breath",
    ],
    "fear": [
        "Eyes wide, body frozen in place",
        "Clinging tightly, refusing to let go",
        "Lower lip trembling, breath held",
        "Startled — arms flung out, then pulled in tight",
        "Burying face into the nearest soft surface",
    ],
    "lonely": [
        "Looking around the room with searching eyes",
        "Reaching arms toward the door where someone left",
        "Making small sounds as if calling out",
        "Holding a toy but looking past it",
        "Crawling toward familiar voices",
    ],
    "boundary": [
        "Turning away firmly when approached",
        "Pushing hands against whoever is too close",
        "Frowning and going quiet",
        "Crossing tiny arms and looking down",
    ],
    "overstimulated": [
        "Covering ears or turning away from noise",
        "Gaze avoidance — looking at the ceiling or a blank wall",
        "Jerky, disorganized movements",
        "Crying that starts suddenly in a busy environment",
        "Arching away from lights and sounds",
    ],
    "curious": [
        "Staring intently at something new",
        "Reaching toward an unfamiliar object",
        "Tilting head to one side, studying",
        "Pointing and making inquisitive sounds",
    ],
    "bored": [
        "Listless, staring at nothing",
        "Dropping toys immediately after picking them up",
        "Sighing — yes, even babies sigh",
        "Fussing without any clear reason",
    ],
    "play": [
        "Bouncing with energy, eyes bright",
        "Banging objects together and laughing",
        "Offering a toy to whoever is nearby",
        "Squealing and waving arms with excitement",
    ],
    "share": [
        "Holding something up and looking at someone expectantly",
        "Babbling with animated gestures",
        "Pointing at something and turning back to check if anyone saw",
    ],
    "secret": [
        "Sneaking a glance around before doing something",
        "Hiding an object behind the back with a sly grin",
        "Whispering to a stuffed animal",
    ],
    "autonomy": [
        "Pushing away the helping hand",
        "Grabbing the spoon and refusing to give it back",
        "Shaking head 'no' with fierce determination",
        "Attempting a task alone, ignoring all offers",
    ],
}

# trigger → 每个角色可用的动作片段
_ACTIONS: dict[str, dict[str, list[str]]] = {
    "hunger": {
        "caregiver": [
            "warmed a bottle and fed the baby",
            "prepared some mashed food and spooned it in patiently",
            "offered a quick snack from the kitchen",
            "heated some milk and held the baby close while feeding",
            "made warm cereal and fed it carefully, spoon by spoon",
            "cut up some soft fruit into tiny pieces and offered them one by one",
            "stirred some warm porridge and blew on each spoonful before offering",
            "brought over a sippy cup of warm milk",
            "peeled a banana and broke off small pieces",
            "mixed a bit of rice with broth and fed it slowly",
        ],
        "self": [
            "found a teething biscuit and gnawed on it",
            "sucked on tiny fists, waiting",
            "chewed on a soft toy until the hunger passed",
            "reached for a cracker left on the tray and nibbled it",
        ],
    },
    "pain": {
        "caregiver": [
            "picked the baby up and gently rubbed the sore spot",
            "checked for bumps, found nothing serious, and soothed with soft words",
            "hummed a familiar tune while rocking the baby gently",
            "said 'Let me see, let me see' in a calm voice",
            "blew on the tiny fingers and distracted the baby with a funny face",
            "pressed a cool cloth gently against the bump",
            "kissed the sore spot and whispered 'All better now'",
            "held the baby upright and rubbed circles on the back",
            "offered a teething ring to chew on for comfort",
            "gently bounced the baby on one knee until the crying softened",
        ],
        "self": [
            "whimpered for a moment, then got distracted by something shiny",
            "rubbed the sore spot with a tiny hand and moved on",
            "cried briefly, then noticed a toy and forgot the pain",
            "held the hurt finger close and rocked side to side",
        ],
    },
    "sleepy": {
        "caregiver": [
            "laid the baby in the crib and patted the back in a slow rhythm",
            "dimmed the lights and whispered a short lullaby",
            "swaddled the baby snugly and rocked the cradle",
            "hummed an old lullaby until the baby's eyes finally closed",
            "walked slowly around the room, holding the baby against the chest, until sleep came",
            "placed a warm hand on the baby's tummy and counted soft breaths",
            "turned on a white noise machine and adjusted the blanket",
            "sat in the rocking chair and rocked in a steady rhythm",
            "stroked the baby's forehead with one finger, over and over",
            "pulled the curtains shut and murmured 'Shhh, sleep now'",
        ],
        "self": [
            "yawned, curled up, and drifted off",
            "rubbed tiny eyes and slowly fell asleep hugging a blanket",
            "fought sleep for a while, then surrendered mid-yawn",
            "found a cozy corner, tucked into a ball, and was gone",
        ],
    },
    "fear": {
        "caregiver": [
            "held the baby close, patting the back and whispering 'It's okay'",
            "turned on a soft nightlight and stayed nearby until the shaking stopped",
            "covered the baby's ears gently and hummed over the scary noise",
            "wrapped the baby in a blanket and said 'Nothing to worry about'",
            "made a silly face to distract from the fright",
            "held both tiny hands and looked into the baby's eyes steadily",
            "pointed at the scary thing and said 'See? It's just a shadow'",
            "sang a familiar song loudly enough to drown out the noise",
            "rocked the baby while walking away from whatever caused the fear",
            "sat on the floor so they were at the same level and stayed calm",
        ],
        "self": [
            "clutched the favorite toy tighter and the trembling slowly stopped",
            "hid under the blanket and peeked out cautiously",
            "pressed against the wall and watched until the scary thing went away",
            "closed both eyes tight and waited for the world to be safe again",
        ],
    },
    "lonely": {
        "caregiver": [
            "sat beside the baby and chatted about nothing in particular",
            "picked the baby up and carried it to where the family was",
            "brought a stuffed animal and propped it next to the baby",
            "came over and just sat quietly — the presence was enough",
            "called out from the next room so the baby knew someone was near",
            "waved from across the room and the baby waved back",
            "moved the playmat to the kitchen so the baby could watch dinner prep",
            "put on a familiar voice recording and the baby perked up",
        ],
        "self": [
            "hugged a favorite toy tightly and the loneliness faded a little",
            "babbled to an imaginary friend for a while",
            "crawled to the doorway and waited, watching for someone to appear",
            "lined up all the stuffed animals and pretended they were company",
        ],
    },
    "play": {
        "caregiver": [
            "pulled out some blocks and built a wobbly tower together",
            "made animal sounds with hand puppets, earning giggles",
            "blew soap bubbles and the baby reached for every one",
            "got on the floor and rolled a ball back and forth",
            "started a game of peek-a-boo that went on for minutes",
            "stacked rings on a pole and cheered each successful placement",
            "drew circles in the air and the baby tried to copy them",
            "hid a toy under a cup and let the baby find it — three times",
            "made a tunnel with legs and the baby crawled through, delighted",
            "drummed on a pot with a spoon and the baby joined in",
        ],
        "self": [
            "found a crinkly wrapper and spent a happy while crinkling it",
            "stacked cups, knocked them down, stacked again — content",
            "discovered a cardboard box and climbed in and out repeatedly",
            "chased a dust bunny across the floor on hands and knees",
            "spun a wheel on an overturned toy car, mesmerized",
        ],
    },
    "share": {
        "caregiver": [
            "knelt down, made eye contact, and listened carefully",
            "repeated back what the baby said, showing it was heard",
            "nodded along and asked 'And then what happened?'",
            "listened to the babbling and responded as if it were a real story",
            "clapped after the baby's monologue, like an appreciative audience",
            "leaned in close and said 'Tell me everything'",
            "pointed at the same thing the baby was pointing at and named it",
            "made an exaggerated surprised face at the right moment",
        ],
        "self": [
            "babbled to a stuffed bear, paused, then babbled some more — a full conversation",
            "pointed at things and narrated in a private language",
            "held up a found object to show an empty room, then admired it alone",
            "talked to a reflection in the window, animated and serious",
        ],
    },
    "curious": {
        "caregiver": [
            "carried the baby to the window and pointed at things outside",
            "handed over a safe object to explore — texture, weight, sound",
            "opened a picture book and let the baby turn the pages",
            "showed how a wind-up toy worked, winding it again and again",
            "lifted the baby up high to see the top of a shelf",
            "turned a flashlight on and off, letting the baby track the beam",
            "brought over a jar of colorful buttons to sort through",
            "let the baby touch ice for the first time — the face was priceless",
        ],
        "self": [
            "picked up a wooden spoon and banged it on everything nearby",
            "opened and closed a cabinet door twelve times, fascinated by the click",
            "examined a leaf from every angle, turning it over and over",
            "put a hand in water and watched the ripples spread",
            "peeled a sticker halfway off and stuck it back, again and again",
        ],
    },
    "bored": {
        "caregiver": [
            "put on some gentle music and swayed with the baby",
            "brought out a new toy from the cupboard — instant interest",
            "took the baby outside for a change of scenery",
            "started clapping a rhythm, and the baby tried to clap along",
            "opened a window and let the breeze blow in",
            "scattered some safe objects on the floor for free exploration",
            "flipped through a picture book, pointing and naming",
            "moved to a different room — novelty restored",
        ],
        "self": [
            "rolled over, found a dust mote in a sunbeam, and watched it float",
            "discovered its own toes and spent a while grabbing at them",
            "pulled every tissue out of the box, one by one, fascinated",
            "banged two blocks together and listened to the sound change",
            "dropped a spoon off the high chair and listened to it clatter — five times",
        ],
    },
    "secret": {
        "caregiver": [
            "noticed the sneaky look but pretended not to see",
            "glanced over, saw the hidden object, and winked",
        ],
        "self": [
            "tucked something behind a pillow with a sly little smile",
            "whispered into a stuffed animal's ear — a private matter",
            "hid under a blanket, giggling at the invisible secret",
            "carried a small treasure to a corner and sat on it",
            "put a hand over something and looked around to make sure no one saw",
        ],
    },
    "boundary": {
        "caregiver": [
            "noticed the frown and stepped back, giving some space",
            "said 'I'll be right here when you're ready' and waited",
            "stopped the activity and let the baby decide what to do next",
            "recognized the look and quietly moved to the other side of the room",
            "put the rejected toy down without comment",
            "lowered the volume and softened the energy in the room",
            "said 'Okay, your choice' and respected the decision",
            "took a step back and busied themselves nearby, not hovering",
        ],
        "self": [
            "pushed the toy away firmly and sat alone for a moment",
            "turned away and stared at the wall, needing a minute",
            "shook the head 'no' and crossed tiny arms — message clear",
            "crawled to a quiet corner and sat with back to the room",
        ],
    },
    "autonomy": {
        "caregiver": [
            "watched from nearby, ready but not interfering, as the baby figured it out",
            "offered help once, was refused, and smiled while stepping back",
            "said 'You can do it!' from across the room — somehow that was enough",
            "hovered a hand close but didn't touch, letting the baby lead",
            "clapped when the task was done, celebrating the independence",
            "narrated the attempt: 'You're doing it! Almost there!'",
        ],
        "self": [
            "tried to put on a sock alone — it ended up on a hand, but the effort was real",
            "insisted on holding the spoon and got food mostly in the right direction",
            "crawled toward the goal with fierce determination, ignoring all offers of help",
            "pulled itself up on the table edge, wobbled, and grinned with pride",
            "pushed the helping hand away and tried again, and this time it worked",
            "carried a toy across the room with both hands, refusing assistance",
        ],
    },
    # ── 新增生理 trigger ──
    "wet_diaper": {
        "caregiver": [
            "checked the diaper, found it soaked, and changed it quickly",
            "laid the baby on the changing mat and swapped in a dry diaper",
            "noticed the squirming, felt the diaper, and whisked it away",
            "cleaned up, applied some cream, and snapped the fresh diaper in place",
            "hummed a little tune during the diaper change to keep things calm",
        ],
        "self": [
            "tugged at the diaper uncomfortably until someone noticed",
            "fussed and kicked until the dampness was dealt with",
        ],
    },
    "soiled_diaper": {
        "caregiver": [
            "caught a whiff, checked, and started the cleanup",
            "carried the baby to the changing table and handled the situation efficiently",
            "wrinkled nose, grabbed the wipes, and got to work",
            "cleaned up thoroughly, applied barrier cream, and dressed the baby fresh",
            "opened the window, changed the diaper, and the world was pleasant again",
        ],
        "self": [
            "cried until the discomfort was impossible to ignore",
        ],
    },
    "gas_colic": {
        "caregiver": [
            "held the baby upright and patted the back in gentle circles",
            "bicycled the tiny legs slowly to help release the gas",
            "placed a warm hand on the tummy and applied gentle pressure",
            "laid the baby across the lap, tummy-down, and rubbed the back",
            "tried the 'colic hold' — face-down along the forearm — and it helped",
            "gave gripe water and waited for the burp that would fix everything",
        ],
        "self": [
            "squirmed and grunted until the gas finally passed",
            "drew knees up, strained, and then relaxed with a small sigh",
        ],
    },
    "teething": {
        "caregiver": [
            "offered a cold teething ring to chew on",
            "rubbed the sore gums gently with a clean finger",
            "gave a frozen washcloth to gnaw on",
            "applied a tiny bit of teething gel to the swollen area",
            "distracted with a new toy while the gum pain subsided",
        ],
        "self": [
            "chewed on the crib rail with fierce determination",
            "gnawed on a fist and drooled everywhere",
            "found a cold spoon and pressed it against the gums",
        ],
    },
    "too_hot": {
        "caregiver": [
            "removed a layer of clothing and the fussing stopped almost immediately",
            "turned on the fan and moved the baby to a cooler spot",
            "dabbed a cool cloth on the forehead and neck",
            "opened a window to let fresh air circulate",
            "swapped the thick blanket for a light cotton one",
        ],
        "self": [
            "kicked off the blanket and spread out, seeking cool air",
        ],
    },
    "too_cold": {
        "caregiver": [
            "wrapped another layer around the baby and held close for warmth",
            "tucked the blanket tighter and rubbed the cold hands",
            "moved the baby away from the drafty window",
            "put on warm socks and a little hat",
            "held the baby against a warm chest until the shivering stopped",
        ],
        "self": [
            "curled into a tight ball and whimpered until warmth arrived",
        ],
    },
    "hiccup": {
        "caregiver": [
            "held the baby upright and waited patiently for the hiccups to pass",
            "offered a few sips of water from a bottle",
            "gently rubbed the back while the little body jolted",
            "distracted with a toy — the hiccups stopped mid-play",
        ],
        "self": [
            "hiccupped a few more times, looked confused, and then it just stopped",
            "burped once, loudly, and the hiccups vanished",
        ],
    },
    "overstimulated": {
        "caregiver": [
            "carried the baby to a quiet, dim room",
            "turned off the music and lowered the lights",
            "held the baby close with a hand over the eyes, blocking the chaos",
            "sat in the rocking chair in silence, just breathing together",
            "removed the noisy toy and replaced it with a soft blanket",
        ],
        "self": [
            "turned away from the noise and closed both eyes",
            "covered ears with tiny hands and went still",
        ],
    },
}

# 结果片段——按 trigger 类别分组
_OUTCOMES = {
    "physiological": [
        "The fussing stopped.",
        "Calm returned.",
        "Quiet settled in.",
        "The crying faded to soft breathing.",
        "Peace, at last.",
        "A tiny burp, then silence.",
        "The little body relaxed.",
        "Breathing slowed to a gentle rhythm.",
        "Comfort found.",
        "The need was met, simply and completely.",
        "A full tummy and heavy eyelids.",
        "The hiccups faded and warmth spread.",
        "Content at last, the tiny mouth stopped searching.",
        "One last whimper, then nothing but peace.",
        "The body unclenched, finally at ease.",
    ],
    "emotional": [
        "A small sigh of relief.",
        "The tension melted away.",
        "Things felt safe again.",
        "A wobbly smile appeared.",
        "The world felt a little less scary.",
        "The trembling stopped.",
        "Shoulders dropped, jaw unclenched.",
        "A deep breath in, a slow breath out.",
        "The storm passed as quickly as it came.",
        "Trust, quietly reinforced.",
        "The tears dried before they reached the chin.",
        "A hand reached out and held on tight.",
        "The heartbeat slowed to match the calm around it.",
        "Something invisible was repaired.",
        "Safety, like a warm blanket, settled in.",
    ],
    "social": [
        "A moment of connection.",
        "That seemed to be enough.",
        "Satisfaction, for now.",
        "The restlessness settled.",
        "Something was learned.",
        "A small nod of understanding.",
        "The curious itch was scratched.",
        "Not perfect, but good enough.",
        "A tiny step forward.",
        "The world got a little bigger today.",
        "A new favorite thing was discovered.",
        "The attention span stretched a little further than before.",
        "Independence, one wobbly step at a time.",
        "A proud moment, witnessed or not.",
        "The gap between wanting and doing got smaller.",
    ],
}


def _generate_nanny_text(trigger: str, role: str) -> str:
    """规则组合生成一条降级响应文本：signal + actor + action + outcome。"""
    actions = _ACTIONS.get(trigger, _ACTIONS.get("play", {}))
    urgency = TRIGGER_URGENCY.get(trigger, NeedUrgency.SOCIAL)

    # 选身体信号
    signals = _SIGNALS.get(trigger, [])
    signal = random.choice(signals) if signals else ""

    # 选动作
    if role == "self":
        action_pool = actions.get("self", ["waited patiently"])
    else:
        action_pool = actions.get("caregiver", ["took care of it"])
    action = random.choice(action_pool)

    # 选角色称谓
    actor = random.choice(_ACTORS.get(role, ["The nanny"]))

    # 选结果
    outcome = random.choice(_OUTCOMES.get(urgency.value, _OUTCOMES["social"]))

    # 拼接：signal. actor action. outcome
    if signal:
        return f"{signal}. {actor} {action}. {outcome}"
    return f"{actor} {action}. {outcome}"


# ============================================================
# 频率控制
# ============================================================

# 两次需求之间的最小模拟天数间隔
MIN_NEED_INTERVAL_DAYS = 2


# ============================================================
# 需求评估（LLM 驱动）
# ============================================================

def evaluate_need(state, day: int) -> dict | None:
    """
    让 LLM 作为宝宝的潜意识，判断此刻是否有需求。

    规则层只做频率门卫，LLM 决定要不要发起、发起什么、用什么表达。
    同步函数（在 asyncio.to_thread 中调用）。

    返回: {"trigger", "urgency", "timeout_sec", "expression", "behavior_type", "intent_id", "parent_hint"} 或 None
    """
    from heartbeat import evaluate_heartbeat, frequency_gate
    from cradle.heartbeat_provider import CradleMonologueProvider
    from cradle.mind import generate_heartbeat_evaluation, generate_ignored_reaction

    ini = state.initiative

    # 1. 有 pending 需求未处理，不发起新的
    if ini.pending_initiative_id:
        return None

    # 2. 频率门卫（2min 绝对间隔 + 60s 互动后冷却）
    if not frequency_gate(ini):
        return None

    # 3. sim days 维度冷却
    if ini.last_initiative_ts > 0:
        last_need_day = int(ini.last_initiative_ts)  # 存的是 sim_day 标记
        if day - last_need_day < MIN_NEED_INTERVAL_DAYS:
            return None

    # 4. 调用 heartbeat 引擎（LLM 判断）
    provider = CradleMonologueProvider()
    result = evaluate_heartbeat(
        state, provider, ini,
        generate_heartbeat_evaluation,
        generate_ignored_reaction,
    )

    # 5. 如果 LLM 判定有主动行为，转换为需求格式
    if result and result.get("initiative"):
        init = result["initiative"]
        trigger = init.get("trigger", "curious")
        urgency = TRIGGER_URGENCY.get(trigger, NeedUrgency.SOCIAL)

        # 多模态表达：LLM 可能返回 dict 或 string
        expr_raw = init.get("expression", "")
        if isinstance(expr_raw, dict):
            expression = expr_raw.get("vocalization", "") or expr_raw.get("signal", "")
            signal = expr_raw.get("signal", "")
            facial = expr_raw.get("facial", "")
            body = expr_raw.get("body", "")
        else:
            expression = expr_raw
            signal = ""
            facial = ""
            body = ""

        return {
            "trigger": trigger,
            "urgency": urgency,
            "timeout_sec": URGENCY_TIMEOUT[urgency],
            "expression": expression,
            "signal": signal,
            "facial": facial,
            "body": body,
            "behavior_type": init.get("behavior_type", "verbal"),
            "intent_id": init.get("intent_id", ""),
            "parent_hint": init.get("parent_hint", ""),
        }

    return None


def pick_nanny_response(trigger: str, caregivers: dict) -> dict:
    """规则组合生成降级响应，按实际照护者角色加权选择。"""
    # 收集实际存在的角色
    existing_roles = set()
    for cg in caregivers.values():
        existing_roles.add(cg.role)
    existing_roles.add("self")  # 宝宝自己总可用
    existing_roles.add("nanny")  # 保姆总可用

    # 按权重选角色：caregiver 角色优先，self 次之
    # social/secret/autonomy 类 trigger 偏向 self
    self_triggers = {"secret", "autonomy", "curious", "bored"}
    if trigger in self_triggers and random.random() < 0.6:
        role = "self"
    else:
        caregiver_roles = [r for r in existing_roles if r != "self"]
        role = random.choice(caregiver_roles) if caregiver_roles else "self"

    text = _generate_nanny_text(trigger, role)
    return {"text": text, "role": role}
