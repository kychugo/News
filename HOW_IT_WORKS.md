# 🔧 How the Hong Kong News Aggregator Works

This document explains the theory, architecture, and data flow of the aggregator in detail.
For a quick overview see [README.md](README.md).

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Step-by-Step Data Flow](#2-step-by-step-data-flow)
3. [Fetching News Articles](#3-fetching-news-articles)
   - [RSS / Atom Feeds](#31-rss--atom-feeds)
   - [Web Scraping (TVB News)](#32-web-scraping-tvb-news)
   - [Fallback URL Strategy](#33-fallback-url-strategy)
4. [Article Caching & Merging](#4-article-caching--merging)
5. [HTML Generation](#5-html-generation)
6. [GitHub Actions Workflow](#6-github-actions-workflow)
7. [Why Some Providers Return 0 Articles](#7-why-some-providers-return-0-articles)
8. [Article Data Schema](#8-article-data-schema)

---

## 1. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                  GitHub Actions (every hour)                       │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                     fetch_news.py                           │   │
│  │                                                             │   │
│  │  ┌────────────┐    ┌────────────┐    ┌──────────────────┐  │   │
│  │  │ fetch_rss()│    │fetch_tvb() │    │load_cached_      │  │   │
│  │  │ (×8 feeds) │    │ (×1 feed) │    │articles()        │  │   │
│  │  └─────┬──────┘    └─────┬──────┘    └────────┬─────────┘  │   │
│  │        │                 │                     │            │   │
│  │        └────────┬────────┘                     │            │   │
│  │                 ▼                              │            │   │
│  │         fresh_articles[]                       │            │   │
│  │                 │                              │            │   │
│  │                 └──────────┬───────────────────┘            │   │
│  │                            ▼                                │   │
│  │                   merge_articles()                          │   │
│  │                      (deduplicate,                          │   │
│  │                       drop >3 days)                         │   │
│  │                            │                                │   │
│  │                 ┌──────────┴──────────┐                     │   │
│  │                 ▼                     ▼                     │   │
│  │          save_articles()         build_html()               │   │
│  │         docs/news.json         docs/index.html              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  git commit & push docs/                                           │
│                        │                                           │
└────────────────────────┼───────────────────────────────────────────┘
                         ▼
              GitHub Pages → https://kychugo.github.io/News/
```

---

## 2. Step-by-Step Data Flow

| Step | What Happens |
|------|-------------|
| **1. Trigger** | GitHub Actions starts the `fetch-and-publish` job on a `cron: '0 * * * *'` schedule (every hour on the hour, UTC) or manually via `workflow_dispatch`. |
| **2. Install deps** | `pip install -r requirements.txt` installs `feedparser`, `requests`, and `beautifulsoup4`. |
| **3. Fetch** | `fetch_news.py` iterates over every entry in `NEWS_FEEDS` and calls the appropriate fetcher function. |
| **4. Merge** | Fresh articles are merged with the rolling cache from `docs/news.json`, deduplicating by URL and dropping articles older than 3 days. |
| **5. Render** | `build_html()` groups the merged articles by source and produces a self-contained responsive HTML page. |
| **6. Persist** | `docs/news.json` (cache) and `docs/index.html` (page) are written to disk. |
| **7. Publish** | GitHub Actions commits and pushes both files; a second workflow step deploys `docs/` to GitHub Pages. |

---

## 3. Fetching News Articles

### 3.1 RSS / Atom Feeds

Most providers publish a standard RSS 2.0 or Atom feed.
The aggregator fetches it in two stages:

```
requests.get(feed_url, headers=SCRAPE_HEADERS)
            │
            ▼
   HTTP response (XML body)
            │
            ▼
feedparser.parse(response.content)
            │
            ▼
  feed.entries  →  list[dict]  (title, link, summary, published, …)
```

**Why use `requests` instead of calling `feedparser.parse(url)` directly?**

`feedparser` can fetch URLs by itself, but it sends its own minimal `User-Agent`
string (`python-feedparser/…`).  Several news servers (RTHK, The Standard, BBC)
actively filter out non-browser user agents and return an empty document or an
HTTP error.

By fetching the content ourselves with `requests` and passing the raw bytes to
`feedparser.parse()`, we can send a realistic browser-like `User-Agent` header:

```python
SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HKNewsBot/1.0; "
        "+https://github.com/kychugo/News)"
    )
}
```

This makes the aggregator appear like a normal browser to most servers.

### 3.2 Web Scraping (TVB News)

TVB News (`news.tvb.com/tc`) is a **Next.js** single-page application that does
not publish an RSS feed.  The aggregator extracts articles using two strategies,
tried in order:

#### Strategy 1 – `__NEXT_DATA__` JSON extraction (preferred)

Next.js embeds a full JSON snapshot of the page's initial data in a
`<script id="__NEXT_DATA__">` tag.  The aggregator:

1. Downloads the HTML page with `requests`.
2. Parses the HTML with `BeautifulSoup` and locates the `__NEXT_DATA__` tag.
3. Parses the embedded JSON (`json.loads`).
4. **Recursively walks** the entire JSON tree (max depth: 6) looking for lists
   of objects that contain a `title` or `headline` key – these are article lists.
5. Extracts `title`, `slug`/`url`, `description`, and `publishedAt` from each
   article object.
6. Converts relative slugs to full `https://news.tvb.com/tc/…` URLs.

```
HTML page
  └─ <script id="__NEXT_DATA__">{ … }</script>
                │
                ▼
       _find_article_lists(json_tree)
                │
                ▼
       article dicts  →  list[dict]
```

#### Strategy 2 – `<a>` tag fallback

If Strategy 1 returns no articles (e.g., the page structure changed), the
aggregator falls back to scanning every `<a href>` element in the page for
links that match the TVB article URL pattern:

```python
re.search(r"/tc/[\w-]+/[\w-]", href)
```

This is less precise (no summaries or dates) but ensures some articles are
always extracted even if the Next.js structure changes.

### 3.3 Fallback URL Strategy

Some RSS providers occasionally move their feed endpoints or return empty feeds
from one URL but not another.  Each feed entry in `NEWS_FEEDS` can specify a
list of `fallback_urls`:

```python
{
    "name": "RTHK (English)",
    "url": "https://rthk9.rthk.hk/rthk/news/rss/e_expressnews_elocal.xml",
    "fallback_urls": [
        "https://rthk9.rthk.hk/rthk/news/rss/e_expressnews_eworldnews.xml",
        "https://rthk9.rthk.hk/rthk/news/rss/e_expressnews_e_conciseinenglish.xml",
    ],
    …
}
```

`fetch_rss()` tries each URL in order and stops as soon as one returns at least
one article:

```
Try primary URL
    │ HTTP error or 0 articles?
    ▼ yes
Try fallback_urls[0]
    │ HTTP error or 0 articles?
    ▼ yes
Try fallback_urls[1]
    │ …
    ▼
Return articles (or raise last exception)
```

---

## 4. Article Caching & Merging

Because some providers are occasionally unavailable, the aggregator maintains a
rolling 3-day cache of all previously fetched articles in `docs/news.json`.

**`merge_articles(cached, fresh)` rules:**

```
fresh_links = {a.link for a in fresh}

for each article in cached:
    if article.link in fresh_links → skip  (fresh version takes precedence)
    if article.published < now - 3 days → skip  (too old)
    otherwise → keep

result = fresh + kept_cached
```

This guarantees:
- **Freshness:** New articles always appear at the top of the page.
- **Continuity:** If a provider is temporarily down, its recent articles are
  still shown from the cache.
- **No stale data:** Articles older than 3 days are automatically evicted.

```
         fresh[]               cached[]
            │                     │
            ▼                     ▼
    ┌───────────────────────────────────────┐
    │           merge_articles()            │
    │  1. index fresh by link               │
    │  2. filter cached (not in fresh,      │
    │     not older than 3 days)            │
    │  3. return fresh + filtered_cached    │
    └───────────────────────────────────────┘
                       │
                       ▼
              merged articles[]
```

---

## 5. HTML Generation

`build_html(articles)` produces a **self-contained, single-file HTML page**.
No external JavaScript or CSS frameworks are used – everything is inline.

**Steps:**

1. Group articles by `source` name (preserving the `NEWS_FEEDS` insertion order
   inherited from `fetch_all_news`).
2. Build a sticky navigation bar with one anchor link per source.
3. For each source, render a responsive CSS Grid of article cards.
4. Each card contains: headline link, summary, publication date, and source badge.
5. All user-supplied text is escaped with `html.escape()` to prevent XSS.
6. A `<meta http-equiv="refresh" content="3600">` tag makes the browser reload
   automatically after one hour (matching the update cadence).

---

## 6. GitHub Actions Workflow

### `fetch_news.yml` – Hourly fetch & publish

```
Trigger: cron '0 * * * *'   OR   workflow_dispatch
         │
         ▼
1. actions/checkout@v4
2. actions/setup-python@v5  (Python 3.12)
3. pip install -r requirements.txt
4. python fetch_news.py
5. git add docs/ && git commit && git push    ← only if files changed
6. actions/configure-pages@v5
7. actions/upload-pages-artifact@v3          ← uploads docs/ directory
8. actions/deploy-pages@v4                  ← publishes to GitHub Pages
```

### `deploy.yml` – Manual / push-triggered deploy

A secondary workflow that re-deploys the GitHub Pages site whenever code is
pushed to `main` (useful for layout or CSS-only changes that don't require a
fresh news fetch).

---

## 7. Why Some Providers Return 0 Articles

The aggregator logs one of three states per provider every run:

| Symbol | Meaning |
|--------|---------|
| ✓ | Articles fetched successfully |
| ⚠ | Feed accessible but returned 0 articles |
| ✗ | Network error or HTTP error |

Common reasons a provider returns 0 or fails:

### User-Agent filtering
Servers check the `User-Agent` HTTP header.  `feedparser`'s built-in fetcher
sends `python-feedparser/6.x`, which many servers recognize as a bot and block.
**Fix applied:** the aggregator now fetches all RSS feeds via `requests` with a
browser-like User-Agent before passing the content to `feedparser`.

### Cloudflare Bot Protection
The Standard and some other providers sit behind Cloudflare, which can issue a
JavaScript challenge page (HTTP 200 but HTML, not XML).  `feedparser` will
parse this HTML and find 0 entries.  The aggregator detects the empty result and
tries any configured fallback URLs.

### Subscription Paywalls
**Coconuts Hong Kong** was removed from the source list because its RSS feed
requires an active subscription and consistently returns 0 articles for
unauthenticated requests.  It has been replaced by **The Guardian (Hong Kong)**,
which provides a freely accessible RSS feed covering HK.

### Geo-restrictions
Some RTHK RSS endpoints return empty feeds for requests originating outside
Hong Kong.  Multiple fallback RTHK URLs are configured so that at least one
endpoint is likely to work from GitHub's US-based runners.

### Feed URL changes
Publishers occasionally rename or relocate their RSS feeds without redirects.
Keeping `fallback_urls` in the configuration makes the aggregator resilient to
such changes.

### Temporary outages
Any server can be temporarily unavailable.  The 3-day rolling article cache
ensures the page is never empty even when all live fetches fail.

---

## 8. Article Data Schema

Each article is stored as a JSON object with the following fields:

```json
{
  "title":      "Article headline text",
  "link":       "https://full-url-to-article",
  "summary":    "First 300 characters of article body (HTML stripped)…",
  "published":  "Sun, 08 Mar 2026 10:00:00 +0000",
  "source":     "HK Free Press",
  "source_url": "https://www.hongkongfp.com/",
  "lang":       "en"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `title` | string | Article headline; HTML-escaped when rendered |
| `link` | string | Full absolute URL to the original article |
| `summary` | string | Plain text, max 300 chars; empty string if unavailable |
| `published` | string | Date string from the RSS feed; multiple formats supported |
| `source` | string | Human-readable provider name |
| `source_url` | string | Homepage of the news provider |
| `lang` | string | `"en"` (English) or `"zh"` (Traditional Chinese) |
