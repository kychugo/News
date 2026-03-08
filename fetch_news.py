"""
fetch_news.py
Fetches the latest Hong Kong news from public RSS feeds and web scraping,
then generates docs/index.html for GitHub Pages.

Sources:
  - RTHK (English & Chinese) – RSS
  - HK Free Press – RSS
  - TVB News (Traditional Chinese) – web scrape
"""

import os
import re
import html
import json
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# News sources
# ---------------------------------------------------------------------------
# type "rss"    → fetched via feedparser
# type "scrape" → fetched via requests + BeautifulSoup
NEWS_FEEDS = [
    {
        "name": "RTHK (English)",
        "url": "https://rthk9.rthk.hk/rthk/news/rss/e_expressnews_e_conciseinenglish.xml",
        "source_url": "https://news.rthk.hk/rthk/en/",
        "type": "rss",
        "lang": "en",
    },
    {
        "name": "RTHK (中文)",
        "url": "https://rthk9.rthk.hk/rthk/news/rss/c_expressnews_cutnews.xml",
        "source_url": "https://news.rthk.hk/rthk/ch/",
        "type": "rss",
        "lang": "zh",
    },
    {
        "name": "HK Free Press",
        "url": "https://www.hongkongfp.com/feed/",
        "source_url": "https://www.hongkongfp.com/",
        "type": "rss",
        "lang": "en",
    },
    {
        "name": "The Standard",
        "url": "https://www.thestandard.com.hk/rss_news_all.xml",
        "source_url": "https://www.thestandard.com.hk/",
        "type": "rss",
        "lang": "en",
    },
    {
        "name": "Asia Times",
        "url": "https://asiatimes.com/feed/",
        "source_url": "https://asiatimes.com/",
        "type": "rss",
        "lang": "en",
    },
    {
        "name": "Coconuts Hong Kong",
        "url": "https://coconuts.co/hongkong/feed/",
        "source_url": "https://coconuts.co/hongkong/",
        "type": "rss",
        "lang": "en",
    },
    {
        "name": "TVB News (無綫新聞)",
        "url": "https://news.tvb.com/tc",
        "source_url": "https://news.tvb.com/tc",
        "type": "scrape",
        "scraper": "tvb",
        "lang": "zh",
    },
    {
        "name": "South China Morning Post",
        "url": "https://www.scmp.com/rss/91/feed",
        "source_url": "https://www.scmp.com/",
        "type": "rss",
        "lang": "en",
    },
    {
        "name": "BBC News (Hong Kong)",
        "url": "https://feeds.bbci.co.uk/news/topics/cp7r8vglne2t.rss",
        "source_url": "https://www.bbc.com/news/topics/cp7r8vglne2t",
        "type": "rss",
        "lang": "en",
    },
]

MAX_ITEMS_PER_FEED = 15  # articles to show per source
MAX_ARTICLE_AGE_DAYS = 7  # drop cached articles older than this

DATA_FILE = os.path.join(os.path.dirname(__file__), "docs", "news.json")

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HKNewsBot/1.0; "
        "+https://github.com/kychugo/News)"
    )
}


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------
def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text).strip()


def fetch_rss(feed_info: dict) -> list[dict]:
    """Fetch articles from an RSS/Atom feed."""
    feed = feedparser.parse(feed_info["url"])
    articles = []
    for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
        summary = _strip_html(entry.get("summary", entry.get("description", "")))
        articles.append(
            {
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", ""),
                "summary": summary[:300] + ("…" if len(summary) > 300 else ""),
                "published": entry.get("published", ""),
                "source": feed_info["name"],
                "source_url": feed_info["source_url"],
                "lang": feed_info["lang"],
            }
        )
    return articles


_MAX_JSON_DEPTH = 6  # Covers typical Next.js __NEXT_DATA__ nesting (props→pageProps→data→categories→articles)


