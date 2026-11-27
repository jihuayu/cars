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
SOURCES_FILE = DATA_DIR / "sources.json"

BRAND_ORDER = [
    # 国产新能源 (34)
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
    ("wuling", "五菱 / 宝骏"),
    ("chery-fulwin", "奇瑞风云 / 捷途山海"),
    ("gwm-haval-ora", "哈弗新能源 / 欧拉"),
    ("hongqi", "红旗新能源"),
    ("dongfeng-epai", "东风奕派 / 纳米 / 猛士"),
    ("saic-roewe-mg", "荣威 / MG新能源"),
    ("other-domestic", "极石 / 江淮钇为 / 北京越野"),
    # 中国大陆在售外资/合资新能源 (16)
    ("tesla", "特斯拉"),
    ("bmw", "宝马新能源"),
    ("mercedes", "奔驰新能源"),
    ("audi", "奥迪新能源"),
    ("porsche", "保时捷新能源"),
    ("volvo", "沃尔沃/极星"),
    ("volkswagen", "大众新能源"),
    ("toyota", "丰田新能源"),
    ("honda", "本田新能源"),
    ("nissan", "日产新能源"),
    ("gm", "通用新能源"),
    ("smart", "smart"),
    ("kia-hyundai", "起亚 / 现代新能源"),
    ("mini", "电动MINI"),
    ("lotus", "莲花跑车 / 路特斯"),
    ("joint-other", "马自达/福特/雷克萨斯"),
]

FOREIGN_BRANDS = {
    "tesla", "bmw", "mercedes", "audi", "porsche", "volvo",
    "volkswagen", "toyota", "honda", "nissan", "gm", "smart", "kia-hyundai", "mini", "lotus", "joint-other",
}

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


