"""
文化感知自动命名（turbo 模式用）。

[INPUT]: state.birthplace, state.phenotype
[OUTPUT]: auto_name(state) -> str
[POS]: scheduler/ 的命名数据模块
[PROTOCOL]: 变更时更新此头部，然后检查 scheduler/CLAUDE.md
"""

from __future__ import annotations

import logging
import random

logger = logging.getLogger(__name__)


# ============================================================
# 按国家/地区代码分组的常见名字池
# ============================================================

_NAME_POOLS: dict[str, dict] = {
    "CN": {
        "surnames": ["李", "王", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
                     "徐", "孙", "马", "朱", "胡", "林", "何", "郭", "罗", "高"],
        "given_m": ["浩然", "子轩", "宇航", "明辉", "俊杰", "天佑", "文博", "志远", "嘉禾", "思源"],
        "given_f": ["诗涵", "欣怡", "雨桐", "梓萱", "若曦", "思琪", "语嫣", "芷若", "婉清", "梦瑶"],
        "format": "surname_first",
    },
    "JP": {
        "surnames": ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤"],
        "given_m": ["蓮", "陽翔", "湊", "樹", "悠真", "颯", "朝陽", "蒼", "律", "結翔"],
        "given_f": ["陽葵", "凛", "詩", "芽依", "葵", "結菜", "莉子", "紬", "澪", "花"],
        "format": "surname_first",
    },
    "KR": {
        "surnames": ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"],
        "given_m": ["서준", "도윤", "시우", "주원", "하준", "지호", "준서", "건우", "민준", "현우"],
        "given_f": ["서연", "서윤", "지우", "하은", "하윤", "민서", "지유", "채원", "수아", "지아"],
        "format": "surname_first",
    },
    "US": {
        "surnames": ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
                     "Miller", "Davis", "Rodriguez", "Martinez"],
        "given_m": ["Liam", "Noah", "Oliver", "James", "Elijah", "Henry", "Lucas", "Mason", "Ethan", "Logan"],
        "given_f": ["Olivia", "Emma", "Charlotte", "Amelia", "Sophia", "Mia", "Isabella", "Ava", "Luna", "Harper"],
        "format": "given_first",
    },
    "GB": {
        "surnames": ["Smith", "Jones", "Taylor", "Brown", "Wilson", "Evans",
                     "Thomas", "Roberts", "Walker", "Wright"],
        "given_m": ["Noah", "Oliver", "George", "Arthur", "Leo", "Harry", "Oscar", "Jack", "Henry", "Charlie"],
        "given_f": ["Olivia", "Amelia", "Isla", "Freya", "Lily", "Florence", "Ivy", "Willow", "Rosie", "Mia"],
        "format": "given_first",
    },
    "IN": {
        "surnames": ["Sharma", "Patel", "Singh", "Kumar", "Gupta", "Reddy",
                     "Nair", "Joshi", "Das", "Mehta"],
        "given_m": ["Aarav", "Vihaan", "Aditya", "Sai", "Arjun", "Reyansh", "Krishna", "Kabir", "Vivaan", "Ishaan"],
        "given_f": ["Aadhya", "Ananya", "Diya", "Saanvi", "Kiara", "Myra", "Aisha", "Priya", "Riya", "Kavya"],
        "format": "given_first",
    },
    "DE": {
        "surnames": ["Müller", "Schmidt", "Schneider", "Fischer", "Weber",
                     "Meyer", "Wagner", "Becker", "Hoffmann", "Schulz"],
        "given_m": ["Noah", "Matteo", "Elias", "Finn", "Leon", "Paul", "Ben", "Luca", "Emil", "Felix"],
        "given_f": ["Emilia", "Mia", "Sophia", "Emma", "Hannah", "Lina", "Ella", "Mila", "Clara", "Marie"],
        "format": "given_first",
    },
    "FR": {
        "surnames": ["Martin", "Bernard", "Dubois", "Thomas", "Robert",
                     "Richard", "Petit", "Durand", "Leroy", "Moreau"],
        "given_m": ["Gabriel", "Léo", "Raphaël", "Arthur", "Louis", "Jules", "Adam", "Maël", "Hugo", "Lucas"],
        "given_f": ["Emma", "Jade", "Louise", "Alice", "Ambre", "Léa", "Rose", "Anna", "Romy", "Mia"],
        "format": "given_first",
    },
    "BR": {
        "surnames": ["Silva", "Santos", "Oliveira", "Souza", "Rodrigues",
                     "Ferreira", "Alves", "Pereira", "Lima", "Gomes"],
        "given_m": ["Miguel", "Arthur", "Heitor", "Bernardo", "Théo", "Davi", "Gabriel", "Samuel", "Pedro", "Rafael"],
        "given_f": ["Helena", "Alice", "Laura", "Maria", "Valentina", "Heloísa", "Sophia", "Liz", "Cecília", "Maitê"],
        "format": "given_first",
    },
    "RU": {
        "surnames": ["Иванов", "Смирнов", "Кузнецов", "Попов", "Васильев",
                     "Петров", "Соколов", "Михайлов", "Новиков", "Фёдоров"],
        "given_m": ["Александр", "Михаил", "Артём", "Максим", "Иван", "Дмитрий", "Матвей", "Даниил", "Тимофей", "Лев"],
        "given_f": ["София", "Мария", "Анна", "Алиса", "Виктория", "Полина", "Варвара", "Ева", "Елизавета", "Ксения"],
        "format": "given_first",
    },
    "NG": {
        "surnames": ["Okafor", "Adeyemi", "Obi", "Ibrahim", "Bello",
                     "Musa", "Okeke", "Abubakar", "Nwosu", "Eze"],
        "given_m": ["Chukwuemeka", "Oluwaseun", "Chijioke", "Adebayo", "Emeka", "Obinna", "Ikenna", "Tunde", "Yusuf", "Kofi"],
        "given_f": ["Ngozi", "Amara", "Chinwe", "Oluwadamilola", "Adaeze", "Ifeoma", "Folake", "Blessing", "Fatima", "Zainab"],
        "format": "given_first",
    },
}

