#!/usr/bin/env python3
"""Sync MIIT (工信部装备工业发展中心) NEV announcements and tax-exemption catalogs.

Sources:
  1. https://www.miit-eidc.org.cn/col/col1691/index.html
     Official announcement index for:
       - 《道路机动车辆生产企业及产品公告》
       - 《享受车船税减免优惠的节约能源 使用新能源汽车车型目录》
       - 《减免车辆购置税的新能源汽车车型目录》
  2. https://yhgscx.miit.gov.cn/
     MIIT vehicle energy consumption query portal (probed; integrated if available,
     gracefully degraded without error if unavailable).

Outputs:
  - data/miit_announcements.json      Latest N batches metadata + attachment links + probe status
  - data/miit_catalog_latest.json     Structured NEV passenger cars parsed from tax-exemption catalog
  - data/miit_untracked_models.json   Candidate new passenger NEV models not yet in catalog.json

Optional:
  --apply       Backfill missing `miit_filing` fields and append official `miit` references
                into matching `data/<brand>/*.json` files.
  --limit N     Number of latest batches to fetch (default: 6).
"""

from __future__ import annotations

import argparse
import datetime as dt
import html as html_lib
import json
import re
import shutil
import ssl
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CATALOG_FILE = REPO_ROOT / "catalog.json"

OUT_ANNOUNCEMENTS = DATA_DIR / "miit_announcements.json"
OUT_CATALOG_LATEST = DATA_DIR / "miit_catalog_latest.json"
OUT_UNTRACKED = DATA_DIR / "miit_untracked_models.json"

MIIT_EIDC_INDEX_URL = "https://www.miit-eidc.org.cn/col/col1691/index.html"
MIIT_EIDC_BASE = "https://www.miit-eidc.org.cn"
YHGSCX_BASE_URL = "https://yhgscx.miit.gov.cn/"

USER_AGENT = (
    "Mozilla/5.0 (compatible; Google-Agent; "
    "+https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent)"
)

# Regex for standard Chinese MIIT vehicle product model codes (e.g. BYD7000CEBEV2, BJ6500A602SBEV)
MODEL_CODE_RE = re.compile(r"^[A-Z]{2,5}[0-9]{4}[A-Z0-9-]{2,20}$")

# Manufacturer legal entity keyword -> candidate brand slugs in this repository
MANUFACTURER_BRAND_MAP: list[tuple[str, list[str]]] = [
    ("比亚迪", ["byd", "denza", "fangchengbao", "yangwang"]),
    ("腾势", ["denza"]),
    ("理想", ["lixiang"]),
    ("小鹏", ["xiaopeng"]),
    ("阿维塔", ["avatr"]),
    ("蔚来", ["nio", "onvo", "firefly"]),
    ("零跑", ["leapmotor"]),
    ("智己", ["immotors"]),
    ("赛力斯", ["hima"]),
    ("奇瑞", ["exeed-sterra", "icar", "hima"]),
    ("江淮", ["hima"]),
    ("北汽蓝谷", ["arcfox", "hima"]),
    ("北京新能源汽车", ["arcfox", "hima"]),
    ("小米", ["xiaomi"]),
    ("极氪", ["zeekr"]),
    ("领克", ["lynkco"]),
    ("吉利", ["geely-galaxy", "zeekr", "lynkco", "smart"]),
    ("岚图", ["voyah"]),
    ("东风", ["voyah"]),
    ("深蓝", ["deepal"]),
    ("长安", ["changan-qiyuan", "deepal", "avatr"]),
    ("广汽埃安", ["aion", "hyptec"]),
    ("广汽乘用车", ["aion", "hyptec"]),
    ("长城", ["wey", "tank"]),
    ("特斯拉", ["tesla"]),
    ("华晨宝马", ["bmw"]),
    ("北京奔驰", ["mercedes"]),
    ("一汽-大众", ["audi", "volkswagen"]),
    ("上汽大众", ["audi", "volkswagen"]),
    ("大众汽车（安徽）", ["volkswagen"]),
    ("沃尔沃", ["volvo"]),
    ("广汽丰田", ["toyota"]),
    ("一汽丰田", ["toyota"]),
    ("广汽本田", ["honda"]),
    ("东风本田", ["honda"]),
    ("东风汽车有限公司", ["nissan"]),
    ("上汽通用", ["gm"]),
    ("智马达", ["smart"]),
    ("长安马自达", ["joint-other"]),
    ("长安福特", ["joint-other"]),
]


def today_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def make_ssl_contexts() -> tuple[ssl.SSLContext, ssl.SSLContext]:
    verified = ssl.create_default_context()
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    return verified, unverified


SSL_VERIFIED, SSL_UNVERIFIED = make_ssl_contexts()


def http_request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 25,
    retries: int = 3,
    backoff: float = 1.5,
) -> tuple[int, dict[str, str], bytes]:
    """Perform an HTTP request with required User-Agent, retry/backoff, and SSL fallback."""
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        req_headers.update(headers)

    last_err: Exception | None = None
    use_unverified = False

    for attempt in range(1, max(1, retries) + 1):
        ctx = SSL_UNVERIFIED if use_unverified else SSL_VERIFIED
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                return resp.status, resp_headers, resp.read()
        except urllib.error.HTTPError as exc:
            # 4xx errors (except 429) won't recover on retry
            if exc.code < 500 and exc.code != 429:
                raise
            last_err = exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLError) and not use_unverified:
                use_unverified = True
                # Immediately retry once with unverified context without burning backoff
                try:
                    with urllib.request.urlopen(req, timeout=timeout, context=SSL_UNVERIFIED) as resp:
                        resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                        return resp.status, resp_headers, resp.read()
                except Exception as exc2:
                    last_err = exc2
            else:
                last_err = exc
        except (ssl.SSLError, TimeoutError, OSError) as exc:
            if isinstance(exc, ssl.SSLError) and not use_unverified:
                use_unverified = True
            last_err = exc

        if attempt < retries:
            time.sleep(backoff * attempt)

    assert last_err is not None
    raise last_err


def decode_html(raw: bytes, headers: dict[str, str]) -> str:
    ct = headers.get("content-type", "")
    m = re.search(r"charset=([\w-]+)", ct, re.I)
    encodings = [m.group(1)] if m else []
    encodings.extend(["utf-8", "gb18030", "gbk"])
    for enc in encodings:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 1. MIIT EIDC Announcement Index & Detail Scraping
# ---------------------------------------------------------------------------


