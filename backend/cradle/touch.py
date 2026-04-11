"""
肢体互动动作定义。

父母可通过点击动作按钮与婴儿进行肢体互动，替代文字描述。
每个动作有阶段范围限制，确保动作适龄。

[INPUT]: 无外部依赖
[OUTPUT]: TOUCH_ACTIONS, get_available_actions()
[POS]: cradle/ 的静态数据层，被 api/cradle.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TouchAction:
    """一个肢体互动动作。"""
    key: str                # 唯一标识
    category: str           # 分类
    label_zh: str           # 中文名
    label_en: str           # 英文名
    emoji: str              # 图标
    phase_range: tuple[int, int]  # 适用阶段范围 (inclusive)
    description: str        # 给 LLM 的动作描述


# 按类别定义动作
TOUCH_ACTIONS: list[TouchAction] = [
    # ── 抚触类 ──
    TouchAction("stroke_head", "caress", "摸头", "Stroke head", "🤚", (0, 11),
                "Parent gently strokes the baby's head"),
    TouchAction("caress_face", "caress", "抚脸", "Caress face", "😊", (0, 11),
                "Parent softly caresses the baby's cheek"),
    TouchAction("rub_belly", "caress", "揉肚子", "Rub belly", "🫄", (0, 11),
                "Parent rubs the baby's belly in circles"),
    TouchAction("hold_hand", "caress", "握小手", "Hold hand", "🤝", (0, 11),
                "Parent holds the baby's tiny hand"),
    TouchAction("rub_feet", "caress", "揉小脚", "Rub feet", "🦶", (0, 11),
                "Parent gently massages the baby's feet"),

    # ── 拥抱类 ──
    TouchAction("pick_up", "embrace", "抱起来", "Pick up", "🤱", (0, 11),
                "Parent picks the baby up and holds them"),
    TouchAction("cuddle", "embrace", "搂在怀里", "Cuddle", "🫂", (0, 11),
                "Parent cuddles the baby close to their chest"),
    TouchAction("lift_high", "embrace", "举高高", "Lift high", "🙌", (2, 11),
                "Parent lifts the baby high in the air playfully"),
    TouchAction("rock", "embrace", "轻轻摇", "Rock gently", "🌙", (0, 8),
                "Parent rocks the baby gently back and forth"),

    # ── 亲昵类 ──
    TouchAction("kiss_forehead", "affection", "亲额头", "Kiss forehead", "😘", (0, 11),
                "Parent kisses the baby's forehead tenderly"),
    TouchAction("kiss_cheek", "affection", "亲脸蛋", "Kiss cheek", "💋", (0, 11),
                "Parent kisses the baby's cheek"),
    TouchAction("nuzzle", "affection", "蹭鼻子", "Nuzzle nose", "👃", (0, 11),
                "Parent nuzzles their nose against the baby's"),
    TouchAction("blow_raspberry", "affection", "吹肚皮", "Blow raspberry", "😝", (1, 9),
                "Parent blows a raspberry on the baby's belly"),

    # ── 安抚类 ──
    TouchAction("pat_back", "soothe", "拍背", "Pat back", "🫳", (0, 11),
                "Parent pats the baby's back gently and rhythmically"),
    TouchAction("pat_bottom", "soothe", "拍屁股", "Pat bottom", "👋", (0, 6),
                "Parent gently pats the baby's bottom to soothe"),
    TouchAction("swaddle", "soothe", "裹紧抱抱", "Swaddle", "🧣", (0, 3),
                "Parent wraps the baby snugly and holds them"),
    TouchAction("wipe_tears", "soothe", "擦眼泪", "Wipe tears", "🥺", (3, 11),
                "Parent gently wipes the baby's tears"),

    # ── 游戏类 ──
    TouchAction("tickle", "play", "挠痒痒", "Tickle", "🤭", (2, 11),
                "Parent tickles the baby playfully"),
    TouchAction("peekaboo", "play", "躲猫猫", "Peekaboo", "🙈", (1, 8),
                "Parent plays peekaboo with the baby"),
    TouchAction("clap_together", "play", "拍手手", "Clap hands", "👏", (2, 9),
                "Parent claps hands together with the baby"),
    TouchAction("dance_together", "play", "跳舞", "Dance", "💃", (4, 11),
                "Parent dances with the baby, holding their hands"),
    TouchAction("piggyback", "play", "骑马马", "Piggyback", "🐴", (4, 11),
                "Parent gives the baby a piggyback ride"),
    TouchAction("chase", "play", "追着跑", "Chase", "🏃", (5, 11),
                "Parent chases the baby playfully around the room"),
]

# 类别信息
TOUCH_CATEGORIES = {
    "caress": {"label_zh": "抚触", "label_en": "Caress", "emoji": "🤚"},
    "embrace": {"label_zh": "拥抱", "label_en": "Embrace", "emoji": "🤱"},
    "affection": {"label_zh": "亲昵", "label_en": "Affection", "emoji": "😘"},
    "soothe": {"label_zh": "安抚", "label_en": "Soothe", "emoji": "🫳"},
    "play": {"label_zh": "游戏", "label_en": "Play", "emoji": "🤭"},
}


def get_available_actions(phase: int) -> dict:
    """获取指定阶段可用的肢体动作，按类别分组。"""
    result = {}
    for action in TOUCH_ACTIONS:
        if action.phase_range[0] <= phase <= action.phase_range[1]:
            cat = action.category
            if cat not in result:
                cat_info = TOUCH_CATEGORIES[cat]
                result[cat] = {
                    "label_zh": cat_info["label_zh"],
                    "label_en": cat_info["label_en"],
                    "emoji": cat_info["emoji"],
                    "actions": [],
                }
            result[cat]["actions"].append({
                "key": action.key,
                "label_zh": action.label_zh,
                "label_en": action.label_en,
                "emoji": action.emoji,
            })
    return result