def _find_article_lists(obj: object, depth: int = 0) -> list[list[dict]]:
    """
    Recursively search a parsed JSON object for lists that look like article
    collections (i.e. lists of dicts that contain a 'title' or 'headline' key).
    """
    if depth > _MAX_JSON_DEPTH:
        return []
    results: list[list[dict]] = []
    if isinstance(obj, list):
        # Detect article list: check up to the first 3 items so that lists
        # whose first entry lacks a title but subsequent entries have one are
        # still recognised correctly.
        sample = [item for item in obj[:3] if isinstance(item, dict)]
        if sample and any(
            item.get("title") or item.get("headline") for item in sample
        ):
            results.append(obj)  # type: ignore[arg-type]
        else:
            # Not an article list – descend into each element
            for item in obj:
                results.extend(_find_article_lists(item, depth + 1))
    elif isinstance(obj, dict):
        for val in obj.values():
            results.extend(_find_article_lists(val, depth + 1))
    return results


def _build_tvb_link(slug: str, fallback: str) -> str:
    """Convert a TVB article slug / path / URL to a full absolute URL."""
    if not slug:
        return fallback
    if slug.startswith("http"):
        return slug
    # Absolute path (e.g. "/tc/local/20240101/12345") – prepend domain only
    if slug.startswith("/"):
        return "https://news.tvb.com" + slug
    # Relative path (e.g. "local/20240101/12345") – prepend full base
    return f"https://news.tvb.com/tc/{slug}"


def fetch_tvb(feed_info: dict) -> list[dict]:
    """
    Scrape articles from the TVB News website (news.tvb.com/tc).

    Strategy 1 – look for __NEXT_DATA__ JSON embedded in the page (Next.js),
                 then walk the entire JSON tree to find article lists.
    Strategy 2 – fall back to parsing <a> tags with article-style hrefs.
    """
    resp = requests.get(feed_info["url"], headers=SCRAPE_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    articles: list[dict] = []

    # --- Strategy 1: Next.js __NEXT_DATA__ JSON ---
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if next_data_tag and next_data_tag.string:
        try:
            data = json.loads(next_data_tag.string)
            # Walk the entire props tree recursively to find article lists.
            # TVB stores articles in various nested paths depending on the page.
            all_lists = _find_article_lists(data)
            seen_titles: set[str] = set()
            for lst in all_lists:
                for item in lst:
                    if not isinstance(item, dict):
                        continue
                    title = (
                        item.get("title") or item.get("headline")
                        or item.get("name") or ""
                    )
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)
                    slug = (
                        item.get("slug") or item.get("url") or item.get("link")
                        or item.get("path") or item.get("articleUrl") or ""
                    )
                    link = _build_tvb_link(slug, feed_info["source_url"])
                    summary = _strip_html(
                        item.get("description") or item.get("summary")
                        or item.get("abstract") or ""
                    )
                    published = (
                        item.get("publishedAt") or item.get("publishTime")
                        or item.get("date") or item.get("createdAt") or ""
                    )
                    articles.append(
                        {
                            "title": title.strip(),
                            "link": link,
                            "summary": summary[:300] + ("…" if len(summary) > 300 else ""),
                            "published": str(published),
                            "source": feed_info["name"],
                            "source_url": feed_info["source_url"],
                            "lang": feed_info["lang"],
                        }
                    )
                    if len(articles) >= MAX_ITEMS_PER_FEED:
                        break
                if len(articles) >= MAX_ITEMS_PER_FEED:
                    break
        except (json.JSONDecodeError, AttributeError):
            pass  # fall through to strategy 2

    # --- Strategy 2: Parse <a> links that look like article URLs ---
    if not articles:
        seen: set[str] = set()
        for tag in soup.find_all("a", href=True):
            href: str = tag["href"]
            # TVB article URLs typically look like /tc/topic/... or /tc/...-NNNNNN
            if not re.search(r"/tc/[\w-]+/[\w-]", href):
                continue
            full_url = (
                href if href.startswith("http")
                else "https://news.tvb.com" + href
            )
            if full_url in seen:
                continue
            seen.add(full_url)
            title_text = tag.get_text(separator=" ", strip=True)
            if not title_text or len(title_text) < 5:
                continue
            articles.append(
                {
                    "title": title_text[:200],
                    "link": full_url,
                    "summary": "",
                    "published": "",
                    "source": feed_info["name"],
                    "source_url": feed_info["source_url"],
                    "lang": feed_info["lang"],
                }
            )
            if len(articles) >= MAX_ITEMS_PER_FEED:
                break

    return articles


