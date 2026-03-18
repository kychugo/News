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


def _extract_image(entry) -> str:
    """Extract the first image URL from an RSS/Atom feed entry."""
    # media:thumbnail (preferred – usually a pre-sized thumbnail)
    thumbs = getattr(entry, "media_thumbnail", None)
    if thumbs and isinstance(thumbs, list) and thumbs:
        url = thumbs[0].get("url", "")
        if url:
            return url
    # media:content (images embedded as media)
    media = getattr(entry, "media_content", None)
    if media and isinstance(media, list):
        for mc in media:
            if mc.get("medium") == "image" or mc.get("type", "").startswith("image/"):
                url = mc.get("url", "")
                if url:
                    return url
        if media[0].get("url"):
            return media[0]["url"]
    # Enclosures (sometimes used for images)
    enclosures = getattr(entry, "enclosures", None)
    if enclosures and isinstance(enclosures, list):
        for enc in enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("href", enc.get("url", ""))
    # Parse <img> from HTML content or summary
    for html_src in [
        (getattr(entry, "content", None) or [{}])[0].get("value", ""),
        entry.get("summary", ""),
    ]:
        if html_src:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_src, re.IGNORECASE)
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
                "summary": content[:500] + ("…" if len(content) > 500 else ""),
                "published": entry.get("published", ""),
                "source": feed_info["name"],
                "source_url": feed_info["source_url"],
                "lang": feed_info["lang"],
                "image": _extract_image(entry),
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
                        item.get("imageUrl") or item.get("image") or item.get("thumbnail")
                        or item.get("coverImage") or item.get("thumbnailUrl") or ""
                    )
                    if isinstance(image, dict):
                        image = image.get("url", "")
                    articles.append(
                        {
                            "title": title.strip(),
                            "link": link,
                            "summary": summary[:500] + ("…" if len(summary) > 500 else ""),
                            "published": str(published),
                            "source": feed_info["name"],
                            "source_url": feed_info["source_url"],
                            "lang": feed_info["lang"],
                            "image": str(image) if image else "",
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
                    "image": "",
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
<html lang="zh-Hant">
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
      padding: 1.1rem 1.2rem 1rem;
      display: flex;
      flex-direction: column;
      transition: border-color .25s, box-shadow .25s;
      cursor: pointer;
    }}
    .card:hover {{
      border-color: #a0785a;
      box-shadow: 2px 3px 10px rgba(90,60,30,.10);
    }}
    .card:focus {{
      outline: 2px solid #a0785a;
      outline-offset: 2px;
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

    /* ---- Modal ---- */
    .modal-overlay {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(40,28,18,.7);
      z-index: 1000;
      overflow-y: auto;
      padding: 1.5rem 1rem 3rem;
    }}
    .modal-overlay.open {{ display: flex; align-items: flex-start; justify-content: center; }}
    .modal-panel {{
      background: #faf5ed;
      border: 1px solid #c9bfaf;
      border-radius: 3px;
      max-width: 700px;
      width: 100%;
      margin: auto;
      overflow: hidden;
      position: relative;
    }}
    .modal-close {{
      position: absolute;
      top: .75rem;
      right: .85rem;
      background: none;
      border: none;
      font-size: 1.5rem;
      color: #8a7060;
      cursor: pointer;
      line-height: 1;
      padding: .1rem .35rem;
      z-index: 10;
    }}
    .modal-close:hover {{ color: #3a3028; }}
    .modal-image {{
      width: 100%;
      max-height: 360px;
      object-fit: cover;
      display: block;
    }}
    .modal-body {{
      padding: 1.4rem 1.6rem 1.8rem;
    }}
    .modal-meta {{
      display: flex;
      gap: .8rem;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: .85rem;
      font-size: .74rem;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #8a7060;
    }}
    .modal-source-link {{
      color: #7b4f2e;
      text-decoration: none;
      border: 1px solid #c4a882;
      border-radius: 2px;
      padding: .1rem .4rem;
      transition: background .2s;
    }}
    .modal-source-link:hover {{ background: #ede0cf; }}
    .modal-title {{
      font-size: 1.25rem;
      font-weight: bold;
      color: #3a3028;
      line-height: 1.45;
      margin: 0 0 1rem;
    }}
    .modal-summary {{
      font-size: .9rem;
      color: #5a4838;
      line-height: 1.8;
      white-space: pre-wrap;
      margin: 0 0 1.4rem;
      font-family: Georgia, "Times New Roman", serif;
    }}
    .modal-read-more {{
      display: inline-block;
      padding: .45rem 1.2rem;
      background: #5c4033;
      color: #faf5ed;
      text-decoration: none;
      font-size: .82rem;
      border-radius: 2px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: .02em;
      transition: background .2s;
    }}
    .modal-read-more:hover {{ background: #3a2820; }}
    @media (max-width: 480px) {{
      .modal-body {{ padding: 1rem 1.1rem 1.4rem; }}
      .modal-title {{ font-size: 1.05rem; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>🇭🇰 Hong Kong News &ensp;香港新聞</h1>
    <p class="sub">Last updated: {updated} UTC &mdash; refreshes every hour</p>
    <span class="stats">📰 {total} articles &thinsp;&middot;&thinsp; {src_count} sources</span>
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
    <a href="https://www.bbc.com/news/topics/cp7r8vglne2t" target="_blank" rel="noopener">BBC News HK</a>,
    <a href="https://news.google.com/home?hl=en-US&gl=US&ceid=US:en" target="_blank" rel="noopener">Google News (US)</a>
  </footer>

  <!-- Article detail modal -->
  <div class="modal-overlay" id="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="modal-title">
    <div class="modal-panel">
      <button class="modal-close" id="modal-close" aria-label="Close article">&times;</button>
      <img class="modal-image" id="modal-img" src="" alt="" style="display:none" />
      <div class="modal-body">
        <div class="modal-meta">
          <span id="modal-date"></span>
          <a class="modal-source-link" id="modal-source-link" href="#" target="_blank" rel="noopener noreferrer"></a>
        </div>
        <h2 class="modal-title" id="modal-title"></h2>
        <p class="modal-summary" id="modal-summary"></p>
        <a class="modal-read-more" id="modal-read-more" href="#" target="_blank" rel="noopener noreferrer">Read full article ↗</a>
      </div>
    </div>
  </div>

  <script type="application/json" id="news-data">{news_data}</script>
  <script>
  (function () {{
    var overlay = document.getElementById('modal-overlay');
    var NEWS_DATA = JSON.parse(document.getElementById('news-data').textContent);

    /* Open modal when a card is clicked */
    document.querySelectorAll('.card').forEach(function (card) {{
      card.addEventListener('click', function () {{
        openArticle(parseInt(this.dataset.idx, 10));
      }});
      card.addEventListener('keydown', function (e) {{
        if (e.key === 'Enter' || e.key === ' ') {{
          e.preventDefault();
          openArticle(parseInt(this.dataset.idx, 10));
        }}
      }});
    }});

    /* Close on backdrop click */
    overlay.addEventListener('click', function (e) {{
      if (e.target === overlay) closeModal();
    }});

    /* Close button */
    document.getElementById('modal-close').addEventListener('click', closeModal);

    /* Close on Escape */
    document.addEventListener('keydown', function (e) {{
      if (e.key === 'Escape') closeModal();
    }});

    function openArticle(idx) {{
      var a = NEWS_DATA[idx];
      if (!a) return;

      /* Only allow http/https URLs to prevent javascript: injection */
      function safeUrl(url) {{
        return (url && (url.indexOf('http://') === 0 || url.indexOf('https://') === 0)) ? url : '#';
      }}

      /* Image */
      var imgEl = document.getElementById('modal-img');
      var imgUrl = safeUrl(a.image);
      if (imgUrl !== '#') {{
        imgEl.src = imgUrl;
        imgEl.alt = a.title;
        imgEl.style.display = 'block';
      }} else {{
        imgEl.src = '';
        imgEl.style.display = 'none';
      }}

      /* Text content */
      document.getElementById('modal-title').textContent = a.title;
      document.getElementById('modal-date').textContent = a.published;
      document.getElementById('modal-summary').textContent = a.summary;

      /* Source link */
      var srcLink = document.getElementById('modal-source-link');
      srcLink.href = safeUrl(a.source_url);
      srcLink.textContent = '\u2197 ' + a.source;

      /* Read-more link */
      document.getElementById('modal-read-more').href = safeUrl(a.link);

      overlay.classList.add('open');
      document.body.style.overflow = 'hidden';
    }}

    function closeModal() {{
      overlay.classList.remove('open');
      document.body.style.overflow = '';
    }}
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
<div class="card" role="button" tabindex="0" data-idx="{idx}">
  <span class="headline">{title}</span>
  {summary_block}
  <div class="card-footer">
    <span class="pub-date">{published}</span>
    <span class="source-badge">{source}</span>
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
            news_data="[]",
        )

    nav_items_html = ""
    sections_html = ""
    news_data_list: list[dict] = []
    article_idx = 0

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
                idx=article_idx,
                title=html.escape(item["title"]),
                summary_block=summary_block,
                published=html.escape(item["published"]),
                source=html.escape(source),
            )
            news_data_list.append({
                "title": item["title"],
                "summary": item["summary"],
                "link": item["link"],
                "published": item["published"],
                "source": item["source"],
                "source_url": item["source_url"],
                "image": item.get("image", ""),
            })
            article_idx += 1

        sections_html += SECTION_TEMPLATE.format(
            anchor=anchor,
            source=html.escape(source),
            source_url=html.escape(source_url, quote=True),
            count=len(items),
            cards=cards_html,
        )

    # Embed article data as JSON; escape </ to prevent script tag injection
    news_data_json = json.dumps(news_data_list, ensure_ascii=False).replace("</", "<\\/")

    return HTML_TEMPLATE.format(
        updated=updated,
        total=len(articles),
        src_count=len(sources),
        nav_items=nav_items_html,
        sections=sections_html,
        news_data=news_data_json,
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
