"""
fetch_news.py
Fetches the latest Hong Kong and world news from public RSS feeds and web scraping,
then generates docs/index.html for GitHub Pages.

Sources:
  - RTHK (English & Chinese) – RSS
  - HK Free Press – RSS
  - The Standard – RSS
  - Asia Times – RSS
  - Coconuts Hong Kong – RSS
  - TVB News (Traditional Chinese) – web scrape
  - South China Morning Post – RSS
  - BBC News (Hong Kong) – RSS
  - Google News (US) – RSS
"""

import os
import re
import html
import json
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

from ai_features import load_ai_content, _no_response_text

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
    {
        "name": "Google News (US)",
        "url": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "source_url": "https://news.google.com/home?hl=en-US&gl=US&ceid=US:en",
        "type": "rss",
        "lang": "en",
    },
]

MAX_ITEMS_PER_FEED = 15  # articles to show per source
MAX_ARTICLE_AGE_DAYS = 3  # drop cached articles older than this

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


def _extract_image(entry) -> str:  # type: ignore[no-untyped-def]
    """Extract the best available image URL from a feedparser entry."""
    # media:thumbnail (Yahoo Media RSS)
    thumbnails = getattr(entry, "media_thumbnail", None)
    if thumbnails and isinstance(thumbnails, list):
        url = thumbnails[0].get("url", "")
        if url:
            return url

    # media:content with medium="image"
    media_content = getattr(entry, "media_content", None)
    if media_content and isinstance(media_content, list):
        for m in media_content:
            if m.get("medium") == "image" or m.get("type", "").startswith("image/"):
                url = m.get("url", "")
                if url:
                    return url
        # fallback: first media:content item regardless of medium
        url = media_content[0].get("url", "")
        if url:
            return url

    # <enclosure> of image type
    enclosures = getattr(entry, "enclosures", None)
    if enclosures and isinstance(enclosures, list):
        for enc in enclosures:
            if enc.get("type", "").startswith("image/"):
                url = enc.get("href", enc.get("url", ""))
                if url:
                    return url

    # Try to pull the first <img> tag out of content or summary HTML
    for attr in ("content", "summary", "description"):
        raw = ""
        if attr == "content":
            entry_content = getattr(entry, "content", None)
            if entry_content and isinstance(entry_content, list):
                raw = entry_content[0].get("value", "")
        else:
            raw = entry.get(attr, "")
        if raw:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw, re.IGNORECASE)
            if m:
                return m.group(1)

    return ""


