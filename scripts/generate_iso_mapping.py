"""
一次性脚本：生成 backend/womb/data/iso_alpha2_to_numeric.json

依赖 pycountry（仅 dev 时使用），生成产物后 prod 运行时无需此依赖。

用法：
    pip install pycountry
    python scripts/generate_iso_mapping.py

产物：
    backend/womb/data/iso_alpha2_to_numeric.json
    格式：{"CN": "156", "US": "840", ...}
"""
from __future__ import annotations

import json
from pathlib import Path

import pycountry

OUT_PATH = Path(__file__).parent.parent / "backend" / "womb" / "data" / "iso_alpha2_to_numeric.json"


def main() -> None:
    mapping: dict[str, str] = {}
    for country in pycountry.countries:
        alpha2 = getattr(country, "alpha_2", None)
        numeric = getattr(country, "numeric", None)
        if alpha2 and numeric:
            mapping[alpha2.upper()] = str(numeric).zfill(3)

    mapping = dict(sorted(mapping.items()))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(mapping)} mappings to {OUT_PATH}")
    print(f"sample: CN={mapping.get('CN')}, US={mapping.get('US')}, JP={mapping.get('JP')}")


if __name__ == "__main__":
    main()
