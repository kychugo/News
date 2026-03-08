# 🏗️ System Architecture & Theory

This document explains how the News Aggregator works under the hood.

---

## Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                       GitHub Actions (hourly)                    │
│                                                                  │
│  ┌─────────────┐    ┌──────────────────┐    ┌────────────────┐  │
│  │  RSS Feeds  │───▶│                  │    │  docs/         │  │
│  │  (9 sources)│    │  fetch_news.py   │───▶│  index.html    │  │
│  └─────────────┘    │                  │    │  news.json     │  │
│  ┌─────────────┐    │  • fetch         │    └────────┬───────┘  │
│  │  Web Scrape │───▶│  • merge/dedup   │             │          │
│  │  (TVB News) │    │  • age-filter    │             │          │
│  └─────────────┘    │  • render HTML   │             │          │
│                     └──────────────────┘             │          │
└──────────────────────────────────────────────────────┼──────────┘
                                                       │ git push
                                              ┌────────▼────────┐
                                              │  GitHub Pages   │
                                              │  (public site)  │
                                              └─────────────────┘
```

---

## Components

### 1. `fetch_news.py` — The Core Script

The main Python script runs all fetch, merge, and render logic.

#### Fetching

**RSS sources** — the majority of providers publish a standard RSS/Atom feed.
Each feed is downloaded using `requests` (which gives us timeout control and a
custom `User-Agent` header that many servers require), then parsed by
`feedparser`.  Using `requests` to download first avoids the common failure
mode where sites reject feedparser's default user-agent or the connection hangs
with no timeout.

**Scraped sources** (TVB News) — some sites do not publish an RSS feed, so the
script downloads the HTML page and extracts articles via:

1. **Strategy 1 – Next.js `__NEXT_DATA__` JSON**: Modern sites built with
   Next.js embed their page data as a JSON blob in a `<script id="__NEXT_DATA__">` tag.
   The script recursively walks this JSON tree to find any list that contains
   article-like objects (dicts with a `title` or `headline` key).
2. **Strategy 2 – `<a>` href pattern matching**: Falls back to scanning all
   anchor tags whose `href` matches a pattern typical for article URLs on that
   site (e.g. `/tc/topic/…`).

#### Merging & Deduplication

After fetching, fresh articles are merged with the previously persisted
articles loaded from `docs/news.json`:

- **Deduplication** is done by article URL (`link`).  If a fresh article has
  the same link as a cached one, the fresh version is used.
- **Age filtering**: any cached article whose publication date can be parsed
  and is older than `MAX_ARTICLE_AGE_DAYS` (currently **3 days**) is dropped.
  Articles without a parseable date are kept (we cannot age them safely).
- Fresh articles are listed first; surviving cached articles follow.

This rolling-window approach means the site always shows recent news (up to 3
days old) without re-fetching every article from scratch on each run.

#### HTML Rendering

The merged article list is grouped by source and rendered into a single
self-contained HTML file (`docs/index.html`) using Python string templates.
The page includes:

- A sticky top-navigation bar with links to each source section.
- Card-based article grid (responsive, CSS-only).
- A `<meta http-equiv="refresh" content="3600">` tag so browsers auto-reload
  every hour when left open.

### 2. `docs/news.json` — The Article Cache

A flat JSON array of article objects, each with:

| Field | Description |
|---|---|
| `title` | Article headline |
| `link` | Canonical URL (used as dedup key) |
| `summary` | Short excerpt (max 300 chars) |
| `published` | Publication date string (format varies by source) |
| `source` | Source display name |
| `source_url` | Source homepage URL |
| `lang` | Language code (`en` or `zh`) |

This file is committed to the repository by the GitHub Actions bot on every
run (only when articles changed), forming a lightweight persistent store
without needing any database.

### 3. `.github/workflows/fetch_news.yml` — The Scheduler

A GitHub Actions workflow with two triggers:

- **`schedule: cron: "0 * * * *"`** – runs at the top of every hour, 24/7.
- **`workflow_dispatch`** – allows manual runs from the GitHub Actions UI.

The job sequence is:

1. Check out the repository.
2. Install Python dependencies (`pip install -r requirements.txt`).
3. Run `fetch_news.py` to produce `docs/index.html` and `docs/news.json`.
4. Commit and push those two files if they changed (using the `github-actions[bot]` identity).
5. Deploy the `docs/` folder to GitHub Pages.

---

## Data Flow (step by step)

```
Every hour:
  1. GH Actions checks out repo  →  reads docs/news.json (cached articles)
  2. fetch_news.py downloads RSS feeds + scrapes TVB News
  3. Fresh + cached articles are merged and deduplicated by URL
  4. Articles older than 3 days are dropped
  5. Merged list is saved back to docs/news.json
  6. Merged list is rendered into docs/index.html
  7. Both files are git-committed and pushed
  8. GitHub Pages serves the updated docs/ folder publicly
```

---

## Why Some Providers May Fail

| Cause | Explanation |
|---|---|
| **Blocked user-agent** | Some servers reject requests from generic HTTP clients. The script sends a descriptive `User-Agent` header via `requests` to mitigate this. |
| **Site restructure** | Web-scraped sources (TVB) can break when the site changes its HTML or JavaScript structure. The two-strategy scraper handles Next.js layout changes, but may need updates if TVB rewrites the site. |
| **Paywalled RSS** | SCMP occasionally restricts their RSS feed to subscribers. The feed URL is kept in the config but may return an empty feed. |
| **Network timeout** | All HTTP requests use a 20-second timeout, so transient network issues cause a logged failure rather than hanging the job. |
| **Feed format changes** | RSS/Atom feeds sometimes change their schema. feedparser is lenient, but extreme changes may result in missing fields (title, link, date). |

Failed providers are logged with a `✗` prefix in the Actions run log. All other
sources continue to be fetched normally — one bad source never blocks the rest.

---

## Adding a New Source

1. Append an entry to the `NEWS_FEEDS` list in `fetch_news.py`:

   ```python
   {
       "name": "My Source",
       "url": "https://example.com/feed.xml",   # RSS/Atom URL
       "source_url": "https://example.com/",    # homepage shown on cards
       "type": "rss",                           # "rss" or "scrape"
       "lang": "en",                            # "en" or "zh"
   },
   ```

2. If the source has no RSS feed, set `"type": "scrape"` and implement a
   custom `fetch_<name>(feed_info)` function (following the pattern of
   `fetch_tvb`), then add a dispatch branch in `fetch_all_news()`.

3. Add the source link to the `<footer>` in `HTML_TEMPLATE`.

4. Update `README.md` to list the new source.
