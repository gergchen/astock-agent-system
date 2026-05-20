"""International geopolitical news — NewsAPI + akshare global sources.

Primary: NewsAPI (newsapi.org) — needs NEWSAPI_API_KEY env var, free tier 100 req/day.
Fallback: akshare Sina/THS/Futu global news with keyword filtering — zero config,
          confirmed working from mainland China.

When proxy is available, RSS feeds (BBC, Al Jazeera, CNN) also become accessible
via the --rss flag.
"""

import re
import xml.etree.ElementTree as ET
from typing import Optional

import requests

from ..config import get_config
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import DataSourceError

# NewsAPI sources best for geopolitics / Middle East coverage
DEFAULT_NEWSAPI_SOURCES = [
    "bbc-news",
    "reuters",
    "al-jazeera-english",
    "cnn",
    "associated-press",
    "bloomberg",
]

# RSS feeds — reachable only when proxy is on
RSS_FEEDS = {
    "bbc-world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "al-jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "cnn-world": "http://rss.cnn.com/rss/edition_world.rss",
}

# Keywords for filtering Chinese-language financial news → geopolitics
GEOPOLITICS_CN_KEYWORDS = [
    "中东", "伊朗", "以色列", "沙特", "阿联酋", "加沙", "也门", "叙利亚",
    "伊拉克", "黎巴嫩", "真主党", "胡塞", "美军", "五角大楼", "航母",
    "导弹", "空袭", "军事", "冲突", "战争", "停火", "谈判",
    "石油", "原油", "OPEC", "能源危机", "避险", "黄金",
    "俄罗斯", "乌克兰", "北约", "核设施", "浓缩铀",
    "地缘", "制裁", "封锁", "海峡", "霍尔木兹",
]


def _newsapi_request(endpoint: str, params: dict) -> list[dict]:
    """Call NewsAPI v2 REST endpoint directly."""
    cfg = get_config()
    api_key = cfg.newsapi_api_key

    if not api_key:
        raise DataSourceError(
            "NEWSAPI_API_KEY not set. Get a free key at https://newsapi.org/register"
        )

    params["apiKey"] = api_key
    try:
        resp = requests.get(
            f"https://newsapi.org/v2/{endpoint}",
            params=params,
            timeout=cfg.http_timeout,
            headers={"User-Agent": cfg.http_user_agent},
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "ok":
            raise DataSourceError(f"NewsAPI error: {body.get('message', 'unknown')}")
        return body.get("articles", [])
    except requests.RequestException as e:
        raise DataSourceError(f"NewsAPI request failed: {e}") from e


# ── akshare fallback (works from mainland China) ────────────────────────────


def _fetch_akshare_global() -> list[dict]:
    """Fetch global financial news from akshare Sina + THS sources.

    These are HTTP-based (no TCP port restrictions) and confirmed working.
    Content is Chinese-language, covers international events affecting markets.
    """
    articles = []

    # Sina global finance news
    try:
        import akshare as ak
        df = ak.stock_info_global_sina()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                articles.append({
                    "title": str(row.iloc[1])[:120] if len(row) > 1 else "",
                    "summary": "",
                    "url": "",
                    "published": str(row.iloc[0]) if len(row) > 0 else "",
                    "source": "sina-global",
                })
    except Exception:
        pass

    # THS global news
    try:
        import akshare as ak
        df = ak.stock_info_global_ths()
        if df is not None and not df.empty:
            cols = list(df.columns)
            title_col = cols[0] if len(cols) > 0 else None
            content_col = cols[1] if len(cols) > 1 else None
            time_col = cols[2] if len(cols) > 2 else None
            source_col = cols[3] if len(cols) > 3 else None

            for _, row in df.iterrows():
                articles.append({
                    "title": str(row[title_col])[:150] if title_col else "",
                    "summary": str(row[content_col])[:300] if content_col else "",
                    "url": "",
                    "published": str(row[time_col]) if time_col else "",
                    "source": f"ths-global{(' /' + str(row[source_col])) if source_col else ''}",
                })
    except Exception:
        pass

    return articles


def _filter_cn_keywords(articles: list[dict], extra_keywords: list[str] = None) -> list[dict]:
    """Filter articles by geopolitics keywords (Chinese + optional extras)."""
    keywords = GEOPOLITICS_CN_KEYWORDS + (extra_keywords or [])
    result = []
    for a in articles:
        text = (a.get("title", "") + " " + a.get("summary", "")).lower()
        if any(kw.lower() in text for kw in keywords):
            result.append(a)
    return result


# ── RSS fallback (works with proxy) ─────────────────────────────────────────


def _parse_rss_feed(url: str) -> list[dict]:
    """Parse RSS/Atom feed and return normalized article dicts."""
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "astock-data/2.0"})
        resp.raise_for_status()
    except requests.RequestException:
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    articles = []

    # RSS 2.0
    for item in root.iter("item"):
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        description = _text(item.find("description"))
        pub_date = _text(item.find("pubDate"))
        articles.append({
            "title": _clean_html(title),
            "summary": _clean_html(description)[:300],
            "url": link,
            "published": pub_date,
            "source": "rss",
        })

    # Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    atom_ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{atom_ns}entry"):
        title = _text(entry.find(f"{atom_ns}title"))
        link_el = entry.find(f"{atom_ns}link")
        link = link_el.get("href", "") if link_el is not None else ""
        summary = _text(entry.find(f"{atom_ns}summary"))
        updated = _text(entry.find(f"{atom_ns}updated"))
        articles.append({
            "title": _clean_html(title),
            "summary": _clean_html(summary)[:300],
            "url": link,
            "published": updated,
            "source": "rss",
        })

    return articles


def _text(el) -> str:
    if el is None:
        return ""
    return el.text or ""


