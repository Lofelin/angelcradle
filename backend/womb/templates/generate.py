"""
离线模板生成器：调用 DeepSeek-V3 批量生成高质量叙事模板，落库到 templates/*.json。

设计原则：
  1. 增量生成——已有模板作为"去重参考"发给 LLM，避免重复
  2. 质量闸门——长度/JSON 格式/占位符/相似度校验，不合格整批重跑
  3. 一次性——跑一次花几美元，永久复用

运行方式：
  cd backend
  python -m womb.templates.generate --dim birth/first_cry_onset --arousal high --count 30

[INPUT]: DeepSeek API key (DEEPSEEK_API_KEY)
[OUTPUT]: templates/{dim}.json 增量落盘
[POS]: womb/templates/ 的离线生成工具，仅构建期执行
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from llm import call_llm, create_client, get_model, parse_json

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent


# ============================================================
# 维度配置：每个模板池的 meta-prompt 描述
# ============================================================

# first_cry 三段拼接：onset(启动时机) × quality(哭声质感) × body(身体反应)
# 每段按 arousal 分三档(high/moderate/low)，每档目标 30 条 → 3×3×30 = 270 条总量

DIMENSIONS: dict[str, dict] = {
    # ── first_cry / onset ──
    "birth/first_cry_onset_high": {
        "stage": "Birth (Apgar-2 breathing)",
        "field": "first_cry_onset — 高唤醒婴儿第一声哭的启动时机",
        "tone": "紧迫、无停顿、立即爆发",
        "applies_when_note": "applies_when: {arousal: 'high'}",
        "examples_existing": [
            "The instant air hit the lungs —",
            "No pause, no hesitation —",
            "Before the cord was even cut —",
            "The moment the chest expanded —",
        ],
        "style_hint": "每条必须以破折号或类似标记结尾（作为下一段 quality 的引子）。",
        "length_range": "20-80 字符",
    },
    "birth/first_cry_onset_moderate": {
        "stage": "Birth (Apgar-1~2 breathing)",
        "field": "first_cry_onset — 中等唤醒婴儿第一声哭的启动时机",
        "tone": "短暂停顿、有酝酿、然后展开",
        "applies_when_note": "applies_when: {arousal: 'moderate'}",
        "examples_existing": [
            "A brief gasp, then —",
            "Two seconds of startled silence, then —",
            "Eyes squeezed shut, mouth opened, and —",
            "A shudder ran through the tiny body, then —",
            "Fists clenched, face reddening, and —",
        ],
        "style_hint": "每条必须以破折号/and/then 结尾。",
        "length_range": "25-100 字符",
    },
    "birth/first_cry_onset_low": {
        "stage": "Birth (Apgar-0~1 breathing)",
        "field": "first_cry_onset — 低唤醒婴儿第一声哭的启动时机",
        "tone": "缓慢、不确定、费力、延迟",
        "applies_when_note": "applies_when: {arousal: 'low'}",
        "examples_existing": [
            "Almost a full five seconds passed before —",
            "So quiet at first that the room held its breath, until —",
            "A long, trembling inhale, lips quivering, and finally —",
            "Barely a sound at first — just air moving, then slowly —",
        ],
        "style_hint": "每条必须以破折号/until/finally/slowly 结尾。可以使用 {seconds} 占位符表示延迟秒数（4-10 秒）。",
        "length_range": "30-130 字符",
        "allow_vars": {
            "seconds": {"type": "int_range", "min": 4, "max": 10},
        },
    },
    # ── first_cry / quality ──
    "birth/first_cry_quality_high": {
        "stage": "Birth",
        "field": "first_cry_quality — 高唤醒哭声的听觉质感（F0 高、强度大）",
        "tone": "尖锐、撕裂、愤怒、持续",
        "applies_when_note": "applies_when: {arousal: 'high'}",
        "examples_existing": [
            "a piercing, full-throated wail split the room",
            "a scream erupted, raw and furious, shaking with force",
            "a cry like a siren — sharp, relentless, demanding",
            "an explosive howl tore through the silence",
        ],
        "style_hint": "描述声音质感，不加句号（后面会接 body 段）。",
        "length_range": "30-100 字符",
    },
    "birth/first_cry_quality_moderate": {
        "stage": "Birth",
        "field": "first_cry_quality — 中等唤醒哭声（节奏稳定）",
        "tone": "稳步建立、有节奏、清晰",
        "applies_when_note": "applies_when: {arousal: 'moderate'}",
        "examples_existing": [
            "a steady cry rose, finding its rhythm breath by breath",
            "a clear, insistent cry filled the space",
            "a strong cry built itself up, each wave louder than the last",
            "a determined cry emerged, rhythmic and purposeful",
        ],
        "style_hint": "描述声音质感，不加句号。",
        "length_range": "30-120 字符",
    },
    "birth/first_cry_quality_low": {
        "stage": "Birth",
        "field": "first_cry_quality — 低唤醒哭声（F0 低、强度小）",
        "tone": "细弱、颤抖、断续、像疑问",
        "applies_when_note": "applies_when: {arousal: 'low'}",
        "examples_existing": [
            "a thin, reedy sound escaped — more whimper than cry",
            "a soft mewling began, fragile but persistent",
            "a trembling note drifted out, barely audible at first",
            "a whisper of a cry, like a question asked to no one",
        ],
        "style_hint": "描述声音质感，不加句号。",
        "length_range": "30-120 字符",
    },
    # ── first_cry / body ──
    "birth/first_cry_body_high": {
        "stage": "Birth",
        "field": "first_cry_body — 高唤醒伴随的身体反应",
        "tone": "剧烈运动、绷紧、脸红",
        "applies_when_note": "applies_when: {arousal: 'high'}",
        "examples_existing": [
            "Limbs flailing, back arching, every muscle engaged in protest.",
            "Fists pounding air, legs kicking, face contorted in outrage.",
            "Whole body trembling with the effort, skin flushing crimson.",
            "Chest heaving in rapid bursts, fingers splayed wide.",
        ],
        "style_hint": "完整句，以句号结尾。",
        "length_range": "40-130 字符",
    },
    "birth/first_cry_body_moderate": {
        "stage": "Birth",
        "field": "first_cry_body — 中等唤醒身体反应",
        "tone": "四肢逐渐伸展、适应重力",
        "applies_when_note": "applies_when: {arousal: 'moderate'}",
        "examples_existing": [
            "Legs drawn up, arms half-extended, settling into the new world.",
            "Fingers curling and uncurling, body slowly adjusting to gravity.",
            "Face scrunched but relaxing between cries, chest rising steadily.",
            "Body curled inward, seeking the shape it knew, then slowly uncurling.",
        ],
        "style_hint": "完整句，以句号结尾。",
        "length_range": "40-140 字符",
    },
    "birth/first_cry_body_low": {
        "stage": "Birth",
        "field": "first_cry_body — 低唤醒身体反应",
        "tone": "静止、无力、微弱",
        "applies_when_note": "applies_when: {arousal: 'low'}",
        "examples_existing": [
            "Barely moving — still folded, still quiet, breathing shallow but steady.",
            "Eyes half-open, body limp and warm, only the faintest chest rise visible.",
            "Motionless except for the tiniest lip tremble and a slow blink.",
            "So still that only the pulse at the fontanelle proved anything at all.",
        ],
        "style_hint": "完整句，以句号结尾。",
        "length_range": "40-140 字符",
    },
    # ── immediate_state / eyes (按 arousal 分档) ──
    "birth/immediate_eyes_high": {
        "stage": "Birth (immediate post-delivery, 0-60s)",
        "field": "immediate_eyes — 高唤醒新生儿的眼部状态（睁眼/警觉/扫视）",
        "tone": "警觉、睁大、对光/运动反应强",
        "applies_when_note": "applies_when: {arousal: 'high'}",
        "examples_existing": ["eyes wide, dark and unfocused", "blinking rapidly, overwhelmed"],
        "style_hint": "短语，不加句号。不要以主语开头（后续会作为状态串的片段拼接）。",
        "length_range": "15-60 字符",
    },
    "birth/immediate_eyes_moderate": {
        "stage": "Birth (immediate post-delivery)",
        "field": "immediate_eyes — 中等唤醒新生儿的眼部状态",
        "tone": "半睁、缓慢适应、偶尔聚焦",
        "applies_when_note": "applies_when: {arousal: 'moderate'}",
        "examples_existing": [
            "eyes squinting against the light",
            "eyes open but glazed, seeing almost nothing yet",
        ],
        "style_hint": "短语，不加句号。",
        "length_range": "15-70 字符",
    },
    "birth/immediate_eyes_low": {
        "stage": "Birth (immediate post-delivery)",
        "field": "immediate_eyes — 低唤醒新生儿的眼部状态（闭眼/无反应）",
        "tone": "闭合、无反应、缓慢",
        "applies_when_note": "applies_when: {arousal: 'low'}",
        "examples_existing": [
            "eyes sealed shut",
            "one eye cracked open, the other shut",
        ],
        "style_hint": "短语，不加句号。",
        "length_range": "15-70 字符",
    },
    # ── immediate_state / posture (按 arousal 分档) ──
    "birth/immediate_posture_high": {
        "stage": "Birth (immediate post-delivery)",
        "field": "immediate_posture — 高唤醒新生儿的姿势（主动伸展/挣扎）",
        "tone": "活跃、伸展、对抗重力",
        "applies_when_note": "applies_when: {arousal: 'high'}",
        "examples_existing": [
            "splayed briefly open, then curling back inward",
            "arms reaching outward, legs tucked",
        ],
        "style_hint": "短语，不加句号。描述身体姿态（限描述 limbs / torso / head 位置）。",
        "length_range": "20-80 字符",
    },
    "birth/immediate_posture_moderate": {
        "stage": "Birth (immediate post-delivery)",
        "field": "immediate_posture — 中等唤醒新生儿的姿势（部分屈曲/偶尔调整）",
        "tone": "半屈曲、温和、自然调整",
        "applies_when_note": "applies_when: {arousal: 'moderate'}",
        "examples_existing": [
            "legs drawn up, arms across chest",
            "one fist pressed against the cheek",
            "chin tucked, shoulders hunched",
            "head turned to one side, body curved",
        ],
        "style_hint": "短语，不加句号。",
        "length_range": "20-90 字符",
    },
    "birth/immediate_posture_low": {
        "stage": "Birth (immediate post-delivery)",
        "field": "immediate_posture — 低唤醒新生儿的姿势（蜷缩/无力/松弛）",
        "tone": "蜷曲、无力、极少动作",
        "applies_when_note": "applies_when: {arousal: 'low'}",
        "examples_existing": [
            "limbs tightly flexed in fetal curl",
            "body limp and heavy with exhaustion",
        ],
        "style_hint": "短语，不加句号。",
        "length_range": "20-90 字符",
    },
    # ── immediate_state / tone (肌张力, 按 arousal 分档) ──
    "birth/immediate_tone_high": {
        "stage": "Birth (immediate post-delivery, Apgar muscle tone scoring)",
        "field": "immediate_tone — 高唤醒新生儿的肌张力（Apgar 2 分：vigorous）",
        "tone": "强、活跃、抗伸展",
        "applies_when_note": "applies_when: {arousal: 'high'}",
        "examples_existing": [
            "muscle tone strong — resists extension",
            "vigorous tone, active movement",
            "hypertonic — limbs stiff and resistant",
        ],
        "style_hint": "短语或半句，描述肌张力。不加句号。术语参考 Apgar。",
        "length_range": "20-80 字符",
    },
    "birth/immediate_tone_moderate": {
        "stage": "Birth (immediate post-delivery, Apgar muscle tone 1 point)",
        "field": "immediate_tone — 中等唤醒新生儿的肌张力（Apgar 1 分：some flexion）",
        "tone": "中等、对刺激有反应、部分屈曲",
        "applies_when_note": "applies_when: {arousal: 'moderate'}",
        "examples_existing": [
            "tone moderate, moves when stimulated",
            "relaxed, pliable, unhurried",
        ],
        "style_hint": "短语，不加句号。",
        "length_range": "20-90 字符",
    },
    "birth/immediate_tone_low": {
        "stage": "Birth (immediate post-delivery, Apgar muscle tone 0 point: limp/floppy)",
        "field": "immediate_tone — 低唤醒新生儿的肌张力（Apgar 0 分：flaccid）",
        "tone": "松弛、无力、逐渐恢复",
        "applies_when_note": "applies_when: {arousal: 'low'}",
        "examples_existing": ["slightly floppy, tone building gradually"],
        "style_hint": "短语，不加句号。",
        "length_range": "20-90 字符",
    },
    # ════════════════════════════════════════════════
    # late_organogenesis (Stage 2B) — 4 output fields
    # ════════════════════════════════════════════════
    # organ_maturation / 3 档 budget 档位
    "late_org/organ_maturation_strong": {
        "stage": "Late Organogenesis (week 8-10)",
        "field": "organ_maturation — budget 充足下器官成熟描述",
        "tone": "清晰、按部就班、各系统同步成熟",
        "applies_when_note": "applies_when: {budget_tier: 'strong'}",
        "examples_existing": [],
        "style_hint": "1-2 句。提及具体器官系统（cardiac / renal / hepatic / GI）与成熟特征。",
        "length_range": "60-200 字符",
    },
    "late_org/organ_maturation_moderate": {
        "stage": "Late Organogenesis",
        "field": "organ_maturation — 中等 budget 下的成熟（有些系统领先有些稍落后）",
        "tone": "不均衡但整体功能正常",
        "applies_when_note": "applies_when: {budget_tier: 'moderate'}",
        "examples_existing": [],
        "style_hint": "1-2 句。描述成熟不均衡。",
        "length_range": "60-200 字符",
    },
    "late_org/organ_maturation_weak": {
        "stage": "Late Organogenesis",
        "field": "organ_maturation — 低 budget 下成熟受限",
        "tone": "发育滞后、系统薄弱、特定器官留下缺陷",
        "applies_when_note": "applies_when: {budget_tier: 'weak'}",
        "examples_existing": [],
        "style_hint": "1-2 句。描述滞后、薄弱的器官系统。",
        "length_range": "60-200 字符",
    },
    # primary_sense / 5 感 × 3 档
    **{
        f"late_org/primary_sense_{sense}_{tier}": {
            "stage": "Late Organogenesis",
            "field": f"primary_sense — {sense} 通道为主导 ({tier} 强度)",
            "tone": {"strong": "主导感官极度锐利", "moderate": "主导感官清晰可辨",
                     "mild": "主导感官仅略占优"}[tier],
            "applies_when_note": f"applies_when: {{sense: '{sense}', strength: '{tier}'}}",
            "examples_existing": [],
            "style_hint": f"MUST contain the word '{sense}'. 1 句。描述该感官如何特化、相关神经环路如何密集。",
            "length_range": "50-180 字符",
        }
        for sense in ("visual", "auditory", "tactile", "olfactory", "proprioceptive")
        for tier in ("strong", "moderate", "mild")
    },
    # weak_sense / 5 感 × 3 severity
    **{
        f"late_org/weak_sense_{sense}_{sev}": {
            "stage": "Late Organogenesis",
            "field": f"weak_sense — {sense} 通道欠发达 ({sev} severity)",
            "tone": {"severe": "严重缺损", "moderate": "明显落后",
                     "mild": "轻微不足"}[sev],
            "applies_when_note": f"applies_when: {{sense: '{sense}', severity: '{sev}'}}",
            "examples_existing": [],
            "style_hint": f"MUST contain the word '{sense}'. 1 句。描述该感官如何欠缺或功能受限。",
            "length_range": "50-180 字符",
        }
        for sense in ("visual", "auditory", "tactile", "olfactory", "proprioceptive")
        for sev in ("severe", "moderate", "mild")
    },
    # perception_style / 5 感主导时的整体感知风格
    **{
        f"late_org/perception_style_{sense}": {
            "stage": "Late Organogenesis",
            "field": f"perception_style — {sense} 主导下的整体感知风格",
            "tone": "以该感官为锚定的世界感知方式",
            "applies_when_note": f"applies_when: {{primary_sense: '{sense}'}}",
            "examples_existing": [],
            "style_hint": "1 句。描述这个体将如何感知世界（以主导感官为锚）。",
            "length_range": "60-180 字符",
        }
        for sense in ("visual", "auditory", "tactile", "olfactory", "proprioceptive")
    },
    # ════════════════════════════════════════════════
    # late_neural (Stage 3B) — 4 output fields
    # ════════════════════════════════════════════════
    # arousal_baseline / 3 档
    "late_neu/arousal_baseline_high": {
        "stage": "Late Neural Development",
        "field": "arousal_baseline — 高唤醒基线（兴奋/抑制回路偏兴奋）",
        "tone": "反应剧烈、阈值低、容易觉醒",
        "applies_when_note": "applies_when: {arousal: 'high'}",
        "examples_existing": [],
        "style_hint": "MUST contain the word 'high'. 1-2 句。提及兴奋/抑制平衡、皮质醇影响等。",
        "length_range": "60-200 字符",
    },
    "late_neu/arousal_baseline_moderate": {
        "stage": "Late Neural Development",
        "field": "arousal_baseline — 中等唤醒基线",
        "tone": "平衡、稳定",
        "applies_when_note": "applies_when: {arousal: 'moderate'}",
        "examples_existing": [],
        "style_hint": "MUST contain the word 'moderate'. 1-2 句。",
        "length_range": "60-200 字符",
    },
    "late_neu/arousal_baseline_low": {
        "stage": "Late Neural Development",
        "field": "arousal_baseline — 低唤醒基线（抑制回路占优）",
        "tone": "沉静、反应慢、阈值高",
        "applies_when_note": "applies_when: {arousal: 'low'}",
        "examples_existing": [],
        "style_hint": "MUST contain the word 'low'. 1-2 句。",
        "length_range": "60-200 字符",
    },
    # myelination_priority / 5 感主导通路 × 3 速率
    **{
        f"late_neu/myelination_{sense}_{rate}": {
            "stage": "Late Neural Development",
            "field": f"myelination_priority — {sense} 通路髓鞘化 ({rate})",
            "tone": {"early": "领先开始包覆", "normal": "按标准时间表",
                     "delayed": "明显滞后"}[rate],
            "applies_when_note": f"applies_when: {{pathway: '{sense}', rate: '{rate}'}}",
            "examples_existing": [],
            "style_hint": f"MUST contain the word '{sense}'. 1 句。描述哪条神经通路优先髓鞘化。",
            "length_range": "60-180 字符",
        }
        for sense in ("visual", "auditory", "tactile", "motor", "somatosensory")
        for rate in ("early", "normal", "delayed")
    },
    # instinct_loops 原子片段库 / 5 感 × 3 强度；运行时采样 2-3 条组成数组
    **{
        f"late_neu/instinct_loop_{sense}_{tier}": {
            "stage": "Late Neural Development",
            "field": f"instinct_loop — {sense} 主导下的 {tier} 强度本能回路（刺激→反应对）",
            "tone": {"strong": "反应迅猛、整合多系统",
                     "moderate": "稳定、局部化",
                     "weak": "反应迟缓或不完整"}[tier],
            "applies_when_note": f"applies_when: {{sense: '{sense}', tier: '{tier}'}}",
            "examples_existing": [
                "Sudden loud sound → startle, brief limb extension, then cry",
                "Soft skin contact → orienting head turn, lip puckering",
            ],
            "style_hint": ("ONE complete stimulus→response loop per template. "
                           "Format: 'Stimulus → response1, response2'. "
                           "Use explicit arrow '→' between stim and response."),
            "length_range": "40-130 字符",
        }
        for sense in ("visual", "auditory", "tactile", "olfactory", "proprioceptive")
        for tier in ("strong", "moderate", "weak")
    },
    # neural_anomalies
    "late_neu/neural_anomalies_clean": {
        "stage": "Late Neural Development",
        "field": "neural_anomalies — 无显著异常",
        "tone": "无异常发现、或仅中性描述",
        "applies_when_note": "applies_when: {has_anomaly: false}",
        "examples_existing": ["No notable deviations from expected patterns.",
                              "Neural integration proceeding without detectable anomaly."],
        "style_hint": "1 短句。可以写 'none detected' 或简短中性句。",
        "length_range": "20-120 字符",
    },
    "late_neu/neural_anomalies_present": {
        "stage": "Late Neural Development",
        "field": "neural_anomalies — 检测到异常（缺陷影响神经通路）",
        "tone": "明确异常、定位清晰",
        "applies_when_note": "applies_when: {has_anomaly: true}",
        "examples_existing": [],
        "style_hint": "1-2 句。描述具体异常（delayed myelination / cortical thinning / subtle asymmetry 等）。",
        "length_range": "50-180 字符",
    },
    # ════════════════════════════════════════════════
    # tendencies (Birth field) — 新生儿性格倾向 trait 库
    # 运行时：从 arousal 池采 2 条 + 从 dominant sense 池采 2-3 条 = 4-5 条独特 trait
    # ════════════════════════════════════════════════
    **{
        f"trait/arousal_{arousal}": {
            "stage": "Birth (innate personality tendencies)",
            "field": f"tendencies — 新生儿的 {arousal} 唤醒性格词",
            "tone": {"high": "敏锐、反应快、易激动",
                     "moderate": "平衡、稳定、适应性强",
                     "low": "沉静、内敛、慢热"}[arousal],
            "applies_when_note": f"applies_when: {{arousal: '{arousal}'}}",
            "examples_existing": ["alert", "curious", "quick to startle", "intense",
                                  "placid", "observant", "slow to warm", "deliberate"],
            "style_hint": ("Short phrase, 1-4 words each. Personality-descriptor style "
                           "(e.g., 'quick to startle', 'deeply observant'). "
                           "No sentences, no punctuation, no article 'a/the'."),
            "length_range": "5-40 字符",
        }
        for arousal in ("high", "moderate", "low")
    },
    **{
        f"trait/sense_{sense}": {
            "stage": "Birth (innate tendencies — sense-specific)",
            "field": f"tendencies — 以 {sense} 为主导感官的倾向词",
            "tone": f"突出 {sense} 感官相关的行为倾向",
            "applies_when_note": f"applies_when: {{dominant_sense: '{sense}'}}",
            "examples_existing": {
                "visual": ["keen-eyed", "visually attentive", "drawn to faces", "pattern-sensitive"],
                "auditory": ["sound-tracking", "rhythm-sensitive", "quick to orient to voice"],
                "tactile": ["touch-seeking", "calmed by contact", "texture-aware"],
                "olfactory": ["scent-tracking", "odor-responsive"],
                "proprioceptive": ["body-aware", "movement-oriented", "gravity-sensitive"],
            }[sense],
            "style_hint": ("Short phrase, 1-4 words each. Must relate to the "
                           f"{sense} modality. No sentences, no punctuation, no article."),
            "length_range": "5-40 字符",
        }
        for sense in ("visual", "auditory", "tactile", "olfactory", "proprioceptive")
    },
    # ════════════════════════════════════════════════
    # maternal_response — 母体反馈 4 字段 × 3 档
    # ════════════════════════════════════════════════
    **{
        f"maternal/hormonal_shift_stress_{tier}": {
            "stage": "Maternal response to stage transition",
            "field": f"hormonal_shift — 母体在 stress={tier} 下的激素反应",
            "tone": {"high": "皮质醇升高、黄体酮波动、hCG 应激",
                     "moderate": "轻微波动、整体稳定",
                     "low": "稳态、各通路协调"}[tier],
            "applies_when_note": f"applies_when: {{stress_tier: '{tier}'}}",
            "examples_existing": [],
            "style_hint": ("1 short clause. Mention specific hormone(s): cortisol / "
                           "progesterone / hCG / thyroid / estriol. No leading subject needed."),
            "length_range": "30-120 字符",
        }
        for tier in ("high", "moderate", "low")
    },
    **{
        f"maternal/physical_adaptation_stress_{tier}": {
            "stage": "Maternal response",
            "field": f"physical_adaptation — 母体在 stress={tier} 下的身体适应",
            "tone": {"high": "子宫收缩、血流受限、张力增高",
                     "moderate": "局部张力、整体正常",
                     "low": "血流畅通、子宫松弛、灌注良好"}[tier],
            "applies_when_note": f"applies_when: {{stress_tier: '{tier}'}}",
            "examples_existing": [],
            "style_hint": "1 short clause. Mention uterine / vascular / cardiopulmonary state. No emoji.",
            "length_range": "30-120 字符",
        }
        for tier in ("high", "moderate", "low")
    },
    **{
        f"maternal/nutrient_redistribution_nutrition_{tier}": {
            "stage": "Maternal response",
            "field": f"nutrient_redistribution — nutrition={tier} 下的营养分配",
            "tone": {"good": "充分供给、均衡分配",
                     "moderate": "基本满足、有局部不足",
                     "poor": "受限、胎盘优先保留关键营养"}[tier],
            "applies_when_note": f"applies_when: {{nutrition_tier: '{tier}'}}",
            "examples_existing": [],
            "style_hint": ("1 short clause. Mention specific nutrients: folate / iron / iodine / DHA / "
                           "calcium / glucose / amino acids. No leading subject."),
            "length_range": "30-130 字符",
        }
        for tier in ("good", "moderate", "poor")
    },
    **{
        f"maternal/stress_response_stress_{tier}": {
            "stage": "Maternal response",
            "field": f"stress_response — stress={tier} 下的应激反应",
            "tone": {"high": "战斗-逃跑激活、胎儿暴露高",
                     "moderate": "管理中、有波动",
                     "low": "良好调节、胎儿免受影响"}[tier],
            "applies_when_note": f"applies_when: {{stress_tier: '{tier}'}}",
            "examples_existing": [],
            "style_hint": ("1 short clause. Describe autonomic / HPA axis state and fetal impact. "
                           "No leading subject."),
            "length_range": "30-130 字符",
        }
        for tier in ("high", "moderate", "low")
    },
    # ── immediate_state / color (按 vitality 分档，反映围产期 perfusion) ──
    "birth/immediate_color_strong": {
        "stage": "Birth (immediate post-delivery, Apgar color scoring)",
        "field": "immediate_color — 强活力新生儿的肤色（Apgar 2 分：完全红润）",
        "tone": "红润、血流灌注良好、快速完成转换",
        "applies_when_note": "applies_when: {vitality: 'strong'}",
        "examples_existing": [
            "pink spreading from the trunk outward",
            "ruddy and flushed, capillaries flooding",
            "deep pink, healthy perfusion from the start",
        ],
        "style_hint": "短语，不加句号。描述肤色 / perfusion / capillary refill。",
        "length_range": "20-90 字符",
    },
    "birth/immediate_color_moderate": {
        "stage": "Birth (immediate post-delivery, Apgar color 1 point: acrocyanosis)",
        "field": "immediate_color — 中等活力新生儿的肤色（Apgar 1 分：躯干红润四肢青紫）",
        "tone": "躯干红润但肢端发绀、逐渐改善",
        "applies_when_note": "applies_when: {vitality: 'moderate'}",
        "examples_existing": [
            "dusky at first, clearing with each breath",
            "blotchy red and white, circulation adjusting",
        ],
        "style_hint": "短语，不加句号。可以提 acrocyanosis / mottled / dusky 等术语。",
        "length_range": "20-100 字符",
    },
    "birth/immediate_color_weak": {
        "stage": "Birth (immediate post-delivery, Apgar color 0 point: pale/central cyanosis)",
        "field": "immediate_color — 弱活力新生儿的肤色（Apgar 0 分：全身苍白或中央发绀）",
        "tone": "苍白、发绀、灌注缓慢",
        "applies_when_note": "applies_when: {vitality: 'weak'}",
        "examples_existing": ["pale but warming quickly under the lamp"],
        "style_hint": "短语，不加句号。可以提 pallor / central cyanosis / poor perfusion。",
        "length_range": "20-100 字符",
    },
}


_META_PROMPT = """You are a neonatal clinical writing expert (Apgar scoring, newborn cry acoustics, Brazelton NBAS).

