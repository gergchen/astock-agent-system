"""Workflow C: Thematic research — iwencai NL search + Eastmoney PDF cross-reference.

Designed for industry/theme deep-dive research.
"""

from ..research.iwencai import semantic_search
from ..research.eastmoney_report import get_reports


def thematic_research(
    queries: list[str],
    channel: str = "report",
    size: int = 50,
    cross_reference: bool = True,
) -> dict:
    """Multi-keyword thematic research with deduplication.

    Args:
        queries: List of NL search queries (e.g., ["人形机器人 丝杠", "减速器 国产替代"]).
        channel: iwencai channel ("report", "announcement", "news").
        size: Results per query.
        cross_reference: If True, supplement with Eastmoney reports for stocks found.

    Returns:
        Dict with:
        - articles: deduped article list
        - query_hits: per-query count
        - cross_reference: Eastmoney reports (if enabled)
    """
    seen_uids = set()
    all_articles = []
    query_hits = {}

    for q in queries:
        try:
            arts = semantic_search(q, channel=channel, size=size, deduplicate=False)
        except Exception:
            query_hits[q] = 0
            continue

        query_hits[q] = len(arts)
        for a in arts:
            uid = a.get("uid", "") or f"{a.get('title','')}|{a.get('publish_date','')}"
            if uid not in seen_uids:
                seen_uids.add(uid)
                all_articles.append(a)

    # Sort by date descending
    all_articles.sort(key=lambda x: x.get("publish_date", ""), reverse=True)

    result = {
        "total_deduped": len(all_articles),
        "query_hits": query_hits,
        "articles": all_articles,
    }

    # Cross-reference with Eastmoney
    if cross_reference:
        stock_codes = set()
        for a in all_articles[:10]:
            stocks = a.get("stock_infos") or []
            for s in stocks:
                sc = s.get("code", "")
                if sc:
                    stock_codes.add(sc)

        cross = {}
        for sc in stock_codes:
            try:
                em = get_reports(sc, max_pages=1)
                cross[sc] = len(em)
            except Exception:
                cross[sc] = 0
        result["cross_reference"] = cross

    return result
