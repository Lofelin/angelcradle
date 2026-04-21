"""
肖像分配：根据出生国家从预设头像库选择。

avatar/ 目录按国家命名（如 china_01.png, japan_02.png），
分配时优先匹配宝宝的出生国家，无匹配则随机选择。

[INPUT]: backend/avatar/*.png 预设头像库, state.birthplace
[OUTPUT]: generate_portrait(), get_portrait_path(), get_latest_portrait(), should_update_portrait()
[POS]: 顶级模块���被 cradle/__init__.py (admit) 和 scheduler/handlers.py (phase_complete) 消费
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import logging
import os
import random
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

ARCHIVE_DIR = Path(os.environ.get("ARCHIVE_DIR", "archive"))
AVATAR_DIR = Path(__file__).parent / "avatar"

# ── 国家名 / code → avatar 文件前缀映射 ─────────────
# regions.yaml 的 name/code → avatar 文件夹中的前缀
# avatar 前缀从文件名提取（如 china_01.png → "china"）

_COUNTRY_TO_PREFIX = {
    # 直接匹配（regions.yaml name → avatar prefix）
    "china": "china",
    "india": "india",
    "united states": "usa",
    "indonesia": "indonesia",
    "pakistan": "pakistan",
    "brazil": "brazil",
    "nigeria": "nigeria",
    "bangladesh": "bangladesh",
    "russia": "russia",
    "japan": "japan",
    "mexico": "mexico",
    "ethiopia": "ethiopia",
    "germany": "germany",
    "egypt": "egypt",
    "united kingdom": "uk",
    "south korea": "korea",
    "south africa": "southafrica",
    "france": "france",
    "thailand": "thailand",
    "saudi arabia": "saudi",
    "australia": "uk",  # 无专属，回退到文化近似
    "canada": "canada",
    "vietnam": "vietnam",
    "turkey": "turkey",
    "dr congo": "congo",
}

# ISO code → avatar prefix（备选匹配）
_CODE_TO_PREFIX = {
    "CN": "china",
    "IN": "india",
    "US": "usa",
    "ID": "indonesia",
    "PK": "pakistan",
    "BR": "brazil",
    "NG": "nigeria",
    "BD": "bangladesh",
    "RU": "russia",
    "JP": "japan",
    "MX": "mexico",
    "ET": "ethiopia",
    "DE": "germany",
    "EG": "egypt",
    "GB": "uk",
    "KR": "korea",
    "ZA": "southafrica",
    "FR": "france",
    "TH": "thailand",
    "SA": "saudi",
    "AU": "uk",
    "CA": "canada",
    "VN": "vietnam",
    "TR": "turkey",
    "CD": "congo",
}

# region → 回退 avatar prefix（没有精确匹配时按区域选）
_REGION_TO_PREFIXES = {
    "east_asia": ["china", "japan", "korea", "mongolia"],
    "south_asia": ["india", "bangladesh", "pakistan", "nepal", "srilanka"],
    "southeast_asia": ["indonesia", "thailand", "vietnam", "philippines",
                       "cambodia", "myanmar", "malaysia", "singapore"],
    "europe": ["france", "germany", "uk", "italy", "spain", "netherlands",
               "poland", "sweden", "norway", "finland", "greece", "ireland",
               "scotland"],
    "sub_saharan_africa": ["nigeria", "ethiopia", "kenya", "ghana",
                           "congo", "tanzania", "southafrica", "sudan"],
    "north_africa_middle_east": ["egypt", "arab", "iran", "iraq", "jordan",
                                 "morocco", "saudi", "turkey", "israel"],
    "latin_america": ["brazil", "mexico", "argentina", "colombia", "peru",
                      "chile", "cuba", "bolivia", "jamaica"],
    "north_america": ["usa", "canada"],
    "oceania": ["usa"],  # 无 Oceania 专属头像，回退
}


def _resolve_avatar_prefix(state) -> str | None:
    """从 state.birthplace 推断 avatar 文件前缀。"""
    bp = getattr(state, "birthplace", None)
    if not bp or not isinstance(bp, dict):
        return None

    # 1. 按国家名精确匹配
    name = (bp.get("name") or "").lower().strip()
    if name in _COUNTRY_TO_PREFIX:
        return _COUNTRY_TO_PREFIX[name]

    # 2. 按 ISO code 匹配
    code = (bp.get("code") or "").upper().strip()
    if code in _CODE_TO_PREFIX:
        return _CODE_TO_PREFIX[code]

    # 3. 按 region 回退
    region = (bp.get("region") or "").lower().strip()
    if region in _REGION_TO_PREFIXES:
        return random.choice(_REGION_TO_PREFIXES[region])

    return None


def _find_avatars_by_prefix(prefix: str) -> list[Path]:
    """查找指定国家前缀的所有 avatar 文件。"""
    return list(AVATAR_DIR.glob(f"{prefix}_*.png"))


def generate_portrait(state, age_years: int = 0) -> str | None:
    """
    根据出生国家从 avatar/ 选择头像。

    优先匹配国家 → 区域回退 → 全局随机。
    若该 baby 已有任何肖像则跳过（幂等）。
    """
    baby_dir = ARCHIVE_DIR / state.baby_id
    baby_dir.mkdir(parents=True, exist_ok=True)
    portrait_path = baby_dir / f"portrait_{age_years}.png"

    # 已有肖像：跳过
    if portrait_path.is_file():
        return str(portrait_path)

    # 如果已有其他年龄的肖像，复用最新的（所有年��共用同一张）
    existing = get_latest_portrait(state.baby_id)
    if existing:
        shutil.copy2(existing, portrait_path)
        return str(portrait_path)

    # 按国家匹配 avatar
    prefix = _resolve_avatar_prefix(state)
    candidates = _find_avatars_by_prefix(prefix) if prefix else []

    if not candidates:
        # 全局随机回退
        candidates = list(AVATAR_DIR.glob("*.png"))
        if not candidates:
            logger.warning("No avatar files found in %s", AVATAR_DIR)
            return None
        logger.info(
            "No avatar for country prefix '%s', random fallback", prefix,
        )

    chosen = random.choice(candidates)
    shutil.copy2(chosen, portrait_path)
    logger.info(
        "Portrait assigned: %s → %s (prefix=%s)",
        chosen.name, portrait_path, prefix or "random",
    )
    return str(portrait_path)


def get_portrait_path(baby_id: str, age_years: int = 0) -> Path | None:
    """获取指定年龄的肖像路径，不存���返回 None。"""
    path = ARCHIVE_DIR / baby_id / f"portrait_{age_years}.png"
    return path if path.is_file() else None


def get_latest_portrait(baby_id: str) -> Path | None:
    """获取最新的肖像文件。"""
    baby_dir = ARCHIVE_DIR / baby_id
    if not baby_dir.is_dir():
        return None
    portraits = sorted(baby_dir.glob("portrait_*.png"), reverse=True)
    return portraits[0] if portraits else None


def should_update_portrait(age_days: int) -> int | None:
    """
    检查是否���该更新肖像。返回目标 age_years，或 None。

    保留接口兼容，但��于所有年龄共用同一��，实际效果是复制���有肖像。
    """
    age_years = age_days // 365
    if age_years > 0 and age_years % 5 == 0:
        return age_years
    return None