def is_affirmative(val) -> bool:
    if val is True:
        return True
    if val in (None, False, "", 0):
        return False
    s = str(val).strip()
    if not s or s in ("无", "不支持", "未知", "手动调节", "—", "-"):
        return False
    if s.startswith("不支持") or s.startswith("无（") or s.startswith("无("):
        return False
    return True


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
        f"共收录 **{root_index['total_brands']} 大品牌（国产 27 + 合资/外资 13） / {root_index['total_models']} 款在售主力车型 / {root_index['total_skus']} 个 SKU**（数据更新日期：**{root_index['data_as_of']}**），在线预览见 **[GitHub Pages 车型配置展厅](https://jihuayu.github.io/cars/)**，全量索引见 [`index.json`](./index.json)，数据结构定义见 [`schema.json`](./schema.json)。",
        "",
        "| 厂商目录 | 品牌 | 产地类型 | 车型数 | SKU 数 | 品牌索引 |",
        "| :--- | :--- | :--- | ---: | ---: | :--- |",
    ]
    for b in root_index["brands"]:
        slug = b["brand"]
        origin = "合资/外资" if slug in FOREIGN_BRANDS else "国产"
        lines.append(
            f"| `data/{slug}/` | {b['brand_name']} | {origin} | {b['model_count']} | {b['sku_count']} | [`data/{slug}/index.json`](./data/{slug}/index.json) |"
        )
    lines.append("<!-- STATS:END -->")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate car SKU JSON files and rebuild indexes.")
    parser.add_argument("--check", action="store_true", help="CI check mode: fail if index files are stale.")
    args = parser.parse_args()

    all_errors: list[str] = []
    seen_sku_ids: set[str] = set()
    latest_date = "2026-11-27"

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
        origin_type = "合资/外资" if brand_slug in FOREIGN_BRANDS else "国产"

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

            # Rich filter facets
            chem_set: set[str] = set()
            v2ls: list[float] = []
            gc_val = None
            has_air = False
            has_cdc = False
            has_rws = False
            has_rear_screen = False
            has_220v = False
            has_swap = False
            has_zg = False
            has_massage = False
            has_cushion_massage = False
            has_stream_in = False
            has_cms_out = False

            for s in skus:
                bc = s.get("battery_and_charging") or {}
                ch = s.get("chassis") or {}
                ck = s.get("cockpit") or {}
                dm = s.get("dimensions") or {}

                if gc_val is None and dm.get("ground_clearance_mm") not in (None, ""):
                    gc_val = dm["ground_clearance_mm"]

                chem = str(bc.get("battery_chemistry") or bc.get("battery_type") or "")
                if "磷酸铁锂" in chem or "刀片" in chem or "金砖" in chem or "短刀" in chem:
                    chem_set.add("磷酸铁锂")
                if "三元锂" in chem or "麒麟" in chem:
                    chem_set.add("三元锂")

                v2l = bc.get("v2l_power_kw")
                if isinstance(v2l, (int, float)) and v2l > 0:
                    v2ls.append(float(v2l))
                if bc.get("battery_swap_supported") is True:
                    has_swap = True

                if is_affirmative(ch.get("air_suspension")):
                    has_air = True
                if is_affirmative(ch.get("cdc")):
                    has_cdc = True
                if is_affirmative(ch.get("rear_wheel_steering")):
                    has_rws = True

                if is_affirmative(ck.get("rear_screen")):
                    has_rear_screen = True
                if is_affirmative(ck.get("power_220v")):
                    has_220v = True
                if is_affirmative(ck.get("zero_gravity_seat")):
                    has_zg = True
                msg_txt = str(ck.get("seat_massage") or "")
                if is_affirmative(msg_txt):
                    has_massage = True
                    if any(k in msg_txt for k in ("明确含座垫", "明确含靠背、坐垫", "明确含靠背及坐垫", "含4点臀部", "明确含座垫/臀部", "坐垫6点", "座垫6点")):
                        has_cushion_massage = True
                if is_affirmative(ck.get("streaming_interior_mirror")):
                    has_stream_in = True
                if is_affirmative(ck.get("streaming_exterior_mirrors")):
                    has_cms_out = True

            has_promo = bool(data.get("promo_highlights")) or any(
                o.get("promo_price_rmb") is not None or o.get("promo_note")
                for s in skus
                for o in (s.get("options") or [])
                if isinstance(o, dict)
            )
            has_miit = bool(data.get("miit_filing"))

            brand_skus += len(skus)
            entry = {
                "brand": brand_slug,
                "brand_name": resolved_brand_name,
                "origin_type": data.get("origin_type") or origin_type,
                "model": data["model"],
                "model_slug": data["model_slug"],
                "sub_brand": data.get("sub_brand"),
                "category": data.get("category"),
                "release_date": data.get("release_date"),
                "image_url": data.get("image_url"),
                "interior_image_url": data.get("interior_image_url"),
                "powertrains": pts,
                "battery_chemistries": sorted(chem_set),
                "sku_count": len(skus),
                "option_count": len(opt_names),
                "price_min_rmb": min(prices) if prices else None,
                "price_max_rmb": max(prices) if prices else None,
                "best_zero_to_100_s": min(accs) if accs else None,
                "max_cltc_ev_km": max(cltcs) if cltcs else None,
                "ground_clearance_mm": gc_val,
                "max_v2l_kw": max(v2ls) if v2ls else None,
                "has_air_suspension": has_air,
                "has_cdc": has_cdc,
                "has_rws": has_rws,
                "has_rear_screen": has_rear_screen,
                "has_220v": has_220v,
                "has_v2l": bool(v2ls),
                "has_swap": has_swap,
                "has_zero_gravity": has_zg,
                "has_seat_massage": has_massage,
                "has_cushion_massage": has_cushion_massage,
                "has_streaming_mirror": has_stream_in,
                "has_cms_mirrors": has_cms_out,
                "has_promo": has_promo,
                "has_miit": has_miit,
                "file": f"data/{brand_slug}/{mf.name}",
                "source_urls": data.get("source_urls", []),
            }
            models_summary.append(entry)
            catalog_models.append(entry)

        brand_index = {
            "brand": brand_slug,
            "brand_name": resolved_brand_name,
            "origin_type": origin_type,
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
                "origin_type": origin_type,
                "model_count": len(models_summary),
                "sku_count": brand_skus,
                "index_file": f"data/{brand_slug}/index.json",
            }
        )

    miit_portals = []
    if SOURCES_FILE.exists():
        miit_portals = json.loads(SOURCES_FILE.read_text(encoding="utf-8")).get("miit_portals", [])

    root_index["data_as_of"] = latest_date
    pending_writes.append((ROOT_INDEX, json.dumps(root_index, ensure_ascii=False, indent=2) + "\n"))
    catalog_payload = {
        "data_as_of": latest_date,
        "total_brands": root_index["total_brands"],
        "total_models": root_index["total_models"],
        "total_skus": root_index["total_skus"],
        "miit_portals": miit_portals,
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