def extract_records_from_xml_datastore(page_html: str) -> list[dict[str, Any]]:
    """Extract announcement items from Hanweb CMS <record><![CDATA[...]]></record> blocks."""
    records = re.findall(r"<record><!\[CDATA\[(.*?)\]\]></record>", page_html, re.S | re.I)
    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for rec in records:
        m_href = re.search(r"""href=['"]([^'"]+)['"]""", rec, re.I)
        if not m_href:
            continue
        href = urllib.parse.urljoin(MIIT_EIDC_BASE, html_lib.unescape(m_href.group(1).strip()))
        if href in seen_urls:
            continue

        m_title = re.search(r"""title=['"]([^'"]+)['"]""", rec, re.I)
        if m_title:
            title = html_lib.unescape(m_title.group(1)).strip()
        else:
            m_text = re.search(r"<a[^>]*>(.*?)</a>", rec, re.S | re.I)
            title = re.sub(r"<[^>]+>", "", html_lib.unescape(m_text.group(1))).strip() if m_text else ""

        m_date = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", rec)
        if not m_date:
            m_date = re.search(r"(\d{4}-\d{2}-\d{2})", rec)
        pub_date = m_date.group(1) if m_date else None

        seen_urls.add(href)
        items.append(parse_announcement_title_meta(title, href, pub_date))

    return items


def parse_announcement_title_meta(title: str, url: str, publish_date: str | None) -> dict[str, Any]:
    """Parse batch numbers (道路机动车辆公告批次 / 车船税目录批次 / 免购置税目录批次) from title."""
    clean_title = re.sub(r"\s+", " ", title).strip()

    batch_num: int | None = None
    batch_label: str | None = None
    m_batch = re.search(r"道路机动车辆生产企业及产品[^（(]*[（(]第(\d+)批[）)]", clean_title)
    if not m_batch:
        m_batch = re.search(r"第(\d+)批", clean_title)
    if m_batch:
        batch_num = int(m_batch.group(1))
        batch_label = f"第{batch_num}批"

    m_tax = re.search(r"减免车辆购置税的新能源汽车车型目录[^（(]*[（(](第[一二三四五六七八九十百千万\d]+批)[）)]", clean_title)
    tax_batch = m_tax.group(1) if m_tax else None

    m_vvt = re.search(r"享受车船税减免优惠[^（(]*[（(](第[一二三四五六七八九十百千万\d]+批)[）)]", clean_title)
    vvt_batch = m_vvt.group(1) if m_vvt else None

    return {
        "batch_number": batch_num,
        "batch_label": batch_label,
        "publish_date": publish_date,
        "title": clean_title,
        "url": url,
        "tax_exemption_batch": tax_batch,
        "vehicle_vessel_tax_batch": vvt_batch,
        "attachments": [],
    }


def fetch_announcement_index(limit: int, timeout: int, retries: int) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch latest `limit` announcements from miit-eidc.org.cn col1691."""
    try:
        _, headers, raw = http_request(MIIT_EIDC_INDEX_URL, timeout=timeout, retries=retries)
    except Exception as exc:
        return [], f"Failed to fetch {MIIT_EIDC_INDEX_URL}: {type(exc).__name__}: {exc}"

    page_html = decode_html(raw, headers)
    items = extract_records_from_xml_datastore(page_html)

    # Support pagination via Hanweb dataproxy.jsp if user requests more than page 1 (15 records)
    if len(items) < limit:
        m_proxy = re.search(r"(/module/web/jpage/dataproxy\.jsp\?[^'\"<>\]]+)", page_html)
        if m_proxy:
            base_proxy = urllib.parse.urljoin(MIIT_EIDC_BASE, html_lib.unescape(m_proxy.group(1)))
            start_rec = len(items) + 1
            while len(items) < limit:
                end_rec = start_rec + 14
                sep = "&" if "?" in base_proxy else "?"
                page_url = f"{base_proxy}{sep}startrecord={start_rec}&endrecord={end_rec}&perpage=15"
                try:
                    _, p_headers, p_raw = http_request(page_url, timeout=timeout, retries=max(1, retries - 1))
                    more = extract_records_from_xml_datastore(decode_html(p_raw, p_headers))
                except Exception:
                    break
                if not more:
                    break
                existing = {x["url"] for x in items}
                added = [x for x in more if x["url"] not in existing]
                if not added:
                    break
                items.extend(added)
                start_rec = end_rec + 1

    return items[:limit], None


def classify_attachment(name: str, url: str) -> str:
    if "减免车辆购置税" in name:
        return "tax_exemption_catalog"
    if "车船税" in name:
        return "vehicle_vessel_tax_catalog"
    if "道路机动车辆" in name:
        return "vehicle_announcement"
    if url.lower().endswith((".doc", ".docx", ".xls", ".xlsx", ".pdf", ".zip")):
        return "attachment"
    return "other"


def fetch_announcement_attachments(item: dict[str, Any], timeout: int, retries: int) -> None:
    """Fetch an announcement article page and extract its official attachment links."""
    url = item["url"]
    try:
        _, headers, raw = http_request(url, timeout=timeout, retries=retries)
    except Exception as exc:
        item["fetch_error"] = f"{type(exc).__name__}: {exc}"
        return

    art_html = decode_html(raw, headers)
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()

    for href, link_body in re.findall(r"""<a[^>]+href=['"]([^'"]+)['"][^>]*>(.*?)</a>""", art_html, re.S | re.I):
        abs_url = urllib.parse.urljoin(url, html_lib.unescape(href.strip()))
        text = re.sub(r"<[^>]+>", "", html_lib.unescape(link_body))
        text = re.sub(r"\s+", " ", text).strip()
        is_doc_file = bool(re.search(r"\.(?:doc|docx|xls|xlsx|pdf|zip)(?:\?|$)", abs_url, re.I))
        is_attach_path = "/attach/" in abs_url.lower() or "cms_files" in abs_url.lower()
        if not (is_doc_file or is_attach_path):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        attachments.append(
            {
                "name": text or Path(urllib.parse.urlparse(abs_url).path).name,
                "category": classify_attachment(text, abs_url),
                "url": abs_url,
            }
        )

    item["attachments"] = attachments
    # Backfill tax_exemption_batch from attachment name if title didn't include it
    if not item.get("tax_exemption_batch"):
        for att in attachments:
            if att["category"] == "tax_exemption_catalog":
                m = re.search(r"[（(](第[一二三四五六七八九十百千万\d]+批)[）)]", att["name"])
                if m:
                    item["tax_exemption_batch"] = m.group(1)
                    break


# ---------------------------------------------------------------------------
# 2. yhgscx.miit.gov.cn Probe (Graceful Degradation)
# ---------------------------------------------------------------------------


def probe_yhgscx(timeout: int = 10) -> dict[str, Any]:
    """Probe https://yhgscx.miit.gov.cn/ and its known API endpoints; never raises."""
    result: dict[str, Any] = {
        "portal_url": YHGSCX_BASE_URL,
        "probed_at": now_iso(),
        "portal_reachable": False,
        "api_available": False,
        "api_endpoint": None,
        "sample_count": 0,
        "status": "unavailable",
        "note": "",
    }

    try:
        status, _, _ = http_request(YHGSCX_BASE_URL, timeout=timeout, retries=1)
        result["portal_reachable"] = status == 200
    except Exception as exc:
        result["note"] = f"Portal probe timed out or failed ({type(exc).__name__}: {exc}); gracefully degraded."
        return result

    candidate_endpoints = [
        "https://yhgscx.miit.gov.cn/fuel-consumption-center/fcSearchCtr/queryNewList",
        "https://yhgscx.miit.gov.cn/fuel-consumption-center/fcSearchCtr/queryList",
    ]
    payload = json.dumps({"pageNum": 1, "pageSize": 5}).encode("utf-8")
    errors: list[str] = []

    for ep in candidate_endpoints:
        try:
            st, _, raw = http_request(
                ep,
                method="POST",
                data=payload,
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "Referer": "https://yhgscx.miit.gov.cn/fuel-consumption-web/mainPage",
                },
                timeout=timeout,
                retries=1,
            )
            if st == 200:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
                rows = (
                    parsed.get("data", {}).get("list")
                    or parsed.get("rows")
                    or parsed.get("list")
                    or []
                )
                if isinstance(rows, list):
                    result["api_available"] = True
                    result["api_endpoint"] = ep
                    result["sample_count"] = len(rows)
                    result["status"] = "available"
                    result["note"] = "Query API returned structured JSON."
                    return result
        except Exception as exc:
            errors.append(f"{ep} -> {type(exc).__name__}: {exc}")

    result["status"] = "portal_only_api_unavailable"
    result["note"] = (
        "SPA portal reachable, but direct JSON query endpoints are not publicly accessible "
        f"({'; '.join(errors)}); gracefully degraded to miit-eidc.org.cn official attachments."
    )
    return result


