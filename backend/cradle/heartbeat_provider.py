"""
摇篮心跳适配器 -- 为 heartbeat 引擎提供摇篮阶段的上下文。

[INPUT]: 依赖 heartbeat.py, cradle/state.py, cradle/phases.py
[OUTPUT]: CradleMonologueProvider, CRADLE_BEHAVIORS, shift_attachment_toward_avoidant()
[POS]: cradle/ 的心跳适配层，被 api/cradle.py 和 nanny.py 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import time

from heartbeat import BehaviorSpace
from .state import BabyState, StressState


# ── 行为空间数据（Phase 1-12 in spec -> index 0-11 in code）────


CRADLE_BEHAVIORS: dict[int, BehaviorSpace] = {
    # Phase 1: Neonatal (0-1 month)
    0: BehaviorSpace(
        verbal=[
            "reflexive_cry", "hunger_cry", "pain_cry",
            "discomfort_whimper", "startle_cry", "contentment_sigh",
            "feeding_sounds", "breathing_vocalization",
            "sleep_whimper", "fuss_before_cry",
        ],
        physical=[
            "rooting_reflex", "sucking_reflex", "grasp_reflex",
            "moro_reflex", "head_turn_to_voice", "eye_tracking_face",
            "body_curl_toward_warmth", "limb_stretch",
            "hand_to_mouth", "skin_to_skin_nuzzle",
            "tonic_neck_reflex", "stepping_reflex",
        ],
        avoidance=[
            "gaze_aversion", "body_stiffen", "turn_head_away",
            "arching_back", "hand_splaying", "hiccup_from_stress",
            "yawn_shutdown", "sneeze_response",
            "sleep_as_escape", "feeding_refusal",
        ],
    ),
    # Phase 2: Sensory Awakening (1-3 months)
    1: BehaviorSpace(
        verbal=[
            "social_smile_coo", "vowel_cooing", "responsive_vocalization",
            "pleasure_squeal", "differentiated_cry", "gurgling",
            "laugh_attempt", "rhythm_vocalization",
            "protest_cry", "attention_fuss",
            "imitation_mouth", "sigh_of_relief",
        ],
        physical=[
            "social_smile", "reach_toward_face", "eye_contact_hold",
            "head_lift_prone", "hand_discovery", "batting_at_objects",
            "kick_in_excitement", "mouth_exploration",
            "turn_toward_sound", "body_wiggle_joy",
            "finger_play", "visual_tracking_arc",
        ],
        avoidance=[
            "cry_escalation", "face_turn_fatigue", "fist_clench_stress",
            "eye_squint_shut", "body_tension", "push_away_bottle",
            "whine_when_alone", "spit_up_overfeed",
            "resist_position_change", "avoid_unfamiliar_smell",
        ],
    ),
    # Phase 3: Body Exploration (3-6 months)
    2: BehaviorSpace(
        verbal=[
            "babbling_consonant", "blow_raspberry", "shriek_delight",
            "growl_play", "sing_along_attempt", "call_for_attention",
            "protest_vocalization", "laugh_out_loud",
            "name_response_sound", "vocal_experimentation",
            "dialogue_turn_taking", "squeal_anticipation",
        ],
        physical=[
            "roll_over", "reach_and_grasp", "transfer_objects",
            "foot_discovery", "sit_with_support", "bounce_on_lap",
            "bang_objects", "pull_hair_face",
            "tummy_time_push", "mouth_everything",
            "reach_for_person", "pat_mirror_image",
        ],
        avoidance=[
            "stranger_wariness", "cling_to_caregiver", "reject_new_food",
            "whimper_when_left", "push_away_disliked", "bury_face",
            "refuse_stranger_hold", "cry_at_loud_noise",
            "turn_from_camera", "stiffen_in_highchair",
        ],
    ),
    # Phase 4: Object Permanence (6-9 months)
    3: BehaviorSpace(
        verbal=[
            "canonical_babble", "shout_for_attention", "whisper_discovery",
            "protest_no", "imitate_sounds", "excited_panting",
            "bye_bye_sound", "demand_vocalization",
            "comfort_self_hum", "question_intonation",
            "name_recognition_response", "sing_song_babble",
        ],
        physical=[
            "peek_a_boo_initiate", "crawl_toward", "pull_to_stand",
            "clap_hands", "wave_bye", "point_at_object",
            "drop_and_watch", "bang_two_objects",
            "open_close_hand", "search_hidden_object",
            "cruise_furniture", "give_and_take",
            "imitate_gesture", "separation_crawl_follow",
        ],
        avoidance=[
            "stranger_anxiety_peak", "separation_cry",
            "hide_behind_caregiver", "refuse_to_be_put_down",
            "reject_food_spit", "protest_diaper_change",
            "avoid_eye_contact_stranger", "body_arch_resist",
            "crawl_away_from", "whine_at_boundary",
            "nighttime_separation_cry", "cling_in_new_place",
        ],
    ),
    # Phase 5: Motor Explosion (9-12 months)
    4: BehaviorSpace(
        verbal=[
            "first_word_attempt", "mama_dada_directed", "jargon_babble",
            "no_head_shake", "point_and_vocalize", "animal_sound_imitate",
            "whine_request", "exclamation_surprise",
            "giggle_chain", "protest_scream",
            "song_fragment", "call_name",
        ],
        physical=[
            "walk_first_steps", "climb_stairs", "open_cabinet",
            "stack_blocks", "feed_self_finger", "turn_pages",
            "push_pull_toy", "throw_ball",
            "dance_to_music", "hug_stuffed_animal",
            "bring_object_to_show", "imitate_housework",
            "put_objects_in_container", "hand_object_to_adult",
        ],
        avoidance=[
            "toddle_away_fast", "hide_face_in_hands", "shake_head_no",
            "push_plate_away", "go_limp_resist", "tantrum_floor",
            "close_eyes_pretend_sleep", "crawl_under_furniture",
            "refuse_hand_hold", "squirm_to_escape",
            "avoid_bath", "reject_medicine",
        ],
    ),
    # Phase 6: First Words (12-18 months)
    5: BehaviorSpace(
        verbal=[
            "vocabulary_10_50", "one_word_sentence", "name_objects",
            "say_no", "say_mine", "request_word",
            "greeting_words", "echo_last_word",
            "emotional_word", "name_family",
            "label_body_part", "exclaim_wow",
            "demand_more", "protest_verbal",
        ],
        physical=[
            "walk_confidently", "run_attempt", "scribble",
            "spoon_self_feed", "carry_large_object", "kick_ball",
            "climb_on_furniture", "open_door",
            "take_off_shoes", "help_dress",
            "hug_parent", "kiss_give",
            "share_food", "bring_book_for_reading",
        ],
        avoidance=[
            "run_away_when_called", "hide_behind_object",
            "say_no_repeatedly", "throw_food",
            "scream_refuse", "hit_when_frustrated",
            "bite_when_angry", "turn_back_to_speaker",
            "limp_body_protest", "cover_ears",
            "close_door_on_person", "pretend_not_hear",
        ],
    ),
    # Phase 7: Language Explosion (18-24 months)
    6: BehaviorSpace(
        verbal=[
            "two_word_combo", "vocabulary_200_plus", "question_what",
            "possessive_mine", "narrate_action", "sing_simple_song",
            "name_emotions", "tell_on_others",
            "command_others", "repeat_phrases",
            "imaginary_phone_talk", "say_sorry",
            "count_attempt", "color_name_attempt",
        ],
        physical=[
            "run_freely", "jump_two_feet", "balance_beam_walk",
            "stack_6_blocks", "turn_doorknob", "pour_water",
            "undress_self", "wash_hands",
            "pretend_play", "push_peer_away",
            "comfort_crying_peer", "drag_parent_to_show",
            "stomp_feet_anger", "throw_in_tantrum",
        ],
        avoidance=[
            "refuse_share_toy", "hide_forbidden_object",
            "run_from_diaper", "ignore_instruction",
            "go_stiff_resist", "scream_tantrum",
            "hit_self_frustration", "refuse_eye_contact",
            "hide_in_closet", "say_go_away",
            "push_hand_away", "pretend_busy",
        ],
    ),
    # Phase 8: Why Stage (2-3 years)
    7: BehaviorSpace(
        verbal=[
            "why_loop", "three_word_sentence", "tell_story_fragment",
            "negotiate_verbally", "lie_first_attempt", "tattle",
            "express_preference", "make_up_words",
            "correct_others", "announce_intention",
            "describe_feelings", "use_please",
            "threat_verbal", "private_speech",
        ],
        physical=[
            "pedal_tricycle", "use_scissors", "draw_circle",
            "build_tower", "dress_self_attempt", "pour_own_drink",
            "toilet_announce", "hold_crayon_properly",
            "parallel_play", "chase_game",
            "help_with_chores", "organize_toys",
            "dance_specific_moves", "cover_parent_with_blanket",
        ],
        avoidance=[
            "full_blown_tantrum", "refuse_routine", "blame_others",
            "hide_evidence", "selective_hearing", "negotiate_to_delay",
            "dawdle", "demand_different_parent",
            "refuse_new_situation", "clingy_regression",
            "say_i_dont_know", "silent_treatment_toddler",
        ],
    ),
    # Phase 9: Social Sprouting (3-4 years)
    8: BehaviorSpace(
        verbal=[
            "initiate_conversation", "invite_to_play", "role_assign",
            "joke_attempt", "secret_whisper", "apologize_genuine",
            "express_empathy", "boast",
            "complain_about_fairness", "ask_permission",
            "report_feelings", "argue_back",
            "make_promise", "use_magic_words",
        ],
        physical=[
            "cooperative_play", "take_turns", "dramatic_play",
            "draw_person", "catch_ball", "hop_on_one_foot",
            "button_unbutton", "set_table",
            "water_plants", "feed_pet",
            "hold_hands_with_friend", "gift_giving",
            "pat_crying_friend", "show_and_tell",
        ],
        avoidance=[
            "exclude_from_play", "silent_protest", "pretend_sick",
            "make_excuse", "blame_imaginary_friend",
            "refuse_unfamiliar_food", "cling_at_school_gate",
            "avoid_bully", "change_subject",
            "withdraw_after_scolding", "demand_routine",
            "bathroom_escape",
        ],
    ),
    # Phase 10: Rule Understanding (4-5 years)
    9: BehaviorSpace(
        verbal=[
            "explain_rules", "negotiate_complex", "tell_elaborate_story",
            "ask_deep_questions", "white_lie", "defend_friend",
            "express_gratitude", "compare_self_to_others",
            "describe_dream", "plan_verbally",
            "persuade", "comfort_with_words",
            "report_wrongdoing", "self_correct_speech",
        ],
        physical=[
            "write_name", "tie_shoes_attempt", "ride_bike_training",
            "build_complex_structure", "clean_up_after_self", "pour_cereal",
            "brush_teeth_self", "make_bed_attempt",
            "freeze_dance", "line_up",
            "raise_hand", "help_younger_child",
            "share_snack", "group_game_follow",
        ],
        avoidance=[
            "tattle_strategically", "lie_to_avoid_trouble",
            "deny_wrongdoing", "slow_compliance",
            "conditional_obey", "compare_unfairly",
            "withdraw_from_competition", "pretend_not_understand",
            "ally_seek", "cry_manipulative",
            "refuse_apology", "silent_sulk",
        ],
    ),
    # Phase 11: Abstract Sprouting (5-6 years)
    10: BehaviorSpace(
        verbal=[
            "hypothetical_thinking", "moral_judgment", "future_planning",
            "explain_cause_effect", "sarcasm_early", "private_joke",
            "gossip_early", "express_worry",
            "debate_opinion", "compliment_genuine",
            "express_love_verbal", "ask_about_death",
            "distinguish_fact_fiction", "use_humor_intentional",
        ],
        physical=[
            "write_letters_numbers", "draw_detailed_picture", "skip",
            "swim_attempt", "ride_bike_no_training", "cook_simple",
            "care_for_plant", "organize_collection",
            "theatrical_performance", "write_letter_to_someone",
            "decorate_room", "board_game_play",
        ],
        avoidance=[
            "compare_and_complain", "perfectionism_avoidance",
            "school_anxiety_excuse", "friendship_withdrawal",
            "overhear_and_worry", "nightmare_avoidance",
            "avoid_failure_task", "deny_feelings",
            "blame_teacher", "hide_test_result",
            "emotional_shutdown", "peer_pressure_conform",
        ],
    ),
    # Phase 12: Independence (6-7 years)
    11: BehaviorSpace(
        verbal=[
            "read_aloud", "tell_complex_story", "argue_logically",
            "express_preference_reasoned", "use_big_words", "keep_secret",
            "report_school_day", "phone_answer",
            "joke_punchline", "explain_to_younger",
            "disagree_politely", "plan_with_friend",
            "express_disappointment", "ask_for_help_specific",
        ],
        physical=[
            "walk_to_school_alone", "make_breakfast_simple",
            "bathe_independently", "homework_independently",
            "clean_room", "ride_bike_neighborhood",
            "sports_team_play", "use_scissors_precisely",
            "write_journal", "pack_school_bag",
            "make_friend_independently", "choose_own_clothes",
        ],
        avoidance=[
            "door_slam", "bedroom_retreat", "homework_avoidance",
            "lie_elaborate", "friend_alliance", "unfair_protest",
            "parent_embarrassment_avoid", "rebel_small_rules",
            "screen_escape", "passive_resistance",
            "negotiate_endlessly", "emotional_outburst",
        ],
    ),
}


# ── 依恋偏移 ─────────────────────────────────────────────


_ATTACHMENT_SHIFT: dict[str, str] = {
    "forming": "avoidant",
    "secure": "anxious",
    "anxious": "avoidant",
    "avoidant": "avoidant",
}


def shift_attachment_toward_avoidant(state: BabyState) -> None:
    """连续忽略导致依恋风格向回避方向偏移。"""
    state.attachment_style = _ATTACHMENT_SHIFT.get(
        state.attachment_style, state.attachment_style,
    )


# ── CradleMonologueProvider ─────────────────────────────


class CradleMonologueProvider:
    """为 heartbeat 引擎提供摇篮阶段的完整上下文。"""

    def build_inner_monologue(self, state: BabyState) -> str:
        """构造婴儿内心独白，供 LLM 作为潜意识判断主动行为。"""
        now = time.time()
        ini = state.initiative
        sections: list[str] = []

        # 1. 生理信号 + 生理时钟
        stress = state.stress
        ns = state.nutrition_sleep
        phys = state.physical
        sim_t = state.sim_time

        # 计算距上次生理事件的模拟小时数
        hours_since_fed = sim_t - ns.last_fed_time if ns.last_fed_time > 0 else -1
        hours_since_diaper = sim_t - ns.last_diaper_time if ns.last_diaper_time > 0 else -1
        hours_since_sleep = sim_t - ns.last_sleep_time if ns.last_sleep_time > 0 else -1

        body_lines = [
            f"Stress level: {stress.stress_level:.2f}",
            f"Sleep quality: {ns.sleep_quality:.1f}, "
            f"night wakings: {ns.night_waking_frequency}",
            f"Feeding mode: {ns.feeding_mode}",
        ]
        # 生理时钟——让 LLM 推断具体需求
        if hours_since_fed >= 0:
            body_lines.append(f"Hours since last feeding: {hours_since_fed:.1f}")
            if hours_since_fed > 3:
                body_lines.append("  → LIKELY HUNGRY (>3h since last feed)")
        if hours_since_diaper >= 0:
            body_lines.append(f"Hours since last diaper change: {hours_since_diaper:.1f}")
            if hours_since_diaper > 2:
                body_lines.append("  → LIKELY NEEDS DIAPER CHANGE (>2h)")
        if hours_since_sleep >= 0:
            body_lines.append(f"Hours since last sleep: {hours_since_sleep:.1f}")
            if hours_since_sleep > 4:
                body_lines.append("  → LIKELY SLEEPY (>4h awake)")
        body_lines.append(f"Temperature comfort: {ns.comfort_temp}")
        if ns.comfort_temp != "comfortable":
            body_lines.append(f"  → UNCOMFORTABLE: {ns.comfort_temp}")
        if ns.sleep_regression_active:
            body_lines.append("Sleep regression is ACTIVE")
        if phys.teeth_count > 0:
            body_lines.append(f"Teething: {phys.teeth_count} teeth erupted")
            if phys.teeth_count <= 4:
                body_lines.append("  → Active teething phase — gums may be sore")
        if stress.regressed_capabilities:
            names = [r["capability"] for r in stress.regressed_capabilities]
            body_lines.append(f"Regressed capabilities: {', '.join(names)}")
        sections.append("## Body Signals & Physiological Clock\n" + "\n".join(body_lines))

        # 2. 最近经历：V2=on 走 recall（相关性 + forget_score），V2=off 保留旧最近 3 条行为
        try:
            from memory import is_v2_enabled, recall, build_memory_prompt_block
            if is_v2_enabled():
                _rc = recall(state, context="internal monologue",
                             current_tags=set(), token_budget=800)
                _block = build_memory_prompt_block(_rc, empty_fallback="")
                if _block:
                    sections.append("## Recent Experiences\n" + _block)
            elif state.memories:
                recent = state.memories[-3:]
                mem_lines = []
                for m in recent:
                    valence = m.emotional_valence
                    mem_lines.append(
                        f"- [{valence}] {m.event}: {m.reaction} "
                        f"(intensity {m.intensity:.1f})"
                    )
                sections.append("## Recent Experiences\n" + "\n".join(mem_lines))
        except Exception:
            # 记忆模块失败不能阻断心跳；退回旧行为
            if state.memories:
                recent = state.memories[-3:]
                mem_lines = []
                for m in recent:
                    valence = m.emotional_valence
                    mem_lines.append(
                        f"- [{valence}] {m.event}: {m.reaction} "
                        f"(intensity {m.intensity:.1f})"
                    )
                sections.append("## Recent Experiences\n" + "\n".join(mem_lines))

        # 3. 情绪状态 + 偏好 + 恐惧
        emo = state.emotional
        emo_lines = [
            f"Empathy: {emo.empathy_level}",
            f"Self-regulation: {emo.self_regulation_score:.2f}",
            f"Tantrum frequency: {emo.tantrum_frequency:.2f}",
            f"Play type: {emo.play_type}",
        ]
        if state.preferences:
            emo_lines.append(f"Preferences: {', '.join(state.preferences)}")
        if state.fears:
            emo_lines.append(f"Fears: {', '.join(state.fears)}")
        if state.comfort_sources:
            emo_lines.append(
                f"Comfort sources: {', '.join(state.comfort_sources)}"
            )
        sections.append("## Emotional State\n" + "\n".join(emo_lines))

        # 4. 互动时间
        mins_since_interact = (
            (now - ini.last_interact_ts) / 60.0
            if ini.last_interact_ts
            else -1
        )
        mins_since_initiative = (
            (now - ini.last_initiative_ts) / 60.0
            if ini.last_initiative_ts
            else -1
        )
        time_lines = []
        if mins_since_interact >= 0:
            time_lines.append(
                f"Minutes since last interaction: {mins_since_interact:.1f}"
            )
        else:
            time_lines.append("No interaction yet")
        if mins_since_initiative >= 0:
            time_lines.append(
                f"Minutes since last initiative: {mins_since_initiative:.1f}"
            )
        sections.append("## Timing\n" + "\n".join(time_lines))

        # 5. 表达约束
        from .phases import EXPRESSION_MODES
        mode = state.expression_mode
        constraints = EXPRESSION_MODES.get(mode, EXPRESSION_MODES["cry_only"])
        sections.append(
            f"## Expression Constraints\n"
            f"Mode: {mode}\n"
            f"Rules: {constraints['format']}"
        )

        # 6. 已解锁能力
        if state.capabilities:
            sections.append(
                "## Unlocked Capabilities\n"
                + ", ".join(state.capabilities)
            )

        # 7. 连续忽略次数
        if ini.consecutive_ignores > 0:
            sections.append(
                f"## Ignore Count\n"
                f"Consecutive ignores: {ini.consecutive_ignores}"
            )

        return "\n\n".join(sections)

    def get_behavior_space(self, state: BabyState) -> BehaviorSpace:
        return CRADLE_BEHAVIORS.get(state.current_phase, CRADLE_BEHAVIORS[0])

    def get_expression_mode(self, state: BabyState) -> str:
        return state.expression_mode

    def get_expression_constraints(self, state: BabyState) -> dict:
        from .phases import EXPRESSION_MODES
        return EXPRESSION_MODES.get(
            state.expression_mode, EXPRESSION_MODES["cry_only"],
        )

    def get_attachment_style(self, state: BabyState) -> str:
        return state.attachment_style

    def get_caregivers(self, state: BabyState) -> dict:
        return state.caregivers

    def get_stress_state(self, state: BabyState) -> StressState:
        return state.stress

    def apply_ignore_escalation(self, state: BabyState) -> None:
        from .nanny import _check_stress_regression
        _check_stress_regression(state)
        shift_attachment_toward_avoidant(state)

    def save_state(self, state: BabyState) -> None:
        from .state import save_state
        save_state(state)

    def get_species(self, state: BabyState) -> str:
        return state.species

    def get_age_days(self, state: BabyState) -> int:
        return state.age_days
