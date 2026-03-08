"""
fetch_news.py
Fetches the latest Hong Kong news from public RSS feeds and generates
docs/index.html for GitHub Pages.
"""

import os
import re
import html
import feedparser
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# News sources – all public RSS feeds, no API key required
# ---------------------------------------------------------------------------
NEWS_FEEDS = [
    {
        "name": "RTHK (English)",
        "url": "https://rthk9.rthk.hk/rthk/news/rss/e_expressnews_e_conciseinenglish.xml",
        "lang": "en",
    },
    {
        "name": "RTHK (中文)",
        "url": "https://rthk9.rthk.hk/rthk/news/rss/c_expressnews_cutnews.xml",
        "lang": "zh",
    },
    {
        "name": "HK Free Press",
        "url": "https://www.hongkongfp.com/feed/",
        "lang": "en",
    },
]

MAX_ITEMS_PER_FEED = 15  # articles to show per source


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def fetch_all_news() -> list[dict]:
    """Return a combined list of article dicts from all feeds."""
    articles: list[dict] = []
    for feed_info in NEWS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
                summary = entry.get("summary", entry.get("description", ""))
                # Strip embedded HTML tags from summary for safety
                summary = re.sub(r"<[^>]+>", "", summary).strip()

                articles.append(
                    {
                        "title": entry.get("title", "").strip(),
                        "link": entry.get("link", ""),
                        "summary": summary[:300] + ("…" if len(summary) > 300 else ""),
                        "published": entry.get("published", ""),
                        "source": feed_info["name"],
                        "lang": feed_info["lang"],
                    }
                )
            print(f"  ✓ {feed_info['name']}: {len(feed.entries[:MAX_ITEMS_PER_FEED])} articles")
        except Exception as exc:
            print(f"  ✗ {feed_info['name']}: {exc}")
    return articles


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="refresh" content="3600" />
  <title>Hong Kong News</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #f0f2f5;
      color: #1a1a2e;
    }}
    header {{
      background: linear-gradient(135deg, #c0392b 0%, #922b21 100%);
      color: #fff;
      padding: 1.5rem 1rem;
      text-align: center;
      box-shadow: 0 2px 6px rgba(0,0,0,.3);
    }}
    header h1 {{ margin: 0 0 .25rem; font-size: 2rem; letter-spacing: .5px; }}
    header p  {{ margin: 0; font-size: .9rem; opacity: .85; }}
    main {{
      max-width: 960px;
      margin: 2rem auto;
      padding: 0 1rem;
    }}
    .source-section {{ margin-bottom: 2.5rem; }}
    .source-title {{
      font-size: 1.25rem;
      font-weight: 700;
      border-left: 4px solid #c0392b;
      padding-left: .6rem;
      margin-bottom: 1rem;
      color: #922b21;
    }}
    .cards {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }}
    .card {{
      background: #fff;
      border-radius: 10px;
      padding: 1rem 1.2rem;
      box-shadow: 0 1px 4px rgba(0,0,0,.12);
      display: flex;
      flex-direction: column;
      transition: box-shadow .2s;
    }}
    .card:hover {{ box-shadow: 0 4px 14px rgba(0,0,0,.18); }}
    .card a {{
      text-decoration: none;
      color: #1a1a2e;
      font-size: 1rem;
      font-weight: 600;
      line-height: 1.4;
      flex: 1;
    }}
    .card a:hover {{ color: #c0392b; }}
    .card .summary {{
      margin-top: .5rem;
      font-size: .85rem;
      color: #555;
      line-height: 1.5;
    }}
    .card .meta {{
      margin-top: .75rem;
      font-size: .75rem;
      color: #999;
    }}
    footer {{
      text-align: center;
      padding: 1.5rem;
      font-size: .8rem;
      color: #888;
    }}
  </style>
</head>
<body>
  <header>
    <h1>🇭🇰 Hong Kong News</h1>
    <p>Last updated: {updated} (UTC) &mdash; auto-refreshes every hour</p>
  </header>
  <main>
    {sections}
  </main>
  <footer>
    Powered by GitHub Actions &amp; public RSS feeds &mdash;
    RTHK, HK Free Press
  </footer>
</body>
</html>
"""

SECTION_TEMPLATE = """\
<div class="source-section">
  <div class="source-title">{source}</div>
  <div class="cards">
    {cards}
  </div>
</div>
"""

CARD_TEMPLATE = """\
<div class="card">
  <a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>
  {summary_block}
  <div class="meta">{published}</div>
</div>
"""


def build_html(articles: list[dict]) -> str:
    # Group by source, preserving insertion order
    sources: dict[str, list[dict]] = {}
    for article in articles:
        sources.setdefault(article["source"], []).append(article)

    if not sources:
        sections_html = (
            '<p style="text-align:center;color:#888;margin-top:3rem;">'
            "No news articles could be fetched. Please check back later.</p>"
        )
        updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        return HTML_TEMPLATE.format(updated=updated, sections=sections_html)

    sections_html = ""
    for source, items in sources.items():
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
            )
        sections_html += SECTION_TEMPLATE.format(
            source=html.escape(source),
            cards=cards_html,
        )

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return HTML_TEMPLATE.format(updated=updated, sections=sections_html)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    print("Fetching Hong Kong news…")
    articles = fetch_all_news()
    print(f"Total articles fetched: {len(articles)}")

    out_path = os.path.join(os.path.dirname(__file__), "docs", "index.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    page = build_html(articles)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"HTML written to {out_path}")


if __name__ == "__main__":
    main()