**CRITICAL: All generated `text` fields MUST be in ENGLISH ONLY. No Chinese characters, no other languages, no mixed-language output. English only. This is non-negotiable — any template containing non-English characters will be rejected.**

TASK: Generate {count} NEW narrative templates for the field below. Each template will be used by a digital-life simulation to render a unique baby.

Stage: {stage}
Field: {field}
Tone requirement: {tone}
Context tag: {applies_when_note}
Length: {length_range}
Style: {style_hint}

EXISTING TEMPLATES (you MUST differ in wording/rhythm/imagery from these — avoid repetition):
{existing}

REQUIREMENTS:
1. **English only** for the `text` field. No Chinese, no other languages.
2. Each template stands alone. No numbering, no bullets.
3. Medical/acoustic grounding — reflect realistic neonatal behavior. Do NOT invent non-existent reflexes or anatomy.
4. Variability — vary sentence structure, vocabulary, and rhythm across templates. NO two should feel alike.
5. Placeholders — you MAY use `{{placeholder_name}}` for numeric variability IF it adds naturalism (e.g., seconds of delay, dB of volume). Keep placeholders rare and justified.
6. Length constraint: stay within {length_range}.
7. No emojis, no hashtags, no meta-commentary.

OUTPUT FORMAT (MUST be valid JSON, a single array, nothing else):
[
  {{"text": "English text only", "vars": {{}}}},
  {{"text": "English text with {{seconds}} placeholder", "vars": {{"seconds": {{"type": "int_range", "min": 4, "max": 10}}}}}}
]