def _clean_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _filter_en_keywords(articles: list[dict], keywords: list[str]) -> list[dict]:
    """Filter articles whose title/summary match any keyword (case-insensitive)."""
    if not keywords:
        return articles
    result = []
    for a in articles:
        text = (a.get("title", "") + " " + a.get("summary", "")).lower()
        if any(kw.lower() in text for kw in keywords):
            result.append(a)
    return result


# ── Public API ───────────────────────────────────────────────────────────────


@retry()
@rate_limit("newsapi")
def search_geopolitical_news(
    query: str,
    max_results: int = 30,
    sources: Optional[list[str]] = None,
    from_date: Optional[str] = None,
    use_rss: bool = False,
    use_akshare: bool = True,
) -> list[dict]:
    """Search international geopolitical news.

    Backend priority:
    1. NewsAPI (if NEWSAPI_API_KEY is set) — English, 100 req/day free tier
    2. akshare Sina/THS global (default fallback) — Chinese, works from mainland
    3. RSS feeds (--rss flag) — English, needs proxy in mainland China

    Args:
        query: Search keywords (NewsAPI: AND/OR/NOT supported; akshare: simple match).
        max_results: Max articles to return.
        sources: Comma-separated NewsAPI source IDs.
        from_date: ISO date string, e.g. "2026-05-10".
        use_rss: Force RSS fallback (needs proxy in China).
        use_akshare: Use akshare as fallback (default True). Set False to skip.

    Returns:
        List of dicts with: title, summary, url, published, source.
    """
    if use_rss:
        return _search_via_rss(query, max_results)

    # Try NewsAPI first
    cfg = get_config()
    if cfg.newsapi_api_key:
        try:
            params = {
                "q": query,
                "pageSize": min(max_results, 100),
                "sortBy": "publishedAt",
                "language": "en",
            }
            if sources:
                params["sources"] = ",".join(sources)
            if from_date:
                params["from"] = from_date

            articles = _newsapi_request("everything", params)
            result = []
            for a in articles[:max_results]:
                result.append({
                    "title": a.get("title", ""),
                    "summary": a.get("description", ""),
                    "url": a.get("url", ""),
                    "published": a.get("publishedAt", ""),
                    "source": a.get("source", {}).get("name", ""),
                    "image_url": a.get("urlToImage", ""),
                })
            if result:
                return result
        except DataSourceError:
            pass

    # Fallback: akshare global news with keyword filtering
    if use_akshare:
        articles = _fetch_akshare_global()
        keywords = _extract_keywords(query)
        filtered = _filter_cn_keywords(articles, keywords)
        return filtered[:max_results]

    # Last resort: RSS (likely blocked without proxy)
    return _search_via_rss(query, max_results)


def _extract_keywords(query: str) -> list[str]:
    """Extract meaningful keywords from a query string."""
    # Remove NewsAPI operators and common words
    stop = {"and", "or", "not", "the", "in", "of", "to", "a", "is", "for", "on", "with"}
    words = re.findall(r'\w+', query.lower())
    return [w for w in words if w not in stop and len(w) > 1]


def _search_via_rss(query: str, max_results: int) -> list[dict]:
    """Fallback: fetch RSS feeds and filter by keyword."""
    keywords = _extract_keywords(query)
    all_articles = []
    for name, url in RSS_FEEDS.items():
        articles = _parse_rss_feed(url)
        for a in articles:
            a["source"] = name
        all_articles.extend(articles)

    filtered = _filter_en_keywords(all_articles, keywords)
    return filtered[:max_results]


@retry()
@rate_limit("newsapi")
def get_top_headlines(
    category: str = "world",
    max_results: int = 30,
    use_rss: bool = False,
    use_akshare: bool = True,
) -> list[dict]:
    """Get top world headlines from major international sources.

    Args:
        category: NewsAPI category (world, business, technology, etc.).
        max_results: Max headlines.
        use_rss: Force RSS (needs proxy in China).
        use_akshare: Use akshare as fallback (default True).

    Returns:
        List of dicts with: title, summary, url, published, source.
    """
    if use_rss:
        all_articles = []
        for name, url in RSS_FEEDS.items():
            articles = _parse_rss_feed(url)
            for a in articles:
                a["source"] = name
            all_articles.extend(articles)
        return sorted(all_articles, key=lambda x: x.get("published", ""), reverse=True)[:max_results]

    # Try NewsAPI
    cfg = get_config()
    if cfg.newsapi_api_key:
        try:
            articles = _newsapi_request("top-headlines", {
                "category": category,
                "pageSize": min(max_results, 100),
                "language": "en",
            })
            result = []
            for a in articles[:max_results]:
                result.append({
                    "title": a.get("title", ""),
                    "summary": a.get("description", ""),
                    "url": a.get("url", ""),
                    "published": a.get("publishedAt", ""),
                    "source": a.get("source", {}).get("name", ""),
                    "image_url": a.get("urlToImage", ""),
                })
            if result:
                return result
        except DataSourceError:
            pass

    # Fallback: akshare global, filtered for broad geopolitics
    if use_akshare:
        articles = _fetch_akshare_global()
        filtered = _filter_cn_keywords(articles)
        return filtered[:max_results]

    return []


# Keyword-grouped presets for common geopolitical topics
GEOPOLITICAL_PRESETS = {
    "middle-east": "Middle East OR Iran OR Israel OR Gaza OR Yemen OR Saudi Arabia OR UAE",
    "us-china": "US China OR Taiwan OR South China Sea OR trade war OR tariffs",
    "ukraine": "Ukraine OR Russia OR NATO OR Zelensky OR Putin",
    "energy": "oil price OR OPEC OR natural gas OR energy crisis OR crude",
    "defense": "military OR missile OR defense spending OR arms deal",
}