def fetch_rss(feed_info: dict) -> list[dict]:
    """Fetch articles from an RSS/Atom feed.

    Uses *requests* to download the raw feed with a custom User-Agent and
    timeout, then hands the raw bytes to feedparser for parsing.  This avoids
    the common failure mode where sites block feedparser's default user-agent
    or the socket hangs indefinitely.
    """
    resp = requests.get(feed_info["url"], headers=SCRAPE_HEADERS, timeout=20)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    articles = []
    for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
        # Prefer full article content when available (Atom <content> or RSS
        # content:encoded), then fall back to summary / description.
        content = ""
        entry_content = getattr(entry, "content", None)
        if entry_content:
            content = _strip_html(entry_content[0].get("value", ""))
        if not content:
            content = _strip_html(entry.get("summary", entry.get("description", "")))
        articles.append(
            {
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", ""),
                "summary": content[:2000] + ("…" if len(content) > 2000 else ""),
                "published": entry.get("published", ""),
                "image": _extract_image(entry),
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
                    image = (
                        item.get("image") or item.get("thumbnail")
                        or item.get("imageUrl") or item.get("img") or ""
                    )
                    if isinstance(image, dict):
                        image = image.get("url") or image.get("src") or ""
                    articles.append(
                        {
                            "title": title.strip(),
                            "link": link,
                            "summary": summary[:2000] + ("…" if len(summary) > 2000 else ""),
                            "published": str(published),
                            "image": str(image),
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
                    "image": "",
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
# HTML generation (wabi-sabi aesthetic)
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en" data-lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="refresh" content="3600" />
  <title>Hong Kong News 香港新聞</title>
  <style>
    /* ---- Base ---- */
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", "PingFang TC", "Noto Serif TC",
                   "Noto Sans TC", serif;
      background: #f2ede4;
      color: #3a3028;
      line-height: 1.65;
    }}

    /* ---- Language visibility ---- */
    html[data-lang="en"] .zh-content {{ display: none; }}
    html[data-lang="zh"] .en-content {{ display: none; }}

    /* ---- Language toggle ---- */
    .lang-toggle {{
      display: inline-flex;
      gap: 0;
      border: 1px solid #c9bfaf;
      border-radius: 2px;
      overflow: hidden;
      margin-top: .7rem;
    }}
    .lang-btn {{
      background: transparent;
      border: none;
      padding: .3rem .9rem;
      font-size: .78rem;
      color: #7a6555;
      cursor: pointer;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      transition: background .2s, color .2s;
    }}
    .lang-btn.active {{
      background: #c9bfaf;
      color: #3a3028;
      font-weight: 600;
    }}
    .lang-btn:hover:not(.active) {{ background: #ede6da; }}

    /* ---- Header ---- */
    header {{
      background: #e8dfd0;
      border-bottom: 1px solid #c9bfaf;
      padding: 2rem 1rem 1.4rem;
      text-align: center;
    }}
    header h1 {{
      margin: 0 0 .4rem;
      font-size: 1.9rem;
      font-weight: normal;
      letter-spacing: .04em;
      color: #5c4033;
    }}
    header .sub {{
      margin: 0 0 .8rem;
      font-size: .82rem;
      color: #8a7060;
      font-style: italic;
    }}
    header .stats {{
      display: inline-block;
      border: 1px solid #c9bfaf;
      border-radius: 2px;
      padding: .2rem .85rem;
      font-size: .78rem;
      color: #7a6555;
      letter-spacing: .02em;
    }}

    /* ---- Source nav ---- */
    nav {{
      background: #ede6da;
      border-bottom: 1px solid #c9bfaf;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    nav ul {{
      list-style: none;
      margin: 0 auto;
      padding: 0 1rem;
      max-width: 1000px;
      display: flex;
      flex-wrap: wrap;
      gap: .1rem;
    }}
    nav ul li a {{
      display: block;
      padding: .5rem .8rem;
      font-size: .8rem;
      color: #7a6555;
      text-decoration: none;
      border-bottom: 2px solid transparent;
      transition: color .2s, border-color .2s;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: .01em;
    }}
    nav ul li a:hover {{
      color: #5c4033;
      border-bottom-color: #a0785a;
    }}

    /* ---- Main ---- */
    main {{
      max-width: 1000px;
      margin: 2rem auto 4rem;
      padding: 0 1rem;
    }}

    /* ---- Source section ---- */
    .source-section {{
      margin-bottom: 3.5rem;
      scroll-margin-top: 44px;
    }}
    .source-header {{
      display: flex;
      align-items: baseline;
      gap: .8rem;
      margin-bottom: 1.1rem;
      border-bottom: 1px solid #c9bfaf;
      padding-bottom: .5rem;
    }}
    .source-title {{
      font-size: 1.05rem;
      font-weight: normal;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: #5c4033;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .source-link {{
      font-size: .75rem;
      color: #a0785a;
      text-decoration: none;
      font-style: italic;
    }}
    .source-link:hover {{ text-decoration: underline; }}
    .article-count {{
      font-size: .72rem;
      color: #b0a090;
      margin-left: auto;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    /* ---- Cards grid ---- */
    .cards {{
      display: grid;
      gap: 1.1rem;
      grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
    }}

    /* ---- Card ---- */
    .card {{
      background: #faf5ed;
      border: 1px solid #d4c9b8;
      border-radius: 2px;
      display: flex;
      flex-direction: column;
      transition: border-color .25s, box-shadow .25s;
      cursor: pointer;
      overflow: hidden;
    }}
    .card:hover {{
      border-color: #a0785a;
      box-shadow: 2px 3px 10px rgba(90,60,30,.10);
    }}
    .card-thumb {{
      width: 100%;
      aspect-ratio: 16/9;
      object-fit: cover;
      display: block;
      border-bottom: 1px solid #d4c9b8;
      background: #ede6da;
    }}
    .card-body {{
      padding: 1.1rem 1.2rem 1rem;
      display: flex;
      flex-direction: column;
      flex: 1;
    }}
    .card .headline {{
      color: #3a3028;
      font-size: .98rem;
      font-weight: bold;
      line-height: 1.5;
      flex: 1;
    }}
    .card:hover .headline {{ color: #7b4f2e; }}
    .card .summary {{
      margin-top: .6rem;
      font-size: .83rem;
      color: #6a5848;
      line-height: 1.6;
      font-family: Georgia, "Times New Roman", serif;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .card .card-footer {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: .85rem;
      padding-top: .6rem;
      border-top: 1px solid #e0d5c5;
      flex-wrap: wrap;
      gap: .3rem;
    }}
    .card .pub-date {{
      font-size: .7rem;
      color: #b0a090;
      font-style: italic;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .card .source-badge {{
      font-size: .68rem;
      color: #7b4f2e;
      background: transparent;
      border: 1px solid #c4a882;
      border-radius: 2px;
      padding: .12rem .45rem;
      white-space: nowrap;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: .02em;
    }}
    .card .read-more {{
      font-size: .72rem;
      color: #a0785a;
      font-style: italic;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin-top: .4rem;
    }}

    /* ---- Modal overlay ---- */
    .modal-overlay {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(50,38,28,.55);
      z-index: 500;
      align-items: flex-start;
      justify-content: center;
      padding: 2rem 1rem;
      overflow-y: auto;
    }}
    .modal-overlay.open {{ display: flex; }}
    .modal {{
      background: #faf5ed;
      border: 1px solid #c9bfaf;
      border-radius: 3px;
      max-width: 720px;
      width: 100%;
      position: relative;
      box-shadow: 0 8px 40px rgba(50,38,28,.25);
      animation: modalIn .18s ease-out;
      margin: auto;
    }}
    @keyframes modalIn {{
      from {{ opacity: 0; transform: translateY(-18px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .modal-close {{
      position: absolute;
      top: .7rem;
      right: .9rem;
      background: none;
      border: none;
      font-size: 1.4rem;
      color: #8a7060;
      cursor: pointer;
      line-height: 1;
      padding: .2rem .4rem;
      border-radius: 2px;
      transition: color .2s, background .2s;
    }}
    .modal-close:hover {{ color: #3a3028; background: #ede6da; }}
    .modal-image {{
      width: 100%;
      max-height: 360px;
      object-fit: cover;
      display: block;
      border-bottom: 1px solid #d4c9b8;
      border-radius: 3px 3px 0 0;
    }}
    .modal-content {{
      padding: 1.6rem 1.8rem 1.8rem;
    }}
    .modal-meta {{
      display: flex;
      align-items: center;
      gap: .7rem;
      flex-wrap: wrap;
      margin-bottom: .9rem;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .modal-source-badge {{
      font-size: .72rem;
      color: #7b4f2e;
      background: transparent;
      border: 1px solid #c4a882;
      border-radius: 2px;
      padding: .15rem .5rem;
      white-space: nowrap;
      letter-spacing: .02em;
    }}
    .modal-date {{
      font-size: .72rem;
      color: #b0a090;
      font-style: italic;
    }}
    .modal-title {{
      font-size: 1.3rem;
      font-weight: bold;
      line-height: 1.45;
      color: #3a3028;
      margin: 0 0 1rem;
    }}
    .modal-body {{
      font-size: .92rem;
      color: #4a3c30;
      line-height: 1.75;
      white-space: pre-wrap;
      font-family: Georgia, "Times New Roman", serif;
      margin-bottom: 1.4rem;
    }}
    .modal-actions {{
      display: flex;
      gap: .8rem;
      flex-wrap: wrap;
      border-top: 1px solid #e0d5c5;
      padding-top: 1rem;
    }}
    .btn-read-full {{
      display: inline-block;
      padding: .55rem 1.1rem;
      background: #7b4f2e;
      color: #faf5ed;
      border-radius: 2px;
      text-decoration: none;
      font-size: .82rem;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: .02em;
      transition: background .2s;
    }}
    .btn-read-full:hover {{ background: #5c3820; }}
    .btn-visit-source {{
      display: inline-block;
      padding: .55rem 1.1rem;
      background: transparent;
      color: #7b4f2e;
      border: 1px solid #c4a882;
      border-radius: 2px;
      text-decoration: none;
      font-size: .82rem;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: .02em;
      transition: background .2s, color .2s;
    }}
    .btn-visit-source:hover {{ background: #ede0cf; color: #5c3020; }}

    /* ---- Footer ---- */
    footer {{
      text-align: center;
      padding: 1.5rem 1rem;
      font-size: .75rem;
      color: #b0a090;
      border-top: 1px solid #c9bfaf;
      font-style: italic;
      font-family: Georgia, serif;
    }}
    footer a {{ color: #a0785a; text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}

    /* ---- AI sections ---- */
    .ai-section {{
      background: #f5f0e8;
      border: 1px solid #c9bfaf;
      border-radius: 3px;
      padding: 1.5rem 1.8rem;
      margin-bottom: 3rem;
      scroll-margin-top: 44px;
    }}
    .ai-section-header {{
      display: flex;
      align-items: baseline;
      gap: .7rem;
      margin-bottom: 1.2rem;
      border-bottom: 1px solid #c9bfaf;
      padding-bottom: .5rem;
      flex-wrap: wrap;
    }}
    .ai-section-title {{
      font-size: 1.05rem;
      font-weight: normal;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: #5c4033;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
    }}
    .ai-badge {{
      display: inline-block;
      background: #7b4f2e;
      color: #faf5ed;
      font-size: .62rem;
      padding: .1rem .45rem;
      border-radius: 2px;
      letter-spacing: .04em;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    /* Editorial */
    .editorial-topic {{
      font-size: .82rem;
      color: #8a7060;
      font-style: italic;
      margin-bottom: 1rem;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .editorial-body {{
      font-size: .95rem;
      line-height: 1.85;
      color: #4a3c30;
      font-family: Georgia, "Times New Roman", serif;
      white-space: pre-wrap;
    }}
    .editorial-attribution {{
      margin-top: 1rem;
      font-size: .75rem;
      color: #b0a090;
      font-style: italic;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    /* Arena */
    .arena-topic {{
      background: #ede6da;
      border-left: 3px solid #a0785a;
      padding: .7rem 1rem;
      margin-bottom: 1.4rem;
      font-size: .88rem;
      color: #5c4033;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .arena-topic strong {{ font-weight: 600; }}
    .arena-messages {{ display: flex; flex-direction: column; gap: 1rem; }}
    .arena-msg {{
      background: #faf5ed;
      border: 1px solid #d4c9b8;
      border-radius: 3px;
      padding: 1rem 1.2rem;
    }}
    .arena-msg-header {{
      display: flex;
      align-items: center;
      gap: .5rem;
      margin-bottom: .6rem;
    }}
    .arena-model-badge {{
      display: inline-block;
      font-size: .72rem;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-weight: 600;
      padding: .18rem .55rem;
      border-radius: 2px;
      letter-spacing: .03em;
    }}
    .badge-openai   {{ background: #dbe8f5; color: #1a4a7a; }}
    .badge-gemini   {{ background: #d6f0e0; color: #1a5a35; }}
    .badge-claude   {{ background: #f5e6d6; color: #7a3a1a; }}
    .badge-glm      {{ background: #e8d6f5; color: #4a1a7a; }}
    .badge-deepseek {{ background: #f5d6e8; color: #7a1a50; }}
    .badge-qwen     {{ background: #f0e8d6; color: #5a4010; }}
    .badge-default  {{ background: #e8e8e8; color: #444; }}
    .arena-msg-body {{
      font-size: .88rem;
      line-height: 1.8;
      color: #4a3c30;
      font-family: Georgia, "Times New Roman", serif;
      white-space: pre-wrap;
    }}
    .ai-empty {{
      color: #b0a090;
      font-style: italic;
      font-size: .88rem;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .editorial-topic-link, .arena-topic-link {{
      color: inherit;
      text-decoration: underline;
      text-decoration-color: #c8a880;
      text-underline-offset: 2px;
    }}
    .editorial-topic-link:hover, .arena-topic-link:hover {{
      color: #7a4a20;
      text-decoration-color: #7a4a20;
    }}
  </style>
</head>
<body>
  <header>
    <h1>🇭🇰 Hong Kong News &ensp;香港新聞</h1>
    <p class="sub">Last updated: {updated} UTC &mdash; refreshes every hour</p>
    <span class="stats">📰 {total} articles &thinsp;&middot;&thinsp; {src_count} sources</span>
    <div class="lang-toggle" role="group" aria-label="Language / 語言">
      <button class="lang-btn" data-lang="en" onclick="setLang('en')">English</button>
      <button class="lang-btn" data-lang="zh" onclick="setLang('zh')">廣東話</button>
    </div>
  </header>

  <nav aria-label="News sources">
    <ul>
      <li><a href="#ai-editorial"><span class="en-content">✍ AI Editorial</span><span class="zh-content">✍ AI社評</span></a></li>
      <li><a href="#ai-arena"><span class="en-content">🎙 News Arena</span><span class="zh-content">🎙 新聞擂台</span></a></li>
      {nav_items}
    </ul>
  </nav>

  <main>
    {ai_sections}
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
    <a href="https://www.bbc.com/news/topics/cp7r8vglne2t" target="_blank" rel="noopener">BBC News HK</a>,
    <a href="https://news.google.com/home?hl=en-US&gl=US&ceid=US:en" target="_blank" rel="noopener">Google News (US)</a>
  </footer>

  <!-- ---- Article detail modal ---- -->
  <div class="modal-overlay" id="newsModal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
    <div class="modal">
      <button class="modal-close" id="modalClose" aria-label="Close">&times;</button>
      <img class="modal-image" id="modalImage" src="" alt="" />
      <div class="modal-content">
        <div class="modal-meta">
          <span class="modal-source-badge" id="modalSource"></span>
          <span class="modal-date" id="modalDate"></span>
        </div>
        <h2 class="modal-title" id="modalTitle"></h2>
        <p class="modal-body" id="modalBody"></p>
        <div class="modal-actions">
          <a class="btn-read-full" id="modalReadFull" href="#" target="_blank" rel="noopener noreferrer">↗ Read full article</a>
          <a class="btn-visit-source" id="modalVisitSource" href="#" target="_blank" rel="noopener noreferrer">Visit source website</a>
        </div>
      </div>
    </div>
  </div>

  <script>
    (function () {{
      var overlay = document.getElementById('newsModal');
      var modalImage = document.getElementById('modalImage');
      var modalSource = document.getElementById('modalSource');
      var modalDate = document.getElementById('modalDate');
      var modalTitle = document.getElementById('modalTitle');
      var modalBody = document.getElementById('modalBody');
      var modalReadFull = document.getElementById('modalReadFull');
      var modalVisitSource = document.getElementById('modalVisitSource');
      var closeBtn = document.getElementById('modalClose');

      function safeUrl(url) {{
        try {{
          var u = new URL(url);
          return (u.protocol === 'https:' || u.protocol === 'http:') ? url : '#';
        }} catch (e) {{ return '#'; }}
      }}

      function openModal(card) {{
        modalTitle.textContent = card.dataset.title || '';
        modalBody.textContent = card.dataset.summary || '';
        modalDate.textContent = card.dataset.published || '';
        modalSource.textContent = card.dataset.source || '';
        modalReadFull.href = safeUrl(card.dataset.link || '');
        modalVisitSource.href = safeUrl(card.dataset.sourceUrl || '');
        modalVisitSource.textContent = 'Visit ' + (card.dataset.source || 'source') + ' website';

        var img = safeUrl(card.dataset.image || '');
        if (img && img !== '#') {{
          modalImage.src = img;
          modalImage.alt = card.dataset.title || '';
          modalImage.style.display = 'block';
        }} else {{
          modalImage.src = '';
          modalImage.style.display = 'none';
        }}

        overlay.classList.add('open');
        document.body.style.overflow = 'hidden';
        closeBtn.focus();
      }}

      function closeModal() {{
        overlay.classList.remove('open');
        document.body.style.overflow = '';
      }}

      document.querySelectorAll('.card').forEach(function (card) {{
        card.addEventListener('click', function () {{ openModal(card); }});
        card.addEventListener('keydown', function (e) {{
          if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); openModal(card); }}
        }});
      }});

      closeBtn.addEventListener('click', closeModal);
      overlay.addEventListener('click', function (e) {{
        if (e.target === overlay) closeModal();
      }});
      document.addEventListener('keydown', function (e) {{
        if (e.key === 'Escape') closeModal();
      }});
    }})();

    /* ---- Language toggle ---- */
    function setLang(lang) {{
      document.documentElement.setAttribute('data-lang', lang);
      document.querySelectorAll('.lang-btn').forEach(function (btn) {{
        btn.classList.toggle('active', btn.dataset.lang === lang);
      }});
      try {{ localStorage.setItem('newsLang', lang); }} catch (e) {{}}
    }}
    (function () {{
      var saved = '';
      try {{ saved = localStorage.getItem('newsLang') || ''; }} catch (e) {{}}
      setLang(saved === 'zh' ? 'zh' : 'en');
    }})();
  </script>
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
<div class="card" tabindex="0"
  data-title="{title}"
  data-summary="{summary}"
  data-published="{published}"
  data-link="{link}"
  data-image="{image}"
  data-source="{source}"
  data-source-url="{source_url}">
  {thumb_block}
  <div class="card-body">
    <span class="headline">{title}</span>
    {summary_block}
    <div class="card-footer">
      <span class="pub-date">{published}</span>
      <span class="source-badge">{source}</span>
    </div>
    <span class="read-more">Tap to read more →</span>
  </div>
</div>
"""


def _slugify(text: str) -> str:
    """Create a simple URL-safe anchor id from a source name."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _model_badge_class(model_name: str) -> str:
    """Return a CSS badge class for a given AI model name."""
    name = model_name.lower()
    if "openai" in name:
        return "badge-openai"
    if "gemini" in name:
        return "badge-gemini"
    if "claude" in name:
        return "badge-claude"
    if "glm" in name:
        return "badge-glm"
    if "deepseek" in name:
        return "badge-deepseek"
    if "qwen" in name:
        return "badge-qwen"
    return "badge-default"


def _build_editorial_html(editorial: dict, lang: str) -> str:
    """Build HTML for one language version of the AI Editorial."""
    content = editorial.get("content", "").strip()
    model   = editorial.get("model", "AI")
    topic   = editorial.get("topic_title", "")
    topic_url = editorial.get("topic_url", "")

    if not content:
        return (
            f'<div class="{lang}-content">'
            '<p class="ai-empty">Editorial not yet generated.</p>'
            "</div>"
        )

    if topic:
        label = "基於以下新聞" if lang == "zh" else "Based on"
        if topic_url:
            topic_link = (
                f'<a href="{html.escape(topic_url)}" target="_blank" rel="noopener" '
                f'class="editorial-topic-link">{html.escape(topic)}</a>'
            )
        else:
            topic_link = html.escape(topic)
        topic_html = f'<p class="editorial-topic">{label}: {topic_link}</p>'
    else:
        topic_html = ""

    return (
        f'<div class="{lang}-content">'
        f"{topic_html}"
        f'<div class="editorial-body">{html.escape(content)}</div>'
        f'<p class="editorial-attribution">— {html.escape(model)}</p>'
        f"</div>"
    )


def _build_arena_html(arena: dict, lang: str) -> str:
    """Build HTML for one language version of the AI Arena."""
    messages      = arena.get("messages", [])
    topic_title   = arena.get("topic_title", "")
    topic_url     = arena.get("topic_url", "")
    topic_summary = arena.get("topic_summary", "")

    # Filter out messages from AIs that did not respond
    messages = [
        m for m in messages
        if m.get("content", "").strip()
        and m.get("content", "").strip() != _no_response_text(m.get("name", ""))
    ]

    if not messages:
        return (
            f'<div class="{lang}-content">'
            '<p class="ai-empty">Arena not yet generated.</p>'
            "</div>"
        )

    topic_label = "今日話題" if lang == "zh" else "Today's Topic"
    if topic_url:
        topic_title_html = (
            f'<a href="{html.escape(topic_url)}" target="_blank" rel="noopener" '
            f'class="arena-topic-link">{html.escape(topic_title)}</a>'
        )
    else:
        topic_title_html = html.escape(topic_title)
    topic_html = (
        f'<div class="arena-topic">'
        f"<strong>{topic_label}:</strong> {topic_title_html}"
        + (
            f"<br><small>{html.escape(topic_summary[:200])}{'…' if len(topic_summary) > 200 else ''}</small>"
            if topic_summary else ""
        )
        + "</div>"
    )

    msgs_html = ""
    for msg in messages:
        name    = msg.get("name", "AI")
        model   = msg.get("model", "")
        content = msg.get("content", "").strip()
        badge_cls = _model_badge_class(model)
        msgs_html += (
            f'<div class="arena-msg">'
            f'<div class="arena-msg-header">'
            f'<span class="arena-model-badge {badge_cls}">{html.escape(name)}</span>'
            f"</div>"
            f'<div class="arena-msg-body">{html.escape(content)}</div>'
            f"</div>"
        )

    return (
        f'<div class="{lang}-content">'
        f"{topic_html}"
        f'<div class="arena-messages">{msgs_html}</div>'
        f"</div>"
    )


def build_ai_sections_html(ai_content: dict) -> str:
    """
    Build HTML for the AI Editorial and AI Arena sections.

    Both sections contain English and Cantonese versions; the active language
    is controlled by the ``data-lang`` attribute on ``<html>`` via JavaScript.
    """
    if not ai_content:
        return ""

    editorial_data = ai_content.get("editorial", {})
    arena_data     = ai_content.get("arena", {})
    generated_at   = ai_content.get("generated_at", "")

    gen_note = ""
    if generated_at:
        try:
            dt = datetime.fromisoformat(generated_at)
            gen_note = dt.strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            gen_note = generated_at

    # --- Editorial section ---
    editorial_en = _build_editorial_html(editorial_data.get("en", {}), "en")
    editorial_zh = _build_editorial_html(editorial_data.get("zh", {}), "zh")

    editorial_section = (
        '<div class="ai-section" id="ai-editorial">'
        '<div class="ai-section-header">'
        '<h2 class="ai-section-title">'
        '<span class="en-content">✍ AI Editorial</span>'
        '<span class="zh-content">✍ AI社評</span>'
        '</h2>'
        '<span class="ai-badge">AI</span>'
        + (f'<span style="font-size:.72rem;color:#b0a090;font-style:italic;font-family:sans-serif;margin-left:auto">{html.escape(gen_note)}</span>' if gen_note else "")
        + "</div>"
        + editorial_en
        + editorial_zh
        + "</div>"
    )

    # --- Arena section ---
    arena_en = _build_arena_html(arena_data.get("en", {}), "en")
    arena_zh = _build_arena_html(arena_data.get("zh", {}), "zh")

    arena_section = (
        '<div class="ai-section" id="ai-arena">'
        '<div class="ai-section-header">'
        '<h2 class="ai-section-title">'
        '<span class="en-content">🎙 News Arena</span>'
        '<span class="zh-content">🎙 新聞擂台</span>'
        '</h2>'
        '<span class="ai-badge">AI</span>'
        "</div>"
        + arena_en
        + arena_zh
        + "</div>"
    )

    return editorial_section + arena_section


def build_html(articles: list[dict]) -> str:
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    # Load AI-generated content (editorial + arena)
    ai_content = load_ai_content()
    ai_sections_html = build_ai_sections_html(ai_content)

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
            ai_sections=ai_sections_html,
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
            snippet = item.get("summary", "")
            if snippet:
                # Show a 3-line clipped preview on the card; full text goes into modal
                summary_block = f'<p class="summary">{html.escape(snippet[:300])}{"…" if len(snippet) > 300 else ""}</p>'
            image_url = item.get("image", "")
            thumb_block = ""
            if image_url:
                thumb_block = f'<img class="card-thumb" src="{html.escape(image_url, quote=True)}" alt="" loading="lazy" onerror="this.style.display=\'none\'">'
            cards_html += CARD_TEMPLATE.format(
                link=html.escape(item["link"], quote=True),
                title=html.escape(item["title"]),
                summary=html.escape(item.get("summary", ""), quote=True),
                summary_block=summary_block,
                published=html.escape(item["published"]),
                image=html.escape(image_url, quote=True),
                source_url=html.escape(source_url, quote=True),
                source=html.escape(source),
                thumb_block=thumb_block,
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
        ai_sections=ai_sections_html,
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