# ---------------------------------------------------------------------------
# 3. Pure-Python OLE2 (.doc), OOXML (.docx), and HTML Table Parsers
# ---------------------------------------------------------------------------


def extract_text_from_ole2_doc(doc_bytes: bytes) -> str:
    """Pure-Python Word 97-2003 (.doc) OLE2 text extractor (reads FIB + Clx piece table)."""
    if len(doc_bytes) < 512 or doc_bytes[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("Not an OLE2 Compound Binary File")

    sector_shift = struct.unpack_from("<H", doc_bytes, 30)[0]
    sector_size = 1 << sector_shift
    dir_first_sector = struct.unpack_from("<I", doc_bytes, 48)[0]
    difat_first = struct.unpack_from("<I", doc_bytes, 68)[0]

    def sec_off(sec: int) -> int:
        return (sec + 1) * sector_size

    fat_sectors = list(struct.unpack_from("<109I", doc_bytes, 76))
    difat_sec = difat_first
    seen_difat: set[int] = set()
    while difat_sec < 0xFFFFFFFA and difat_sec not in seen_difat:
        seen_difat.add(difat_sec)
        off = sec_off(difat_sec)
        if off + sector_size > len(doc_bytes):
            break
        vals = struct.unpack_from(f"<{sector_size // 4}I", doc_bytes, off)
        fat_sectors.extend(vals[:-1])
        difat_sec = vals[-1]

    fat: list[int] = []
    for s in fat_sectors:
        if s >= 0xFFFFFFFA:
            continue
        off = sec_off(s)
        if off + sector_size <= len(doc_bytes):
            fat.extend(struct.unpack_from(f"<{sector_size // 4}I", doc_bytes, off))

    def read_chain(start_sec: int, size: int | None = None) -> bytes:
        out = bytearray()
        sec = start_sec
        seen: set[int] = set()
        while sec < 0xFFFFFFFA and sec not in seen and sec < len(fat):
            seen.add(sec)
            off = sec_off(sec)
            out.extend(doc_bytes[off : off + sector_size])
            sec = fat[sec]
        return bytes(out[:size] if size is not None else out)

    dir_bytes = read_chain(dir_first_sector)
    streams: dict[str, tuple[int, int]] = {}
    for i in range(0, len(dir_bytes), 128):
        entry = dir_bytes[i : i + 128]
        if len(entry) < 128:
            break
        name_len = struct.unpack_from("<H", entry, 64)[0]
        if name_len < 2 or name_len > 64:
            continue
        name = entry[: name_len - 2].decode("utf-16le", errors="ignore")
        start_sec = struct.unpack_from("<I", entry, 116)[0]
        size = struct.unpack_from("<I", entry, 120)[0]
        streams[name] = (start_sec, size)

    if "WordDocument" not in streams:
        raise ValueError("Missing WordDocument stream in OLE2 file")

    wd = read_chain(*streams["WordDocument"])
    flags = struct.unpack_from("<H", wd, 10)[0]
    table_stream_name = "1Table" if (flags & 0x0200) else "0Table"
    if table_stream_name not in streams:
        raise ValueError(f"Missing {table_stream_name} stream in OLE2 file")
    tb = read_chain(*streams[table_stream_name])

    fc_clx = struct.unpack_from("<I", wd, 0x01A2)[0]
    lcb_clx = struct.unpack_from("<I", wd, 0x01A6)[0]
    clx = tb[fc_clx : fc_clx + lcb_clx]

    pos = 0
    while pos < len(clx) and clx[pos] == 1:
        cb = struct.unpack_from("<H", clx, pos + 1)[0]
        pos += 3 + cb
    if pos >= len(clx) or clx[pos] != 2:
        raise ValueError("Could not locate Pcdt in Word Clx table")

    lcb_pcdt = struct.unpack_from("<I", clx, pos + 1)[0]
    pcdt = clx[pos + 5 : pos + 5 + lcb_pcdt]
    n_pieces = (lcb_pcdt - 4) // 12
    cps = struct.unpack_from(f"<{n_pieces + 1}I", pcdt, 0)

    chunks: list[str] = []
    for i in range(n_pieces):
        pcd_off = (n_pieces + 1) * 4 + i * 8
        fc_val = struct.unpack_from("<I", pcdt, pcd_off + 2)[0]
        is_ansi = bool(fc_val & 0x40000000)
        fc = (fc_val & 0x3FFFFFFF) >> (1 if is_ansi else 0)
        char_count = cps[i + 1] - cps[i]
        if is_ansi:
            chunks.append(wd[fc : fc + char_count].decode("cp1252", errors="replace"))
        else:
            chunks.append(wd[fc : fc + char_count * 2].decode("utf-16le", errors="replace"))

    return "".join(chunks)


def clean_cell_text(val: str) -> str:
    val = val.replace("\r", " ").replace("\n", " ").replace("\x0b", " ").replace("\xa0", " ")
    val = re.sub(r"\s+", " ", val).strip()
    # Normalize spaces around Chinese/alphanumeric tokens (e.g. "比亚迪汉 , 比亚迪汉 08" -> "比亚迪汉, 比亚迪汉08")
    val = re.sub(r"\s*([,，/（(）)])\s*", r"\1", val)
    return val


def normalize_model_display(name: str) -> str:
    """Clean spacing in common names like '方程豹钛 9' -> '方程豹钛9', '比亚迪汉 08' -> '比亚迪汉08'."""
    s = clean_cell_text(name)
    # Remove stray space between CJK char and ASCII digit/letter
    s = re.sub(r"([\u4e00-\u9fff])\s+([A-Za-z0-9])", r"\1\2", s)
    s = re.sub(r"([A-Za-z0-9])\s+([\u4e00-\u9fff])", r"\1\2", s)
    return s


def parse_first_number(raw: str | None) -> float | None:
    if not raw:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", str(raw))
    if not m:
        return None
    val = float(m.group(1))
    return int(val) if val.is_integer() else val


def infer_powertrain(section_mode: str, product_name: str) -> str:
    if "增程" in product_name:
        return "REEV"
    if "插电" in product_name or section_mode == "PHEV":
        return "PHEV"
    return "BEV"


def parse_tax_catalog_from_ole2_text(
    full_text: str,
    announcement: dict[str, Any],
    attachment_url: str,
) -> list[dict[str, Any]]:
    """Parse passenger BEV & PHEV/REEV tables from Word OLE2 \\x07-delimited text."""
    # Split into row segments terminated by \x07\x07 (Word table row end marker)
    raw_rows = full_text.split("\x07\x07")
    models: list[dict[str, Any]] = []
    mode: str | None = None  # "BEV_PASSENGER" | "PHEV_PASSENGER" | None
    current_mfr = ""

    for raw_row in raw_rows:
        cells = [clean_cell_text(c) for c in raw_row.split("\x07")]
        # Drop pure empty trailing/leading spacer rows
        non_empty = [c for c in cells if c]
        if not non_empty:
            continue

        joined = " ".join(non_empty)

        # Detect table headers
        if "汽车生产企业名称" in joined and "车辆型号" in joined:
            if "通用名称" in joined and "燃料消耗量" in joined:
                mode = "PHEV_PASSENGER"
                current_mfr = ""
            elif "通用名称" in joined:
                mode = "BEV_PASSENGER"
                current_mfr = ""
            else:
                # Commercial vehicles (buses, trucks, special vehicles, FCEV, company renames)
                mode = None
                current_mfr = ""
            continue

        if mode is None:
            continue

        # Locate the product_model_code cell (robust against rowspan-omitted manufacturer/seq cells)
        code_idx = -1
        for idx, c in enumerate(cells[:4]):
            token = c.replace(" ", "")
            if MODEL_CODE_RE.match(token):
                code_idx = idx
                break

        if code_idx == -1:
            continue

        # Manufacturer is immediately before code_idx if present and not purely numeric
        if code_idx >= 1:
            prev = cells[code_idx - 1]
            if prev and not prev.isdigit() and len(prev) >= 3:
                current_mfr = prev

        product_code = cells[code_idx].replace(" ", "")
        tail = cells[code_idx + 1 :]

        if mode == "BEV_PASSENGER":
            # Expected after code: common_name, product_name, ev_range, curb_weight, batt_weight, batt_kwh, [notes]
            if len(tail) < 6:
                continue
            common_raw, product_name, ev_range, curb_weight, batt_weight, batt_kwh = tail[:6]
            notes = tail[6] if len(tail) > 6 else ""
            fuel_cons = None
            displacement = None
        else:
            # PHEV_PASSENGER: common_name, product_name, ev_range, fuel_cons, displacement, curb_weight, batt_weight, batt_kwh, [notes]
            if len(tail) < 8:
                continue
            (
                common_raw,
                product_name,
                ev_range,
                fuel_cons,
                displacement,
                curb_weight,
                batt_weight,
                batt_kwh,
            ) = tail[:8]
            notes = tail[8] if len(tail) > 8 else ""

        # Sanity check: passenger cars only
        if not common_raw or not product_name:
            continue

        common_norm = normalize_model_display(common_raw)
        model_names = [n.strip() for n in re.split(r"[,，/、]", common_norm) if n.strip()]
        pt = infer_powertrain("PHEV" if mode == "PHEV_PASSENGER" else "BEV", product_name)

        models.append(
            {
                "batch_number": announcement.get("batch_number"),
                "batch_label": announcement.get("batch_label"),
                "tax_exemption_batch": announcement.get("tax_exemption_batch"),
                "publish_date": announcement.get("publish_date"),
                "powertrain_type": pt,
                "manufacturer": current_mfr,
                "product_model_code": product_code,
                "common_name": common_norm,
                "model_names": model_names,
                "product_name": product_name,
                "ev_range_km": ev_range,
                "ev_range_km_num": parse_first_number(ev_range),
                "fuel_consumption_l_100km": fuel_cons,
                "engine_displacement_ml": displacement,
                "curb_weight_kg": curb_weight,
                "curb_weight_kg_num": parse_first_number(curb_weight),
                "battery_weight_kg": batt_weight,
                "battery_capacity_kwh": batt_kwh,
                "battery_capacity_kwh_num": parse_first_number(batt_kwh),
                "notes": notes,
                "announcement_url": announcement.get("url"),
                "attachment_url": attachment_url,
            }
        )

    return models


class SimpleHTMLTableParser(HTMLParser):
    """Stdlib HTML parser extracting <table> grids with rowspan/colspan expansion."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cur_rows: list[list[tuple[str, int, int]]] = []
        self._cur_row: list[tuple[str, int, int]] = []
        self._cell_buf: list[str] = []
        self._cell_rs = 1
        self._cell_cs = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "table":
            self._in_table = True
            self._cur_rows = []
        elif t == "tr" and self._in_table:
            self._in_row = True
            self._cur_row = []
        elif t in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell_buf = []
            attr_map = dict(attrs)
            try:
                self._cell_rs = max(1, int(attr_map.get("rowspan") or 1))
            except ValueError:
                self._cell_rs = 1
            try:
                self._cell_cs = max(1, int(attr_map.get("colspan") or 1))
            except ValueError:
                self._cell_cs = 1

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("td", "th") and self._in_cell:
            self._in_cell = False
            self._cur_row.append((clean_cell_text(" ".join(self._cell_buf)), self._cell_rs, self._cell_cs))
        elif t == "tr" and self._in_row:
            self._in_row = False
            if self._cur_row:
                self._cur_rows.append(self._cur_row)
        elif t == "table" and self._in_table:
            self._in_table = False
            self.tables.append(self._expand_grid(self._cur_rows))

    @staticmethod
    def _expand_grid(raw_rows: list[list[tuple[str, int, int]]]) -> list[list[str]]:
        grid: list[list[str | None]] = []
        for r_idx, row in enumerate(raw_rows):
            while len(grid) <= r_idx:
                grid.append([])
            c_idx = 0
            for text, rs, cs in row:
                while c_idx < len(grid[r_idx]) and grid[r_idx][c_idx] is not None:
                    c_idx += 1
                for dr in range(rs):
                    while len(grid) <= r_idx + dr:
                        grid.append([])
                    while len(grid[r_idx + dr]) < c_idx + cs:
                        grid[r_idx + dr].append(None)
                    for dc in range(cs):
                        grid[r_idx + dr][c_idx + dc] = text
                c_idx += cs
        return [[c or "" for c in r] for r in grid]


def parse_tax_catalog_from_tables(
    tables: list[list[list[str]]],
    announcement: dict[str, Any],
    attachment_url: str,
) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for grid in tables:
        if len(grid) < 2:
            continue
        hdr = " ".join(grid[0])
        if "通用名称" not in hdr or "车辆型号" not in hdr:
            continue
        is_phev = "燃料消耗量" in hdr
        last_mfr = ""
        for row in grid[1:]:
            if len(row) < 9:
                continue
            mfr = row[1].strip() or last_mfr
            if mfr:
                last_mfr = mfr
            code = row[2].replace(" ", "")
            if not MODEL_CODE_RE.match(code):
                continue
            common_norm = normalize_model_display(row[3])
            product_name = row[4].strip()
            ev_range = row[5].strip()
            if is_phev and len(row) >= 11:
                fuel_cons = row[6].strip()
                displacement = row[7].strip()
                curb_weight = row[8].strip()
                batt_weight = row[9].strip()
                batt_kwh = row[10].strip()
                notes = row[11].strip() if len(row) > 11 else ""
            else:
                fuel_cons = None
                displacement = None
                curb_weight = row[6].strip()
                batt_weight = row[7].strip()
                batt_kwh = row[8].strip()
                notes = row[9].strip() if len(row) > 9 else ""

            model_names = [n.strip() for n in re.split(r"[,，/、]", common_norm) if n.strip()]
            pt = infer_powertrain("PHEV" if is_phev else "BEV", product_name)
            models.append(
                {
                    "batch_number": announcement.get("batch_number"),
                    "batch_label": announcement.get("batch_label"),
                    "tax_exemption_batch": announcement.get("tax_exemption_batch"),
                    "publish_date": announcement.get("publish_date"),
                    "powertrain_type": pt,
                    "manufacturer": mfr,
                    "product_model_code": code,
                    "common_name": common_norm,
                    "model_names": model_names,
                    "product_name": product_name,
                    "ev_range_km": ev_range,
                    "ev_range_km_num": parse_first_number(ev_range),
                    "fuel_consumption_l_100km": fuel_cons,
                    "engine_displacement_ml": displacement,
                    "curb_weight_kg": curb_weight,
                    "curb_weight_kg_num": parse_first_number(curb_weight),
                    "battery_weight_kg": batt_weight,
                    "battery_capacity_kwh": batt_kwh,
                    "battery_capacity_kwh_num": parse_first_number(batt_kwh),
                    "notes": notes,
                    "announcement_url": announcement.get("url"),
                    "attachment_url": attachment_url,
                }
            )
    return models


def parse_docx_tables(docx_bytes: bytes) -> list[list[list[str]]]:
    """Stdlib .docx table extractor using zipfile + ElementTree."""
    tables: list[list[list[str]]] = []
    with tempfile.NamedTemporaryFile(suffix=".docx") as tmp:
        tmp.write(docx_bytes)
        tmp.flush()
        with zipfile.ZipFile(tmp.name) as zf:
            xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for tbl in root.findall(".//w:tbl", ns):
        grid: list[list[str]] = []
        for tr in tbl.findall("./w:tr", ns):
            row = []
            for tc in tr.findall("./w:tc", ns):
                txt = "".join(t.text or "" for t in tc.findall(".//w:t", ns))
                row.append(clean_cell_text(txt))
            if row:
                grid.append(row)
        if grid:
            tables.append(grid)
    return tables


def parse_tax_exemption_attachment(
    announcement: dict[str, Any],
    attachment_url: str,
    timeout: int,
    retries: int,
) -> tuple[list[dict[str, Any]], str, str | None]:
    """Download and parse a tax-exemption catalog attachment (.doc / .docx / .html)."""
    try:
        _, headers, raw = http_request(
            attachment_url,
            headers={"Referer": announcement.get("url") or MIIT_EIDC_INDEX_URL},
            timeout=timeout,
            retries=retries,
        )
    except Exception as exc:
        return [], "download_failed", f"{type(exc).__name__}: {exc}"

    # 1. OLE2 .doc
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        try:
            text = extract_text_from_ole2_doc(raw)
            parsed = parse_tax_catalog_from_ole2_text(text, announcement, attachment_url)
            if parsed:
                return parsed, "pure_python_ole2", None
        except Exception:
            pass

        # Fallback to LibreOffice if installed
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice:
            try:
                with tempfile.TemporaryDirectory() as td:
                    doc_path = Path(td) / "catalog.doc"
                    doc_path.write_bytes(raw)
                    subprocess.run(
                        [soffice, "--headless", "--convert-to", "html", "--outdir", td, str(doc_path)],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=60,
                    )
                    html_path = Path(td) / "catalog.html"
                    if html_path.exists():
                        parser = SimpleHTMLTableParser()
                        parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
                        parsed = parse_tax_catalog_from_tables(parser.tables, announcement, attachment_url)
                        return parsed, "libreoffice_html", None
            except Exception as exc:
                return [], "ole2_fallback_failed", f"{type(exc).__name__}: {exc}"
        return [], "ole2_empty", "Parsed 0 passenger NEV rows from OLE2 .doc"

    # 2. OOXML .docx (ZIP)
    if raw[:2] == b"PK":
        try:
            tables = parse_docx_tables(raw)
            parsed = parse_tax_catalog_from_tables(tables, announcement, attachment_url)
            return parsed, "pure_python_docx", None
        except Exception as exc:
            return [], "docx_failed", f"{type(exc).__name__}: {exc}"

    # 3. HTML-disguised .doc or plain HTML
    html_text = decode_html(raw, headers)
    if "<table" in html_text.lower():
        parser = SimpleHTMLTableParser()
        parser.feed(html_text)
        parsed = parse_tax_catalog_from_tables(parser.tables, announcement, attachment_url)
        return parsed, "html_table", None

    return [], "unsupported_format", f"Unrecognized attachment format ({len(raw)} bytes)"


# ---------------------------------------------------------------------------
# 4. Comparison Against Repository catalog.json & Optional --apply Backfill
# ---------------------------------------------------------------------------


def normalize_key(text: str) -> str:
    """Normalize a model name for fuzzy comparison (strip spaces, year tags, punctuation, lowercase)."""
    s = text.lower()
    s = re.sub(r"[（(][^）)]*(?:款|年|版|焕新|全新)[^）)]*[）)]", "", s)
    s = re.sub(r"20\d{2}款?", "", s)
    s = re.sub(r"[\s\-_/·・,，.。()（）]+", "", s)
    return s


def guess_brand_slugs(manufacturer: str, common_name: str) -> list[str]:
    slugs: list[str] = []
    combined = f"{manufacturer} {common_name}"
    # Specific sub-brand checks first
    sub_hints = [
        ("方程豹", "fangchengbao"),
        ("腾势", "denza"),
        ("仰望", "yangwang"),
        ("极氪", "zeekr"),
        ("领克", "lynkco"),
        ("银河", "geely-galaxy"),
        ("阿维塔", "avatr"),
        ("深蓝", "deepal"),
        ("启源", "changan-qiyuan"),
        ("乐道", "onvo"),
        ("萤火虫", "firefly"),
        ("昊铂", "hyptec"),
        ("埃安", "aion"),
        ("极狐", "arcfox"),
        ("α", "arcfox"),
        ("阿尔法", "arcfox"),
        ("星纪元", "exeed-sterra"),
        ("问界", "hima"),
        ("智界", "hima"),
        ("享界", "hima"),
        ("尊界", "hima"),
        ("尚界", "hima"),
        ("岚图", "voyah"),
        ("魏牌", "wey"),
        ("坦克", "tank"),
    ]
    for kw, slug in sub_hints:
        if kw in combined and slug not in slugs:
            slugs.append(slug)

    for kw, mapped in MANUFACTURER_BRAND_MAP:
        if kw in manufacturer:
            for s in mapped:
                if s not in slugs:
                    slugs.append(s)
    return slugs


def load_repo_models() -> tuple[list[dict[str, Any]], dict[str, Path]]:
    """Load catalog.json entries and map each model file path + existing product_model_code."""
    catalog_models: list[dict[str, Any]] = []
    if CATALOG_FILE.exists():
        cat = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        catalog_models = cat.get("models", [])

    code_to_file: dict[str, Path] = {}
    for entry in catalog_models:
        rel = entry.get("file")
        if not rel:
            continue
        p = REPO_ROOT / rel
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            mf = d.get("miit_filing") or {}
            code = mf.get("product_model_code")
            if isinstance(code, str) and code.strip():
                for part in re.split(r"[/,，\s]+", code.strip()):
                    if part:
                        code_to_file[part.upper()] = p
        except Exception:
            continue

    return catalog_models, code_to_file


def match_miit_entry_to_repo(
    item: dict[str, Any],
    catalog_models: list[dict[str, Any]],
    code_to_file: dict[str, Path],
) -> dict[str, Any] | None:
    """Return matching catalog.json entry if already tracked, else None."""
    code = (item.get("product_model_code") or "").upper()
    if code and code in code_to_file:
        target_rel = str(code_to_file[code].relative_to(REPO_ROOT))
        for cm in catalog_models:
            if cm.get("file") == target_rel:
                return cm

    candidate_brands = set(guess_brand_slugs(item.get("manufacturer", ""), item.get("common_name", "")))
    miit_names = [normalize_key(n) for n in item.get("model_names", []) if n]
    if not miit_names:
        return None

    for cm in catalog_models:
        if candidate_brands and cm.get("brand") not in candidate_brands:
            continue
        repo_model = cm.get("model", "")
        repo_brand_cn = cm.get("brand_name", "")
        repo_norm = normalize_key(repo_model)
        # Strip brand prefix from both sides for cleaner comparison
        repo_stripped = normalize_key(repo_model.replace(repo_brand_cn.replace("汽车", ""), ""))
        for mn in miit_names:
            if not mn or len(mn) < 2:
                continue
            mn_stripped = mn
            for prefix in ("比亚迪", "极狐", "吉利", "长安", "奇瑞", "广汽", "长城", "一汽", "上汽", "东风"):
                if mn_stripped.startswith(prefix) and len(mn_stripped) > len(prefix) + 1:
                    mn_stripped = mn_stripped[len(prefix) :]
            if mn == repo_norm or (repo_stripped and mn_stripped == repo_stripped):
                return cm
            # Handle cases like "比亚迪汉" matching "汉L" or "汉EV" only when exact or clear suffix match
            if mn == repo_stripped and len(mn) >= 3:
                return cm

    return None


def build_untracked_candidates(
    miit_models: list[dict[str, Any]],
    catalog_models: list[dict[str, Any]],
    code_to_file: dict[str, Path],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
    """Compare MIIT passenger NEV entries with catalog.json; return (untracked, matched_pairs)."""
    untracked_grouped: dict[tuple[str, str], dict[str, Any]] = {}
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for item in miit_models:
        match = match_miit_entry_to_repo(item, catalog_models, code_to_file)
        if match:
            matched_pairs.append((item, match))
            continue

        key = (item.get("manufacturer", ""), item.get("common_name", ""))
        if key not in untracked_grouped:
            untracked_grouped[key] = {
                "manufacturer": item.get("manufacturer"),
                "common_name": item.get("common_name"),
                "model_names": item.get("model_names", []),
                "suggested_brand_slugs": guess_brand_slugs(
                    item.get("manufacturer", ""), item.get("common_name", "")
                ),
                "batch_label": item.get("batch_label"),
                "tax_exemption_batch": item.get("tax_exemption_batch"),
                "publish_date": item.get("publish_date"),
                "powertrain_types": [],
                "product_model_codes": [],
                "ev_ranges_km": [],
                "battery_capacities_kwh": [],
                "curb_weights_kg": [],
                "announcement_url": item.get("announcement_url"),
                "attachment_url": item.get("attachment_url"),
                "variant_count": 0,
            }

        grp = untracked_grouped[key]
        grp["variant_count"] += 1
        for field, val in [
            ("powertrain_types", item.get("powertrain_type")),
            ("product_model_codes", item.get("product_model_code")),
            ("ev_ranges_km", item.get("ev_range_km")),
            ("battery_capacities_kwh", item.get("battery_capacity_kwh")),
            ("curb_weights_kg", item.get("curb_weight_kg")),
        ]:
            if val and val not in grp[field]:
                grp[field].append(val)

    return list(untracked_grouped.values()), matched_pairs


def apply_miit_backfill(
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Backfill missing `miit_filing` fields and append official `miit` reference to matched model files."""
    by_file: dict[Path, list[dict[str, Any]]] = {}
    for miit_item, catalog_entry in matched_pairs:
        rel = catalog_entry.get("file")
        if not rel:
            continue
        p = REPO_ROOT / rel
        if p.exists():
            by_file.setdefault(p, []).append(miit_item)

    changes: list[dict[str, Any]] = []
    retrieved_date = today_iso()

    for path, items in sorted(by_file.items()):
        data = json.loads(path.read_text(encoding="utf-8"))
        mf = data.get("miit_filing")
        if not isinstance(mf, dict):
            mf = {
                "miit_batch": None,
                "product_model_code": None,
                "curb_weight_kg": None,
                "gross_weight_kg": None,
                "approach_departure_deg": None,
                "battery_supplier": None,
            }

        updated_fields: list[str] = []
        first = items[0]

        if not mf.get("miit_batch") and first.get("batch_label"):
            mf["miit_batch"] = first["batch_label"]
            updated_fields.append("miit_filing.miit_batch")

        codes = sorted({it["product_model_code"] for it in items if it.get("product_model_code")})
        if not mf.get("product_model_code") and codes:
            mf["product_model_code"] = "/".join(codes[:4])
            updated_fields.append("miit_filing.product_model_code")

        weights = sorted(
            {
                it["curb_weight_kg_num"]
                for it in items
                if isinstance(it.get("curb_weight_kg_num"), (int, float))
            }
        )
        if not mf.get("curb_weight_kg") and weights:
            mf["curb_weight_kg"] = weights[0] if len(weights) == 1 else f"{weights[0]}-{weights[-1]}"
            updated_fields.append("miit_filing.curb_weight_kg")

        # Append official MIIT reference if not already present
        refs = data.get("references")
        if not isinstance(refs, list):
            refs = []
        existing_urls = {r.get("url") for r in refs if isinstance(r, dict)}
        ann_url = first.get("announcement_url")
        if ann_url and ann_url not in existing_urls:
            title_parts = []
            if first.get("batch_label"):
                title_parts.append(f"《道路机动车辆生产企业及产品》（{first['batch_label']}）")
            if first.get("tax_exemption_batch"):
                title_parts.append(f"《减免车辆购置税的新能源汽车车型目录》（{first['tax_exemption_batch']}）")
            ref_title = "工信部" + " / ".join(title_parts) if title_parts else "工信部新能源车型公告"
            refs.append(
                {
                    "title": ref_title,
                    "url": ann_url,
                    "type": "miit",
                    "is_third_party": False,
                    "retrieved_at": retrieved_date,
                }
            )
            updated_fields.append("references(miit)")

        if updated_fields:
            data["miit_filing"] = mf
            data["references"] = refs
            if not dry_run:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changes.append(
                {
                    "file": str(path.relative_to(REPO_ROOT)),
                    "updated_fields": updated_fields,
                    "matched_codes": codes,
                }
            )

    return changes


def write_markdown_report(
    report_path: Path,
    announcements: list[dict[str, Any]],
    yhgscx_probe: dict[str, Any],
    catalog_payload: dict[str, Any],
    untracked_payload: dict[str, Any],
    applied_changes: list[dict[str, Any]],
) -> None:
    lines = [
        f"## 工信部新能源车型公告同步报告 ({today_iso()})",
        "",
        f"- **公告源**：[{MIIT_EIDC_INDEX_URL}]({MIIT_EIDC_INDEX_URL})",
        f"- **已同步批次数**：{len(announcements)} 批",
        f"- **能耗查询接口 (`yhgscx.miit.gov.cn`)**：`{yhgscx_probe.get('status')}`",
        f"- **最新免购置税目录乘用车记录**：{catalog_payload.get('total_passenger_entries', 0)} 条"
        f"（BEV {catalog_payload.get('bev_count', 0)} / PHEV {catalog_payload.get('phev_count', 0)} / REEV {catalog_payload.get('reev_count', 0)}）",
        f"- **尚未收录候选车型**：{untracked_payload.get('total_untracked_models', 0)} 款",
    ]
    if applied_changes:
        lines.append(f"- **已回填已有车型文件**：{len(applied_changes)} 个")

    if announcements:
        lines.extend(
            [
                "",
                "### 最新公告批次",
                "",
                "| 批次 | 发布日期 | 免购置税目录 | 附件数 | 链接 |",
                "| :--- | :--- | :--- | ---: | :--- |",
            ]
        )
        for ann in announcements:
            lines.append(
                f"| {ann.get('batch_label') or '-'} | {ann.get('publish_date') or '-'} | "
                f"{ann.get('tax_exemption_batch') or '-'} | {len(ann.get('attachments') or [])} | "
                f"[查看]({ann.get('url')}) |"
            )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync MIIT official NEV announcements and tax-exemption catalogs.")
    parser.add_argument("--limit", type=int, default=6, help="Number of latest announcement batches to fetch (default: 6).")
    parser.add_argument(
        "--catalog-batches",
        type=int,
        default=1,
        help="Number of latest batches to parse tax-exemption catalog attachments from (default: 1).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Backfill missing miit_filing fields and official miit references in data/<brand>/*.json.",
    )
    parser.add_argument("--dry-run", action="store_true", help="With --apply, show planned edits without writing brand JSON files.")
    parser.add_argument("--timeout", type=int, default=25, help="HTTP request timeout in seconds (default: 25).")
    parser.add_argument("--retries", type=int, default=3, help="Max HTTP retries per request (default: 3).")
    parser.add_argument("--skip-yhgscx", action="store_true", help="Skip probing yhgscx.miit.gov.cn.")
    parser.add_argument("--write-report", type=str, default="", help="Optional Markdown summary report path.")
    args = parser.parse_args()

    limit = max(1, args.limit)
    catalog_batches = max(1, min(args.catalog_batches, limit))

    print(f"[sync_miit] Fetching latest {limit} batches from {MIIT_EIDC_INDEX_URL} ...")
    announcements, index_err = fetch_announcement_index(limit=limit, timeout=args.timeout, retries=args.retries)
    if index_err:
        print(f"[sync_miit] WARNING: {index_err}", file=sys.stderr)

    for ann in announcements:
        fetch_announcement_attachments(ann, timeout=args.timeout, retries=args.retries)
        print(
            f"  - {ann.get('batch_label') or '?'} ({ann.get('publish_date')}) "
            f"| 购置税目录: {ann.get('tax_exemption_batch') or '-'} "
            f"| 附件: {len(ann.get('attachments') or [])}"
        )

    if args.skip_yhgscx:
        yhgscx_probe = {
            "portal_url": YHGSCX_BASE_URL,
            "probed_at": now_iso(),
            "portal_reachable": False,
            "api_available": False,
            "status": "skipped",
            "note": "Skipped via --skip-yhgscx",
        }
    else:
        print(f"[sync_miit] Probing {YHGSCX_BASE_URL} ...")
        yhgscx_probe = probe_yhgscx(timeout=min(args.timeout, 12))
        print(f"  - yhgscx status: {yhgscx_probe['status']}")

    # Save data/miit_announcements.json
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    announcements_payload = {
        "synced_at": now_iso(),
        "data_as_of": today_iso(),
        "source_url": MIIT_EIDC_INDEX_URL,
        "limit": limit,
        "total_batches": len(announcements),
        "index_error": index_err,
        "yhgscx_probe": yhgscx_probe,
        "announcements": announcements,
    }
    OUT_ANNOUNCEMENTS.write_text(
        json.dumps(announcements_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[sync_miit] Wrote {OUT_ANNOUNCEMENTS.relative_to(REPO_ROOT)} ({len(announcements)} batches)")

    # Parse passenger NEVs from the latest tax-exemption catalog attachment(s)
    parsed_models: list[dict[str, Any]] = []
    parsed_sources: list[dict[str, Any]] = []
    parsed_count = 0

    for ann in announcements:
        if parsed_count >= catalog_batches:
            break
        tax_att = next(
            (a for a in (ann.get("attachments") or []) if a.get("category") == "tax_exemption_catalog"),
            None,
        )
        if not tax_att:
            continue
        print(f"[sync_miit] Parsing tax-exemption catalog: {tax_att['name']} ...")
        entries, parser_used, parse_err = parse_tax_exemption_attachment(
            ann, tax_att["url"], timeout=max(args.timeout, 30), retries=args.retries
        )
        parsed_sources.append(
            {
                "batch_number": ann.get("batch_number"),
                "batch_label": ann.get("batch_label"),
                "tax_exemption_batch": ann.get("tax_exemption_batch"),
                "publish_date": ann.get("publish_date"),
                "announcement_url": ann.get("url"),
                "attachment_name": tax_att["name"],
                "attachment_url": tax_att["url"],
                "parser": parser_used,
                "parsed_entries": len(entries),
                "error": parse_err,
            }
        )
        parsed_models.extend(entries)
        parsed_count += 1
        print(f"  - Parsed {len(entries)} passenger NEV entries via {parser_used}")

    bev_count = sum(1 for m in parsed_models if m.get("powertrain_type") == "BEV")
    phev_count = sum(1 for m in parsed_models if m.get("powertrain_type") == "PHEV")
    reev_count = sum(1 for m in parsed_models if m.get("powertrain_type") == "REEV")

    catalog_payload = {
        "synced_at": now_iso(),
        "data_as_of": today_iso(),
        "sources": parsed_sources,
        "total_passenger_entries": len(parsed_models),
        "bev_count": bev_count,
        "phev_count": phev_count,
        "reev_count": reev_count,
        "models": parsed_models,
    }
    OUT_CATALOG_LATEST.write_text(
        json.dumps(catalog_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[sync_miit] Wrote {OUT_CATALOG_LATEST.relative_to(REPO_ROOT)} ({len(parsed_models)} entries)")

    # Compare against repository catalog.json
    repo_models, code_to_file = load_repo_models()
    untracked_candidates, matched_pairs = build_untracked_candidates(parsed_models, repo_models, code_to_file)

    untracked_payload = {
        "synced_at": now_iso(),
        "data_as_of": today_iso(),
        "compared_against": "catalog.json",
        "repo_model_count": len(repo_models),
        "miit_passenger_entries": len(parsed_models),
        "matched_entries": len(matched_pairs),
        "total_untracked_models": len(untracked_candidates),
        "candidates": untracked_candidates,
    }
    OUT_UNTRACKED.write_text(
        json.dumps(untracked_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[sync_miit] Wrote {OUT_UNTRACKED.relative_to(REPO_ROOT)} "
        f"({len(untracked_candidates)} untracked candidates, {len(matched_pairs)} matched entries)"
    )

    applied_changes: list[dict[str, Any]] = []
    if args.apply:
        applied_changes = apply_miit_backfill(matched_pairs, dry_run=args.dry_run)
        mode_tag = "DRY-RUN" if args.dry_run else "APPLIED"
        print(f"[sync_miit] {mode_tag}: {len(applied_changes)} model files backfilled.")
        for ch in applied_changes:
            print(f"  - {ch['file']}: {', '.join(ch['updated_fields'])}")

    if args.write_report:
        report_path = Path(args.write_report)
        write_markdown_report(
            report_path,
            announcements,
            yhgscx_probe,
            catalog_payload,
            untracked_payload,
            applied_changes,
        )
        print(f"[sync_miit] Wrote report to {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
