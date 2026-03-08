# 🇭🇰 Hong Kong News Aggregator 香港新聞聚合

[![Fetch HK News](https://github.com/kychugo/News/actions/workflows/fetch_news.yml/badge.svg)](https://github.com/kychugo/News/actions/workflows/fetch_news.yml)
[![GitHub Pages](https://img.shields.io/badge/Live%20Site-GitHub%20Pages-brightgreen)](https://kychugo.github.io/News/)

A lightweight, automated Hong Kong news aggregator that pulls headlines from multiple sources and publishes them as a static website updated every hour.

## 🌐 Live Website

**[https://kychugo.github.io/News/](https://kychugo.github.io/News/)**

## 📰 News Sources

| Provider | Language | Feed Type | URL |
|---|---|---|---|
| **RTHK** (Radio Television Hong Kong) | English | RSS | [news.rthk.hk/rthk/en](https://news.rthk.hk/rthk/en/) |
| **RTHK** (香港電台) | 中文 | RSS | [news.rthk.hk/rthk/ch](https://news.rthk.hk/rthk/ch/) |
| **HK Free Press** | English | RSS | [hongkongfp.com](https://www.hongkongfp.com/) |
| **The Standard** | English | RSS | [thestandard.com.hk](https://www.thestandard.com.hk/) |
| **Asia Times** | English | RSS | [asiatimes.com](https://asiatimes.com/) |
| **The Guardian** (Hong Kong) | English | RSS | [theguardian.com/world/hong-kong](https://www.theguardian.com/world/hong-kong) |
| **TVB News** (無綫新聞) | 中文 | Web scrape | [news.tvb.com/tc](https://news.tvb.com/tc) |
| **South China Morning Post** | English | RSS | [scmp.com](https://www.scmp.com/) |
| **BBC News** (Asia) | English | RSS | [bbc.com/news/world/asia](https://www.bbc.com/news/world/asia) |

> **Note on provider reliability:** Some providers use Cloudflare protection, geo-restrictions, or
> subscription paywalls that can temporarily block automated fetching. The aggregator handles this
> gracefully – if a source fails or returns an empty feed, previously cached articles for that
> source are served instead. See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for the full explanation.

## ⚙️ How It Works

1. A [GitHub Actions](.github/workflows/fetch_news.yml) workflow runs **every hour**.
2. `fetch_news.py` fetches the latest articles via **RSS feeds** (most sources) and **web scraping** (TVB News).
3. Fresh articles are merged with a 3-day rolling cache stored in `docs/news.json`.
4. The articles are rendered into a responsive HTML page saved to `docs/index.html`.
5. The page is automatically deployed to **GitHub Pages**.

For a detailed technical explanation of each step, see [HOW_IT_WORKS.md](HOW_IT_WORKS.md).

## 🛠️ Tech Stack

| Tool | Purpose |
|---|---|
| **Python 3.12** | Core scripting language |
| **feedparser** | RSS / Atom feed parsing |
| **requests** | HTTP fetching with proper browser headers |
| **BeautifulSoup4** | HTML parsing for TVB News scraping |
| **GitHub Actions** | Scheduled automation & CI/CD |
| **GitHub Pages** | Static site hosting |

## 🚀 Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Fetch news and generate the HTML page
python fetch_news.py

# 3. Open the generated page
open docs/index.html       # macOS
xdg-open docs/index.html   # Linux
start docs/index.html      # Windows
```

The script prints a summary of each provider's status:

```
Fetching Hong Kong news…
  ✓ HK Free Press: 15 articles
  ✓ Asia Times: 15 articles
  ⚠ The Standard: 0 articles (feed may be empty or temporarily unavailable)
  ✗ TVB News (無綫新聞): <error details>
Total articles fetched: 45
```

## 🤔 Why Do Some Providers Return 0 Articles?

Several factors can cause a provider to return 0 articles:

| Cause | Affected Providers | Notes |
|---|---|---|
| **User-agent filtering** | RTHK, The Standard | Some servers reject feedparser's default UA; the aggregator uses a browser-like UA via `requests` |
| **Cloudflare protection** | The Standard | Anti-bot challenges can block automated requests |
| **Subscription paywall** | *(Coconuts HK – removed)* | Subscription-gated RSS replaced with The Guardian HK |
| **Geo-restrictions** | RTHK (sometimes) | Some RTHK RSS endpoints are restricted outside Hong Kong |
| **Feed URL changes** | Any | Publishers occasionally move their RSS endpoints; fallback URLs are configured for RTHK and BBC |
| **Temporary outage** | Any | The provider's server may be temporarily down |

The aggregator always falls back to the **3-day article cache** (`docs/news.json`) so the page never goes completely empty.

## 🗂️ Project Structure

```
News/
├── fetch_news.py          # Main script: fetch → merge → render
├── requirements.txt       # Python dependencies
├── docs/
│   ├── index.html         # Generated website (auto-updated hourly)
│   └── news.json          # Rolling 3-day article cache
├── .github/workflows/
│   ├── fetch_news.yml     # Hourly fetch + deploy workflow
│   └── deploy.yml         # GitHub Pages deployment workflow
├── README.md              # This file
└── HOW_IT_WORKS.md        # Detailed system architecture & theory
```

## 📄 License

This project is open source. News content belongs to the respective publishers.
