#!/usr/bin/env python3
"""Validate all brand/model SKU JSON files and rebuild index.json, catalog.json & README stats.

Usage:
  python3 scripts/validate_and_index.py          # validate + regenerate indexes & README stats
  python3 scripts/validate_and_index.py --check  # validate only (CI mode, fails if indexes are stale)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
ROOT_INDEX = REPO_ROOT / "index.json"
CATALOG_FILE = REPO_ROOT / "catalog.json"
README_FILE = REPO_ROOT / "README.md"

BRAND_ORDER = [
    ("lixiang", "理想汽车"),
    ("xiaopeng", "小鹏汽车"),
    ("avatr", "阿维塔"),
    ("nio", "蔚来"),
    ("onvo", "乐道"),
    ("firefly", "萤火虫"),
    ("leapmotor", "零跑汽车"),
    ("immotors", "智己汽车"),
    ("hima", "鸿蒙智行"),
    ("xiaomi", "小米汽车"),
    ("zeekr", "极氪"),
    ("lynkco", "领克新能源"),
    ("byd", "比亚迪"),
    ("denza", "腾势"),
    ("fangchengbao", "方程豹"),
    ("yangwang", "仰望"),
    ("voyah", "岚图"),
    ("deepal", "深蓝"),
    ("geely-galaxy", "吉利银河"),
    ("changan-qiyuan", "长安启源"),
    ("exeed-sterra", "星途星纪元"),
    ("icar", "iCAR"),
    ("hyptec", "广汽昊铂"),
    ("aion", "广汽埃安"),
    ("arcfox", "极狐"),
    ("wey", "魏牌"),
    ("tank", "坦克新能源"),
]

REQUIRED_MODEL_KEYS = {"brand", "brand_name", "model", "model_slug", "data_as_of", "skus"}
REQUIRED_SKU_KEYS = {
    "sku_id",
    "sku_name",
    "price_rmb",
    "powertrain_type",
    "dimensions",
    "performance",
    "battery_and_charging",
    "chassis",
    "adas",
    "cockpit",
    "options",
}
VALID_POWERTRAINS = {"BEV", "REEV", "PHEV", None}


def validate_model_file(path: Path, expected_brand: str, seen_sku_ids: set[str]) -> tuple[dict, list[str]]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [f"{path}: invalid JSON ({exc})"]

    missing = REQUIRED_MODEL_KEYS - set(data.keys())
    if missing:
        errors.append(f"{path}: missing top-level keys {sorted(missing)}")

    if data.get("brand") != expected_brand:
        errors.append(f"{path}: brand={data.get('brand')!r} does not match directory {expected_brand!r}")

    skus = data.get("skus")
    if not isinstance(skus, list) or not skus:
        errors.append(f"{path}: 'skus' must be a non-empty list")
        return data, errors

    for idx, sku in enumerate(skus):
        if not isinstance(sku, dict):
            errors.append(f"{path}: skus[{idx}] is not an object")
            continue
        sku_missing = REQUIRED_SKU_KEYS - set(sku.keys())
        if sku_missing:
            errors.append(f"{path}: skus[{idx}] missing keys {sorted(sku_missing)}")

        sid = sku.get("sku_id")
        if not isinstance(sid, str) or not sid.strip():
            errors.append(f"{path}: skus[{idx}] invalid sku_id")
        elif sid in seen_sku_ids:
            errors.append(f"{path}: duplicate sku_id {sid!r}")
        else:
            seen_sku_ids.add(sid)

        price = sku.get("price_rmb")
        if price is not None and not isinstance(price, (int, float)):
            errors.append(f"{path}: sku {sid} price_rmb must be number or null, got {type(price).__name__}")

        pt = sku.get("powertrain_type")
        if pt not in VALID_POWERTRAINS:
            errors.append(f"{path}: sku {sid} invalid powertrain_type {pt!r}")

        if not isinstance(sku.get("options"), list):
            errors.append(f"{path}: sku {sid} options must be a list")

    return data, errors


def build_readme_stats_block(root_index: dict) -> str:
    lines = [
        "<!-- STATS:START -->",
        f"共收录 **{root_index['total_brands']} 大品牌 / {root_index['total_models']} 款主力车型 / {root_index['total_skus']} 个在售 SKU**（数据更新日期：**{root_index['data_as_of']}**，外观图与选装明细 100% 覆盖），在线预览见 **[GitHub Pages 车型配置展厅](https://jihuayu.github.io/cars/)**，全量索引见 [`index.json`](./index.json)，数据结构定义见 [`schema.json`](./schema.json)。",
        "",
        "| 厂商目录 | 品牌 | 车型数 | SKU 数 | 品牌索引 |",
        "| :--- | :--- | ---: | ---: | :--- |",
    ]
    for b in root_index["brands"]:
        slug = b["brand"]
        lines.append(
            f"| `data/{slug}/` | {b['brand_name']} | {b['model_count']} | {b['sku_count']} | [`data/{slug}/index.json`](./data/{slug}/index.json) |"
        )
    lines.append("<!-- STATS:END -->")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate car SKU JSON files and rebuild indexes.")
    parser.add_argument("--check", action="store_true", help="CI check mode: fail if index files are stale.")
    args = parser.parse_args()

    all_errors: list[str] = []
    seen_sku_ids: set[str] = set()
    latest_date = "2026-11-26"

    brand_dirs = {p.name for p in DATA_DIR.iterdir() if p.is_dir()} if DATA_DIR.exists() else set()
    ordered_brands = list(BRAND_ORDER)
    known_slugs = {b[0] for b in BRAND_ORDER}
    for extra in sorted(brand_dirs - known_slugs):
        ordered_brands.append((extra, extra))

    root_index = {
        "data_as_of": latest_date,
        "schema": "./schema.json",
        "total_brands": 0,
        "total_models": 0,
        "total_skus": 0,
        "brands": [],
    }
    catalog_models = []
    pending_writes: list[tuple[Path, str]] = []

    for brand_slug, brand_cn in ordered_brands:
        bdir = DATA_DIR / brand_slug
        if not bdir.exists():
            continue
        model_files = sorted(p for p in bdir.glob("*.json") if p.name != "index.json")
        if not model_files:
            continue

        models_summary = []
        brand_skus = 0
        resolved_brand_name = brand_cn

        for mf in model_files:
            data, errs = validate_model_file(mf, brand_slug, seen_sku_ids)
            all_errors.extend(errs)
            if not data:
                continue

            resolved_brand_name = data.get("brand_name") or brand_cn
            d_as_of = data.get("data_as_of")
            if isinstance(d_as_of, str) and d_as_of > latest_date:
                latest_date = d_as_of

            skus = data.get("skus", [])
            prices = [s["price_rmb"] for s in skus if isinstance(s.get("price_rmb"), (int, float))]
            pts = sorted({s["powertrain_type"] for s in skus if s.get("powertrain_type")})
            accs = [
                s["performance"]["zero_to_100_s"]
                for s in skus
                if isinstance((s.get("performance") or {}).get("zero_to_100_s"), (int, float))
            ]
            cltcs = [
                s["battery_and_charging"]["cltc_pure_electric_range_km"]
                for s in skus
                if isinstance((s.get("battery_and_charging") or {}).get("cltc_pure_electric_range_km"), (int, float))
            ]
            opt_names = {
                str(o.get("name", "")).strip()
                for s in skus
                for o in (s.get("options") or [])
                if isinstance(o, dict) and o.get("name")
            }
            brand_skus += len(skus)
            entry = {
                "brand": brand_slug,
                "brand_name": resolved_brand_name,
                "model": data["model"],
                "model_slug": data["model_slug"],
                "sub_brand": data.get("sub_brand"),
                "category": data.get("category"),
                "release_date": data.get("release_date"),
                "image_url": data.get("image_url"),
                "powertrains": pts,
                "sku_count": len(skus),
                "option_count": len(opt_names),
                "price_min_rmb": min(prices) if prices else None,
                "price_max_rmb": max(prices) if prices else None,
                "best_zero_to_100_s": min(accs) if accs else None,
                "max_cltc_ev_km": max(cltcs) if cltcs else None,
                "file": f"data/{brand_slug}/{mf.name}",
                "source_urls": data.get("source_urls", []),
            }
            models_summary.append(entry)
            catalog_models.append(entry)

        brand_index = {
            "brand": brand_slug,
            "brand_name": resolved_brand_name,
            "data_as_of": latest_date,
            "model_count": len(models_summary),
            "sku_count": brand_skus,
            "models": models_summary,
        }
        pending_writes.append((bdir / "index.json", json.dumps(brand_index, ensure_ascii=False, indent=2) + "\n"))

        root_index["total_brands"] += 1
        root_index["total_models"] += len(models_summary)
        root_index["total_skus"] += brand_skus
        root_index["brands"].append(
            {
                "brand": brand_slug,
                "brand_name": resolved_brand_name,
                "model_count": len(models_summary),
                "sku_count": brand_skus,
                "index_file": f"data/{brand_slug}/index.json",
            }
        )

    root_index["data_as_of"] = latest_date
    pending_writes.append((ROOT_INDEX, json.dumps(root_index, ensure_ascii=False, indent=2) + "\n"))
    catalog_payload = {
        "data_as_of": latest_date,
        "total_brands": root_index["total_brands"],
        "total_models": root_index["total_models"],
        "total_skus": root_index["total_skus"],
        "brands": root_index["brands"],
        "models": catalog_models,
    }
    pending_writes.append((CATALOG_FILE, json.dumps(catalog_payload, ensure_ascii=False, indent=2) + "\n"))

    if README_FILE.exists():
        readme_text = README_FILE.read_text(encoding="utf-8")
        if "<!-- STATS:START -->" in readme_text and "<!-- STATS:END -->" in readme_text:
            updated_readme = re.sub(
                r"<!-- STATS:START -->.*?<!-- STATS:END -->",
                build_readme_stats_block(root_index),
                readme_text,
                flags=re.S,
            )
            pending_writes.append((README_FILE, updated_readme))

    if all_errors:
        print("VALIDATION FAILED:", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    stale_files = []
    for target, content in pending_writes:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != content:
            if args.check:
                stale_files.append(str(target.relative_to(REPO_ROOT)))
            else:
                target.write_text(content, encoding="utf-8")

    if args.check and stale_files:
        print("STALE INDEX/README FILES (run `python3 scripts/validate_and_index.py`):", file=sys.stderr)
        for sf in stale_files:
            print(f"  - {sf}", file=sys.stderr)
        return 1

    print(
        f"OK: {root_index['total_brands']} brands, "
        f"{root_index['total_models']} models, "
        f"{root_index['total_skus']} unique SKUs validated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