# 区域兜底映射
_REGION_FALLBACK: dict[str, str] = {
    "East Asia": "CN", "Southeast Asia": "CN", "South Asia": "IN",
    "Western Europe": "GB", "Eastern Europe": "RU", "Northern Europe": "GB",
    "Southern Europe": "FR", "North America": "US", "South America": "BR",
    "Central America": "US", "Middle East": "IN", "North Africa": "FR",
    "Sub-Saharan Africa": "NG", "Oceania": "US",
}


def auto_name(state) -> str:
    """根据出生地文化习惯生成名字。纯规则，不调 LLM。"""
    bp = getattr(state, "birthplace", {}) or {}
    code = bp.get("code", "")
    region = bp.get("region", "")
    sex = getattr(state, "phenotype", {}).get("sex") if hasattr(state, "phenotype") else None

    logger.info(
        "auto_name 入参: baby=%s, birthplace=%s, code=%r, region=%r, sex=%r",
        getattr(state, "baby_id", "?"), bp, code, region, sex,
    )

    # 查找名字池：先按国家代码，再按区域兜底，最后用 US
    pool = _NAME_POOLS.get(code)
    if pool is None and region:
        fallback_code = _REGION_FALLBACK.get(region, "US")
        pool = _NAME_POOLS.get(fallback_code, _NAME_POOLS["US"])
    if pool is None:
        pool = _NAME_POOLS["US"]
    if sex == "female":
        given = random.choice(pool["given_f"])
    elif sex == "male":
        given = random.choice(pool["given_m"])
    else:
        given = random.choice(pool["given_m"] + pool["given_f"])
    surname = random.choice(pool["surnames"])

    if pool["format"] == "surname_first":
        name = f"{surname}{given}"
    else:
        name = f"{given} {surname}"
    logger.info("auto_name 结果: baby=%s, name=%r, pool_code=%s", getattr(state, "baby_id", "?"), name, code or "US(fallback)")
    return name
