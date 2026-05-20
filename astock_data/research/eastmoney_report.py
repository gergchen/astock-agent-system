"""Eastmoney Research Reports — report list + PDF download.

API: reportapi.eastmoney.com (public JSON API, free, no key).
PDF: pdf.dfcfw.com (requires Referer header).
"""

import re
import time
from pathlib import Path

import requests

from ..config import get_config
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import AKShareError


REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@retry()
@rate_limit("akshare")
def get_reports(code: str, max_pages: int = 5) -> list[dict]:
    """Fetch research report list for a stock.

    Args:
        code: 6-digit stock code.
        max_pages: Max pages to fetch (100 reports per page).

    Returns:
        List of report dicts with keys: title, publishDate, orgSName,
        infoCode, predictThisYearEps, predictNextYearEps,
        predictNextTwoYearEps, emRatingName, indvInduName.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Referer": "https://data.eastmoney.com/",
    })

    all_records = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": "2000-01-01", "endTime": "2030-01-01",
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": str(code).zfill(6), "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        try:
            r = session.get(REPORT_API, params=params, timeout=30)
            r.raise_for_status()
            d = r.json()
        except requests.RequestException as e:
            raise AKShareError(f"东财研报 fetch failed for {code}: {e}") from e

        rows = d.get("data") or []
        if not rows:
            break
        all_records.extend(rows)
        if page >= (d.get("TotalPage", 1) or 1):
            break
        time.sleep(0.3)

    return all_records


def download_report_pdf(
    info_code: str,
    date: str = "",
    org: str = "",
    title: str = "",
    target_dir: str = "./reports",
) -> str | None:
    """Download a single research report PDF.

    Args:
        info_code: Eastmoney infoCode from report record.
        date: Publication date (for filename).
        org: Organization name (for filename).
        title: Report title (for filename).
        target_dir: Save directory.

    Returns:
        File path on success, None on failure.
    """
    if not info_code:
        return None

    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80] if title else "report"
    fname = f"{date}_{org}_{safe_title}.pdf" if date else f"{info_code}.pdf"
    target = Path(target_dir) / fname

    if target.exists():
        return str(target)

    url = PDF_TPL.format(info_code=info_code)
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"},
            timeout=60,
        )
        if r.status_code == 200 and len(r.content) >= 1024:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(r.content)
            return str(target)
    except requests.RequestException:
        pass
    return None
