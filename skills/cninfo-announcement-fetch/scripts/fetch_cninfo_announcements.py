"""Fetch announcement metadata and PDFs from cninfo.com.cn.

This script is intentionally conservative: sequential requests, small default
page size, and a sleep between pages/downloads.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
TOP_SEARCH_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"
PDF_BASE_URL = "http://static.cninfo.com.cn"

CATEGORY_ALIASES = {
    "annual_report": "category_ndbg_szsh",
    "semiannual_report": "category_bndbg_szsh",
    "quarterly_report": "category_yjdbg_szsh",
    "ipo": "category_szzb_szsh",
    "bond": "category_zqgg_szsh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch cninfo announcement metadata and optionally PDFs."
    )
    parser.add_argument("--keyword", default="", help="Full-text keyword.")
    parser.add_argument(
        "--category",
        default="",
        help="Cninfo category code or alias, such as annual_report.",
    )
    parser.add_argument("--stock-code", default="", help="Stock code, e.g. 000001.")
    parser.add_argument(
        "--company-name",
        default="",
        help="Company name or short name. Used to resolve stock when stock code is unknown.",
    )
    parser.add_argument(
        "--stock",
        default="",
        help="Raw cninfo stock parameter, e.g. 000001,gssz0000001.",
    )
    parser.add_argument(
        "--market",
        choices=["szse", "hke", "fund", "bond", "third"],
        default="",
        help="Cninfo market shortcut. Use hke for Hong Kong listings.",
    )
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD.")
    parser.add_argument("--column", default="szse", help="Cninfo column.")
    parser.add_argument("--plate", default="", help="Cninfo plate filter.")
    parser.add_argument("--page-size", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--download", action="store_true", help="Download PDFs.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for metadata and downloaded PDFs.",
    )
    return parser.parse_args()


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Referer": (
                "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch"
                "?url=disclosure/list/search"
            ),
            "Accept": "application/json,text/plain,*/*",
        }
    )
    return session


def resolve_stock(session: requests.Session, code: str, timeout: float) -> str:
    if not code:
        return ""
    response = session.post(
        TOP_SEARCH_URL,
        data={"keyWord": code, "maxNum": "10"},
        timeout=timeout,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    candidates = response.json()
    for item in candidates:
        if item.get("code") == code and item.get("orgId"):
            return f"{item['code']},{item['orgId']}"
    raise RuntimeError(f"Could not resolve stock code to cninfo orgId: {code}")


def resolve_stock_by_name(session: requests.Session, name: str, timeout: float) -> str:
    if not name:
        return ""
    response = session.post(
        TOP_SEARCH_URL,
        data={"keyWord": name, "maxNum": "10"},
        timeout=timeout,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    candidates = response.json()
    normalized = re.sub(r"\s+", "", name).lower()
    fallback = ""
    for item in candidates:
        code = item.get("code")
        org_id = item.get("orgId")
        if not code or not org_id:
            continue
        candidate_text = "".join(
            str(item.get(key) or "")
            for key in ("zwjc", "zwmc", "shortName", "secName", "name", "code")
        )
        candidate_norm = re.sub(r"\s+", "", candidate_text).lower()
        stock = f"{code},{org_id}"
        if not fallback:
            fallback = stock
        if normalized and normalized in candidate_norm:
            return stock
    return fallback


def strip_em(value: str | None) -> str:
    if not value:
        return ""
    return html.unescape(re.sub(r"</?em>", "", value))


def safe_filename(value: str, max_len: int = 120) -> str:
    value = strip_em(value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if len(value) > max_len:
        value = value[:max_len].rstrip(" .")
    return value or "announcement"


def format_time(ms: int | None) -> str:
    if not ms:
        return "unknown-date"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def normalize_query_args(args: argparse.Namespace) -> tuple[str, str, str, str]:
    column = args.market or args.column
    plate = args.plate
    category = CATEGORY_ALIASES.get(args.category, args.category)
    searchkey = args.keyword
    if column == "hke":
        if not plate:
            plate = "hkmb"
        if args.category == "annual_report":
            category = ""
            if not searchkey:
                searchkey = "年报"
    return column, plate, category, searchkey


def query_page(
    session: requests.Session,
    args: argparse.Namespace,
    page_num: int,
    stock_param: str,
) -> dict[str, Any]:
    column, plate, category, searchkey = normalize_query_args(args)
    payload = {
        "pageNum": str(page_num),
        "pageSize": str(args.page_size),
        "column": column,
        "tabName": "fulltext",
        "plate": plate,
        "stock": stock_param,
        "searchkey": searchkey,
        "secid": "",
        "category": category,
        "trade": "",
        "seDate": f"{args.start_date}~{args.end_date}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    response = session.post(QUERY_URL, data=payload, timeout=args.timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.json()


def download_pdf(
    session: requests.Session,
    announcement: dict[str, Any],
    pdf_dir: Path,
    timeout: float,
) -> dict[str, Any]:
    adjunct_url = announcement.get("adjunctUrl") or ""
    if not adjunct_url:
        return {"ok": False, "error": "missing adjunctUrl"}
    url = f"{PDF_BASE_URL}/{adjunct_url.lstrip('/')}"
    date = format_time(announcement.get("announcementTime"))
    sec_code = announcement.get("secCode") or "unknown"
    announcement_id = announcement.get("announcementId") or "unknown"
    title = safe_filename(announcement.get("announcementTitle") or "")
    filename = f"{date}_{sec_code}_{announcement_id}_{title}.pdf"
    path = pdf_dir / filename
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        path.write_bytes(response.content)
        return {"ok": True, "url": url, "path": str(path), "size": len(response.content)}
    except Exception as exc:  # noqa: BLE001 - persist failure detail for batch jobs.
        return {"ok": False, "url": url, "error": repr(exc)}


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    pdf_dir = output_dir / "pdfs"
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.download:
        pdf_dir.mkdir(parents=True, exist_ok=True)

    session = make_session()
    stock_param = args.stock or resolve_stock(session, args.stock_code, args.timeout)
    if not stock_param and args.company_name:
        stock_param = resolve_stock_by_name(session, args.company_name, args.timeout)
    if not stock_param and args.company_name and not args.keyword:
        args.keyword = args.company_name

    all_announcements: list[dict[str, Any]] = []
    page_summaries: list[dict[str, Any]] = []
    download_results: list[dict[str, Any]] = []

    for page_num in range(1, args.max_pages + 1):
        data = query_page(session, args, page_num, stock_param)
        announcements = data.get("announcements") or []
        page_summaries.append(
            {
                "pageNum": page_num,
                "count": len(announcements),
                "totalAnnouncement": data.get("totalAnnouncement"),
                "totalRecordNum": data.get("totalRecordNum"),
                "totalpages": data.get("totalpages"),
                "hasMore": data.get("hasMore"),
            }
        )
        all_announcements.extend(announcements)
        print(
            f"page={page_num} count={len(announcements)} "
            f"total={data.get('totalAnnouncement')}"
        )
        if not data.get("hasMore") or not announcements:
            break
        time.sleep(args.sleep)

    if args.download:
        for index, announcement in enumerate(all_announcements, start=1):
            result = download_pdf(session, announcement, pdf_dir, args.timeout)
            result["announcementId"] = announcement.get("announcementId")
            download_results.append(result)
            status = "ok" if result["ok"] else "failed"
            print(f"download {index}/{len(all_announcements)} {status}")
            time.sleep(args.sleep)

    column, plate, category, searchkey = normalize_query_args(args)
    metadata = {
        "query": {
            "keyword": args.keyword,
            "keywordResolved": searchkey,
            "category": args.category,
            "categoryResolved": category,
            "market": args.market,
            "stockCode": args.stock_code,
            "companyName": args.company_name,
            "stock": stock_param,
            "startDate": args.start_date,
            "endDate": args.end_date,
            "column": column,
            "plate": plate,
            "pageSize": args.page_size,
            "maxPages": args.max_pages,
            "download": args.download,
        },
        "pageSummaries": page_summaries,
        "downloadResults": download_results,
        "announcements": all_announcements,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "metadata.jsonl").open("w", encoding="utf-8") as handle:
        for announcement in all_announcements:
            handle.write(json.dumps(announcement, ensure_ascii=False) + "\n")

    ok_downloads = sum(1 for item in download_results if item.get("ok"))
    failed_downloads = len(download_results) - ok_downloads
    print(
        "done "
        f"announcements={len(all_announcements)} "
        f"download_ok={ok_downloads} "
        f"download_failed={failed_downloads} "
        f"output={output_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