Return ONLY the JSON array, no code fences, no prose before or after. All `text` values MUST be English.
"""


def _load_existing(key: str) -> list[dict]:
    path = _TEMPLATE_DIR / f"{key}.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("templates", [])
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save(key: str, templates: list[dict], applies_when: dict | None = None) -> None:
    path = _TEMPLATE_DIR / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "key": key,
        "count": len(templates),
        "applies_when_default": applies_when or {},
        "templates": templates,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("落库 %s: %d 条", path, len(templates))


# ============================================================
# 质量闸门
# ============================================================

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_CHINESE_RE = re.compile(r"[一-鿿]")


def _validate_one(tpl: dict, length_range: str, allow_vars: dict | None) -> tuple[bool, str]:
    if not isinstance(tpl, dict):
        return False, "not a dict"
    text = tpl.get("text")
    if not isinstance(text, str) or not text.strip():
        return False, "empty text"

    # 纯英文校验：禁止中文字符混入（LLM 有时自作主张切换语种）
    if _CHINESE_RE.search(text):
        return False, "non-English characters present"

    # 长度校验
    try:
        lo, hi = [int(x) for x in length_range.split("-") if x.strip().isdigit() or x.strip().replace("-", "").isdigit()]
    except Exception:
        lo, hi = 20, 200
    text_stripped = text.strip()
    # 填充占位符粗略长度：按平均值估算
    if len(text_stripped) < lo * 0.5 or len(text_stripped) > hi * 1.5:
        return False, f"length {len(text_stripped)} out of [{lo*0.5:.0f}, {hi*1.5:.0f}]"

    # 占位符一致性
    placeholders = set(_PLACEHOLDER_RE.findall(text))
    declared = set((tpl.get("vars") or {}).keys())
    if placeholders != declared:
        return False, f"placeholders {placeholders} != declared vars {declared}"

    # 只允许约定的变量名（防止 LLM 自己发明）
    if allow_vars is not None and placeholders and not placeholders.issubset(set(allow_vars.keys())):
        return False, f"unknown placeholder(s): {placeholders - set(allow_vars.keys())}"

    return True, ""


def _dedupe_against_existing(
    candidates: list[dict], existing: list[dict], min_token_diff: int = 3
) -> list[dict]:
    existing_tokens = [set(t.get("text", "").lower().split()) for t in existing]
    out = []
    for c in candidates:
        tokens = set(c.get("text", "").lower().split())
        dup = False
        for et in existing_tokens:
            overlap = tokens & et
            # 字符重叠率 > 70% 视为太相似
            if tokens and len(overlap) / max(len(tokens), 1) > 0.7:
                dup = True
                break
        if not dup:
            out.append(c)
            existing_tokens.append(tokens)  # 自去重
    return out


# ============================================================
# 主流程
# ============================================================

def generate_for_dim(
    dim_key: str,
    count: int,
    model: str | None = None,
    provider: str = "deepseek",
) -> int:
    """为指定维度生成 count 条新模板，增量追加到 JSON。返回实际新增数。"""
    if dim_key not in DIMENSIONS:
        raise ValueError(f"Unknown dimension: {dim_key}")
    cfg = DIMENSIONS[dim_key]

    existing = _load_existing(dim_key)
    logger.info("%s 已有 %d 条，目标新增 %d 条", dim_key, len(existing), count)

    # applies_when 从 dim_key 反推（late_*/trait/maternal 用 DIMENSIONS 自带字段；birth 走老规则）
    applies_when = {}
    if (dim_key.startswith("late_org/") or dim_key.startswith("late_neu/")
            or dim_key.startswith("trait/") or dim_key.startswith("maternal/")):
        # late_* 的元信息从 applies_when_note 字段解析
        note = cfg.get("applies_when_note", "")
        import re as _re
        m = _re.search(r"\{([^}]+)\}", note)
        if m:
            for pair in m.group(1).split(","):
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if v in ("true", "false"):
                        applies_when[k] = v == "true"
                    else:
                        applies_when[k] = v
    elif "immediate_color" in dim_key:
        if dim_key.endswith("_strong"):
            applies_when = {"vitality": "strong"}
        elif dim_key.endswith("_moderate"):
            applies_when = {"vitality": "moderate"}
        elif dim_key.endswith("_weak"):
            applies_when = {"vitality": "weak"}
    elif dim_key.endswith("_high"):
        applies_when = {"arousal": "high"}
    elif dim_key.endswith("_moderate"):
        applies_when = {"arousal": "moderate"}
    elif dim_key.endswith("_low"):
        applies_when = {"arousal": "low"}

    existing_text = "\n".join(f'- "{t.get("text","")}"' for t in existing[:20]) or "(none yet)"

    prompt = _META_PROMPT.format(
        count=count,
        stage=cfg["stage"],
        field=cfg["field"],
        tone=cfg["tone"],
        applies_when_note=cfg["applies_when_note"],
        length_range=cfg["length_range"],
        style_hint=cfg["style_hint"],
        existing=existing_text,
    )

    client = create_client(provider)
    if model is None:
        model = get_model(provider)

    logger.info("调用 LLM (%s / %s)...", provider, model)
    raw = call_llm(prompt, client, model, provider)

    try:
        parsed = parse_json(raw)
    except Exception as e:
        logger.error("LLM 返回解析失败: %s\n原文前 500 字:\n%s", e, raw[:500])
        return 0

    if not isinstance(parsed, list):
        logger.error("LLM 返回非数组: %s", type(parsed))
        return 0

    # 为所有模板打上 applies_when
    for t in parsed:
        if isinstance(t, dict):
            t.setdefault("applies_when", dict(applies_when))

    # 逐条校验
    valid: list[dict] = []
    for t in parsed:
        ok, reason = _validate_one(t, cfg["length_range"], cfg.get("allow_vars"))
        if ok:
            valid.append(t)
        else:
            logger.warning("丢弃模板 [%s]: %s", reason, (t or {}).get("text", "")[:80])

    # 去重（与 existing + 自身）
    deduped = _dedupe_against_existing(valid, existing)

    logger.info("%s: LLM 返回 %d 条 → 校验通过 %d → 去重后 %d",
                dim_key, len(parsed), len(valid), len(deduped))

    if not deduped:
        return 0

    merged = existing + deduped
    _save(dim_key, merged, applies_when)
    return len(deduped)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--dim", default=None,
                        help="单维度 key（例 birth/first_cry_onset_high）")
    parser.add_argument("--prefix", default=None,
                        help="仅生成此前缀的维度（例 late_org/）")
    parser.add_argument("--skip-full", type=int, default=0,
                        help="若池已有 >= 此条数则跳过（默认 0=永远追加）")
    parser.add_argument("--count", type=int, default=30, help="每维度目标新增条数")
    parser.add_argument("--model", default=None)
    parser.add_argument("--provider", default="deepseek")
    args = parser.parse_args()

    if args.dim:
        n = generate_for_dim(args.dim, args.count, args.model, args.provider)
        print(f"\n✓ {args.dim}: +{n} 条")
        return

    # 全量或按 prefix 过滤
    targets = [d for d in DIMENSIONS if not args.prefix or d.startswith(args.prefix)]
    print(f"将生成 {len(targets)} 个维度" + (f"（prefix={args.prefix}）" if args.prefix else ""))

    total = 0
    for dim in targets:
        # 若已有 >= skip_full 条，跳过
        if args.skip_full > 0:
            existing = _load_existing(dim)
            if len(existing) >= args.skip_full:
                print(f"  ⊙ {dim}: 已有 {len(existing)} 条 ≥ {args.skip_full}，跳过")
                continue
        try:
            n = generate_for_dim(dim, args.count, args.model, args.provider)
            total += n
            print(f"  ✓ {dim}: +{n}")
        except Exception as e:
            print(f"  ✗ {dim}: {e}", file=sys.stderr)
    print(f"\n合计新增 {total} 条模板")


if __name__ == "__main__":
    main()
