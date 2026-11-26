#!/usr/bin/env python3
"""Official automaker configuration page sync & drift-detection script.

Reads `source_urls` directly from `data/<brand>/<model>.json`, fetches official
configuration pages via HTTP (for SSR / Next.js `__NEXT_DATA__` sites) or
Playwright headless Chromium (`--browser`, for client-rendered SPAs), extracts
verified price/spec updates non-destructively, records content hashes in
`.sync_state.json`, and writes a Markdown sync report for GitHub Actions PRs.

Usage:
  python3 scripts/sync_official.py --dry-run
  python3 scripts/sync_official.py --brand xiaopeng --browser --write-report sync_report.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
STATE_FILE = REPO_ROOT / ".sync_state.json"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Sites that generally require JS rendering for full parameter tables
SPA_DOMAINS = {
    "www.lixiang.com",
    "lixiang.com",
    "www.nio.cn",
    "nio.cn",
    "leapmotor.cn",
    "www.leapmotor.cn",
    "cn.leapmotor.com",
}


def fetch_http(url: str, timeout: int = 20) -> tuple[int, str]:
    import requests

    resp = requests.get(
        url,
        headers={
            "User-Agent": DEFAULT_UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        timeout=timeout,
    )
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.status_code, resp.text


def fetch_playwright(url: str, timeout_ms: int = 30000) -> tuple[int, str, list[dict[str, Any]]]:
    """Render SPA page with Playwright and capture JSON XHR payloads."""
    from playwright.sync_api import sync_playwright

    captured_json: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=DEFAULT_UA, locale="zh-CN")
        page = context.new_page()

        def on_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "application/json" in ct and response.status == 200:
                    if any(k in response.url.lower() for k in ("config", "param", "car", "vehicle", "sku", "spec")):
                        data = response.json()
                        captured_json.append({"url": response.url, "data": data})
            except Exception:
                pass

        page.on("response", on_response)
        resp = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(1500)
        html = page.content()
        status = resp.status if resp else 200
        browser.close()
    return status, html, captured_json


def extract_next_data(html: str) -> dict[str, Any] | None:
    m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def extract_visible_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    except ImportError:
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()


def extract_metrics_from_text(text: str) -> dict[str, Any]:
    """Extract high-confidence structured signals from official config text."""
    signals: dict[str, Any] = {}

    # Dimensions: e.g. 4891/1937/1670 or 4891*1937*1670 or 4891×1937×1670
    m_dim = re.search(r"(\d{4})\s*[/\*×xX]\s*(\d{4})\s*[/\*×xX]\s*(\d{4})", text)
    if m_dim:
        signals["dimensions"] = {
            "length_mm": int(m_dim.group(1)),
            "width_mm": int(m_dim.group(2)),
            "height_mm": int(m_dim.group(3)),
        }

    # Wheelbase: e.g. 轴距（mm） 2998
    m_wb = re.search(r"轴距[^0-9]{0,12}(\d{4})", text)
    if m_wb:
        signals.setdefault("dimensions", {})["wheelbase_mm"] = int(m_wb.group(1))

    # Prices: e.g. ¥248,800 or ￥248,800
    raw_prices = re.findall(r"[¥￥]\s*(\d{2,3},\d{3}|\d{5,7})", text)
    parsed_prices = sorted({int(p.replace(",", "")) for p in raw_prices if 50000 <= int(p.replace(",", "")) <= 2000000})
    if parsed_prices:
        signals["detected_prices_rmb"] = parsed_prices

    return signals


def merge_non_destructive(model_data: dict[str, Any], signals: dict[str, Any]) -> list[str]:
    """Fill null dimension fields non-destructively when official page confirms them."""
    changes: list[str] = []
    dims = signals.get("dimensions") or {}
    if not dims:
        return changes

    for sku in model_data.get("skus", []):
        sku_dims = sku.setdefault("dimensions", {})
        for k in ("length_mm", "width_mm", "height_mm", "wheelbase_mm"):
            if sku_dims.get(k) is None and k in dims:
                sku_dims[k] = dims[k]
                changes.append(f"{sku['sku_id']}: filled dimensions.{k}={dims[k]}")

    return changes


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync official NEV configuration pages.")
    parser.add_argument("--brand", help="Only sync a specific brand slug (e.g. xiaopeng, nio)")
    parser.add_argument("--browser", action="store_true", help="Enable Playwright Chromium for SPA pages")
    parser.add_argument("--dry-run", action="store_true", help="Do not modify JSON files or .sync_state.json")
    parser.add_argument("--write-report", type=Path, help="Write Markdown sync report to this path")
    args = parser.parse_args()

    state = load_state()
    today_str = date.today().isoformat()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    report_lines = [
        f"## 自动同步报告（{today_str}）",
        "",
        f"- 运行时间 (UTC): `{now_iso}`",
        f"- 模式: `{'browser (Playwright + HTTP)' if args.browser else 'HTTP only'}` | `{'dry-run' if args.dry_run else 'write'}`",
        "",
        "| 品牌 | 车型 | 官方源 URL | 状态 | 内容变化 | 自动补全/变更 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    total_checked = 0
    total_ok = 0
    total_changed_pages = 0
    total_field_updates = 0

    brand_dirs = sorted(p for p in DATA_DIR.iterdir() if p.is_dir())
    for bdir in brand_dirs:
        if args.brand and bdir.name != args.brand:
            continue

        for mf in sorted(p for p in bdir.glob("*.json") if p.name != "index.json"):
            model_data = json.loads(mf.read_text(encoding="utf-8"))
            urls = model_data.get("source_urls") or []
            if not urls:
                continue

            primary_url = urls[0]
            host = urlparse(primary_url).netloc.lower()
            total_checked += 1

            status_str = "skipped"
            changed_str = "—"
            field_changes: list[str] = []

            try:
                if args.browser and host in SPA_DOMAINS:
                    code, html, _xhr = fetch_playwright(primary_url)
                else:
                    code, html = fetch_http(primary_url)
                    if args.browser and len(html) < 5000:
                        code, html, _xhr = fetch_playwright(primary_url)

                if code == 200 and html:
                    total_ok += 1
                    status_str = f"HTTP {code}"
                    next_data = extract_next_data(html)
                    visible_text = extract_visible_text(html)
                    fingerprint_src = json.dumps(next_data, sort_keys=True) if next_data else visible_text
                    content_hash = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()[:16]

                    prev_hash = state.get(primary_url, {}).get("hash")
                    if prev_hash is None:
                        changed_str = "首次记录"
                    elif prev_hash != content_hash:
                        changed_str = "官网内容已更新"
                        total_changed_pages += 1
                    else:
                        changed_str = "无变化"

                    signals = extract_metrics_from_text(visible_text)
                    field_changes = merge_non_destructive(model_data, signals)

                    # Flag price list drift against recorded SKU prices
                    known_prices = sorted(
                        {int(s["price_rmb"]) for s in model_data.get("skus", []) if isinstance(s.get("price_rmb"), (int, float))}
                    )
                    detected_prices = signals.get("detected_prices_rmb") or []
                    new_prices = [p for p in detected_prices if p not in known_prices]
                    if new_prices and len(new_prices) <= 6:
                        field_changes.append(f"检测到新价格信号: {new_prices}")

                    if not args.dry_run:
                        state[primary_url] = {
                            "hash": content_hash,
                            "last_checked": now_iso,
                            "status": code,
                        }
                        if field_changes and any(c.startswith(model_data["brand"]) for c in field_changes):
                            model_data["data_as_of"] = today_str
                            mf.write_text(json.dumps(model_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                            total_field_updates += len(field_changes)
                else:
                    status_str = f"HTTP {code}"
            except Exception as exc:
                status_str = f"ERR: {type(exc).__name__}"

            change_summary = "; ".join(field_changes[:3]) if field_changes else "无"
            report_lines.append(
                f"| {model_data['brand_name']} | {model_data['model']} | {primary_url} | {status_str} | {changed_str} | {change_summary} |"
            )

    if not args.dry_run:
        save_state(state)

    report_lines.extend(
        [
            "",
            f"**汇总**：共巡检 {total_checked} 款车型官方源，成功访问 {total_ok} 个，检测到官网页面变动 {total_changed_pages} 处，自动无损补全字段 {total_field_updates} 处。",
        ]
    )
    report_md = "\n".join(report_lines) + "\n"

    if args.write_report:
        args.write_report.write_text(report_md, encoding="utf-8")

    print(f"Sync complete: checked={total_checked}, ok={total_ok}, changed_pages={total_changed_pages}, updates={total_field_updates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