def fetch_all_news() -> list[dict]:
    """Return a combined list of article dicts from all configured feeds."""
    all_articles: list[dict] = []
    for feed_info in NEWS_FEEDS:
        try:
            if feed_info["type"] == "rss":
                items = fetch_rss(feed_info)
            elif feed_info.get("scraper") == "tvb":
                items = fetch_tvb(feed_info)
            else:
                items = fetch_rss(feed_info)
            all_articles.extend(items)
            print(f"  ✓ {feed_info['name']}: {len(items)} articles")
        except Exception as exc:
            print(f"  ✗ {feed_info['name']}: {exc}")
    return all_articles


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="refresh" content="3600" />
  <title>Hong Kong News 香港新聞</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang TC",
                   "Noto Sans TC", Roboto, Helvetica, Arial, sans-serif;
      background: #f0f2f5;
      color: #1a1a2e;
    }}

    /* ---- Header ---- */
    header {{
      background: linear-gradient(135deg, #c0392b 0%, #922b21 100%);
      color: #fff;
      padding: 1.5rem 1rem 1rem;
      text-align: center;
      box-shadow: 0 2px 6px rgba(0,0,0,.3);
    }}
    header h1 {{ margin: 0 0 .3rem; font-size: 2rem; letter-spacing: .5px; }}
    header .sub {{
      margin: 0 0 .8rem;
      font-size: .88rem;
      opacity: .85;
    }}
    header .stats {{
      display: inline-block;
      background: rgba(255,255,255,.18);
      border-radius: 20px;
      padding: .25rem .9rem;
      font-size: .8rem;
      margin-bottom: .5rem;
    }}

    /* ---- Source nav ---- */
    nav {{
      background: #fff;
      border-bottom: 1px solid #e5e5e5;
      position: sticky;
      top: 0;
      z-index: 100;
      box-shadow: 0 1px 4px rgba(0,0,0,.08);
    }}
    nav ul {{
      list-style: none;
      margin: 0 auto;
      padding: 0 1rem;
      max-width: 960px;
      display: flex;
      flex-wrap: wrap;
      gap: .25rem;
    }}
    nav ul li a {{
      display: block;
      padding: .55rem .85rem;
      font-size: .85rem;
      font-weight: 600;
      color: #555;
      text-decoration: none;
      border-bottom: 3px solid transparent;
      transition: color .15s, border-color .15s;
    }}
    nav ul li a:hover {{
      color: #c0392b;
      border-bottom-color: #c0392b;
    }}

    /* ---- Main ---- */
    main {{
      max-width: 960px;
      margin: 1.5rem auto 3rem;
      padding: 0 1rem;
    }}

    /* ---- Source section ---- */
    .source-section {{ margin-bottom: 3rem; scroll-margin-top: 48px; }}
    .source-header {{
      display: flex;
      align-items: baseline;
      gap: .75rem;
      margin-bottom: 1rem;
    }}
    .source-title {{
      font-size: 1.2rem;
      font-weight: 700;
      border-left: 4px solid #c0392b;
      padding-left: .6rem;
      color: #922b21;
    }}
    .source-link {{
      font-size: .8rem;
      color: #c0392b;
      text-decoration: none;
      opacity: .8;
    }}
    .source-link:hover {{ opacity: 1; text-decoration: underline; }}
    .article-count {{
      font-size: .78rem;
      color: #aaa;
      margin-left: auto;
    }}

    /* ---- Cards ---- */
    .cards {{
      display: grid;
      gap: 1rem;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    }}
    .card {{
      background: #fff;
      border-radius: 10px;
      padding: 1rem 1.2rem;
      box-shadow: 0 1px 4px rgba(0,0,0,.10);
      display: flex;
      flex-direction: column;
      transition: box-shadow .2s, transform .15s;
    }}
    .card:hover {{
      box-shadow: 0 6px 18px rgba(0,0,0,.15);
      transform: translateY(-2px);
    }}
    .card .headline {{
      text-decoration: none;
      color: #1a1a2e;
      font-size: 1rem;
      font-weight: 600;
      line-height: 1.45;
      flex: 1;
    }}
    .card .headline:hover {{ color: #c0392b; }}
    .card .summary {{
      margin-top: .5rem;
      font-size: .84rem;
      color: #555;
      line-height: 1.55;
    }}
    .card .card-footer {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: .75rem;
      flex-wrap: wrap;
      gap: .3rem;
    }}
    .card .pub-date {{
      font-size: .73rem;
      color: #aaa;
    }}
    .card .source-badge {{
      font-size: .72rem;
      font-weight: 600;
      color: #fff;
      background: #c0392b;
      border-radius: 4px;
      padding: .15rem .45rem;
      text-decoration: none;
      white-space: nowrap;
    }}
    .card .source-badge:hover {{ background: #922b21; }}

    /* ---- Footer ---- */
    footer {{
      text-align: center;
      padding: 1.5rem 1rem;
      font-size: .78rem;
      color: #aaa;
      border-top: 1px solid #e5e5e5;
    }}
    footer a {{ color: #c0392b; text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <header>
    <h1>🇭🇰 Hong Kong News 香港新聞</h1>
    <p class="sub">Last updated: {updated} (UTC) &mdash; auto-refreshes every hour</p>
    <span class="stats">📰 {total} articles from {src_count} sources</span>
  </header>

  <nav aria-label="News sources">
    <ul>
      {nav_items}
    </ul>
  </nav>

  <main>
    {sections}
  </main>

  <footer>
    Powered by <a href="https://github.com/features/actions" target="_blank" rel="noopener">GitHub Actions</a>
    &mdash; Sources:
    <a href="https://news.rthk.hk/rthk/en/" target="_blank" rel="noopener">RTHK</a>,
    <a href="https://www.hongkongfp.com/" target="_blank" rel="noopener">HK Free Press</a>,
    <a href="https://www.thestandard.com.hk/" target="_blank" rel="noopener">The Standard</a>,
    <a href="https://asiatimes.com/" target="_blank" rel="noopener">Asia Times</a>,
    <a href="https://coconuts.co/hongkong/" target="_blank" rel="noopener">Coconuts HK</a>,
    <a href="https://news.tvb.com/tc" target="_blank" rel="noopener">TVB News</a>,
    <a href="https://www.scmp.com/" target="_blank" rel="noopener">SCMP</a>,
    <a href="https://www.bbc.com/news/topics/cp7r8vglne2t" target="_blank" rel="noopener">BBC News HK</a>
  </footer>
</body>
</html>
"""

NAV_ITEM_TEMPLATE = '<li><a href="#{anchor}">{source}</a></li>'

SECTION_TEMPLATE = """\
<div class="source-section" id="{anchor}">
  <div class="source-header">
    <span class="source-title">{source}</span>
    <a class="source-link" href="{source_url}" target="_blank" rel="noopener noreferrer">
      ↗ Visit source
    </a>
    <span class="article-count">{count} articles</span>
  </div>
  <div class="cards">
    {cards}
  </div>
</div>
"""

CARD_TEMPLATE = """\
<div class="card">
  <a class="headline" href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>
  {summary_block}
  <div class="card-footer">
    <span class="pub-date">{published}</span>
    <a class="source-badge" href="{source_url}" target="_blank" rel="noopener noreferrer"
       title="Visit {source} website">{source}</a>
  </div>
</div>
"""


def _slugify(text: str) -> str:
    """Create a simple URL-safe anchor id from a source name."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_html(articles: list[dict]) -> str:
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    # Group by source, preserving insertion order
    sources: dict[str, list[dict]] = {}
    for article in articles:
        sources.setdefault(article["source"], []).append(article)

    if not sources:
        empty = (
            '<p style="text-align:center;color:#aaa;margin-top:4rem;font-size:1.1rem;">'
            "⚠️ No news articles could be fetched right now. Please check back later.</p>"
        )
        return HTML_TEMPLATE.format(
            updated=updated,
            total=0,
            src_count=0,
            nav_items="",
            sections=empty,
        )

    nav_items_html = ""
    sections_html = ""

    for source, items in sources.items():
        anchor = _slugify(source)
        source_url = items[0]["source_url"]

        nav_items_html += NAV_ITEM_TEMPLATE.format(
            anchor=anchor, source=html.escape(source)
        )

        cards_html = ""
        for item in items:
            summary_block = ""
            if item["summary"]:
                summary_block = f'<p class="summary">{html.escape(item["summary"])}</p>'
            cards_html += CARD_TEMPLATE.format(
                link=html.escape(item["link"], quote=True),
                title=html.escape(item["title"]),
                summary_block=summary_block,
                published=html.escape(item["published"]),
                source_url=html.escape(source_url, quote=True),
                source=html.escape(source),
            )

        sections_html += SECTION_TEMPLATE.format(
            anchor=anchor,
            source=html.escape(source),
            source_url=html.escape(source_url, quote=True),
            count=len(items),
            cards=cards_html,
        )

    return HTML_TEMPLATE.format(
        updated=updated,
        total=len(articles),
        src_count=len(sources),
        nav_items=nav_items_html,
        sections=sections_html,
    )


# ---------------------------------------------------------------------------
# Article persistence helpers
# ---------------------------------------------------------------------------
def load_cached_articles() -> list[dict]:
    """Load previously saved articles from the JSON data file."""
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _parse_date(date_str: str) -> datetime | None:
    """Try to parse a date string into a timezone-aware datetime."""
    if not date_str:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def merge_articles(cached: list[dict], fresh: list[dict]) -> list[dict]:
    """
    Merge freshly fetched articles with cached ones.

    Rules:
    - Deduplicate by article link; fresh articles take precedence.
    - Articles older than MAX_ARTICLE_AGE_DAYS are dropped.
    - Output order: all fresh articles first, followed by non-duplicate
      cached articles (no source-level grouping is applied here).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_ARTICLE_AGE_DAYS)

    # Index fresh articles by link for fast lookup
    fresh_links: set[str] = {a["link"] for a in fresh}

    # Keep cached articles whose link is not superseded by a fresh one and are
    # not stale.  Articles with no parsable date are kept (we cannot age them).
    kept_cached: list[dict] = []
    for article in cached:
        if article["link"] in fresh_links:
            continue  # fresh version will be used
        dt = _parse_date(article.get("published", ""))
        if dt is not None and dt < cutoff:
            continue  # too old
        kept_cached.append(article)

    return fresh + kept_cached


def save_articles(articles: list[dict]) -> None:
    """Persist articles to the JSON data file."""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump(articles, fh, ensure_ascii=False, indent=2)
    print(f"Articles saved to {DATA_FILE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    print("Fetching Hong Kong news…")
    fresh_articles = fetch_all_news()
    print(f"Total articles fetched: {len(fresh_articles)}")

    cached_articles = load_cached_articles()
    print(f"Cached articles loaded: {len(cached_articles)}")

    articles = merge_articles(cached_articles, fresh_articles)
    print(f"Total articles after merge: {len(articles)}")

    out_path = os.path.join(os.path.dirname(__file__), "docs", "index.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    save_articles(articles)

    page = build_html(articles)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"HTML written to {out_path}")


if __name__ == "__main__":
    main()
