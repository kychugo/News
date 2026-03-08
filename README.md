# 🇭🇰 Hong Kong & World News Aggregator 香港新聞聚合

A lightweight, automated news aggregator that pulls headlines from multiple sources and publishes them as a static website updated every hour. Articles are automatically removed after **3 days** to keep the feed fresh.

## 🌐 Live Website

**[https://kychugo.github.io/News/](https://kychugo.github.io/News/)**

## 📰 News Sources

| Provider | Language | Type | URL |
|---|---|---|---|
| **RTHK** (Radio Television Hong Kong) | English | RSS | [https://news.rthk.hk/rthk/en/](https://news.rthk.hk/rthk/en/) |
| **RTHK** (香港電台) | 中文 | RSS | [https://news.rthk.hk/rthk/ch/](https://news.rthk.hk/rthk/ch/) |
| **HK Free Press** | English | RSS | [https://www.hongkongfp.com/](https://www.hongkongfp.com/) |
| **The Standard** | English | RSS | [https://www.thestandard.com.hk/](https://www.thestandard.com.hk/) |
| **Asia Times** | English | RSS | [https://asiatimes.com/](https://asiatimes.com/) |
| **Coconuts Hong Kong** | English | RSS | [https://coconuts.co/hongkong/](https://coconuts.co/hongkong/) |
| **TVB News** (無綫新聞) | 中文 | Web scrape | [https://news.tvb.com/tc](https://news.tvb.com/tc) |
| **South China Morning Post** | English | RSS | [https://www.scmp.com/](https://www.scmp.com/) |
| **BBC News** (Hong Kong) | English | RSS | [https://www.bbc.com/news/topics/cp7r8vglne2t](https://www.bbc.com/news/topics/cp7r8vglne2t) |
| **Google News** (US) | English | RSS | [https://news.google.com/home?hl=en-US&gl=US&ceid=US:en](https://news.google.com/home?hl=en-US&gl=US&ceid=US:en) |

## ⚙️ How It Works

1. A [GitHub Actions](.github/workflows/fetch_news.yml) workflow runs **every hour**.
2. `fetch_news.py` fetches the latest articles from all sources via **RSS feeds** (RTHK, HK Free Press, The Standard, Asia Times, Coconuts HK, SCMP, BBC, Google News) and **web scraping** (TVB News).
3. New articles are merged with cached articles from `docs/news.json`, deduplicating by URL.
4. Articles older than **3 days** are automatically removed from the cache.
5. All articles are rendered into a responsive HTML page saved to `docs/index.html`.
6. The page is automatically deployed to **GitHub Pages**.

See [ARCHITECTURE.md](ARCHITECTURE.md) for a deeper explanation of the system design.

## 🛠️ Tech Stack

- **Python 3.12** – core language
- **feedparser** – RSS/Atom feed parsing
- **requests + BeautifulSoup4** – HTTP client with custom headers/timeout and web scraping
- **GitHub Actions** – scheduled automation & CI/CD
- **GitHub Pages** – static site hosting

## 🚀 Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Fetch news and generate the HTML page
python fetch_news.py

# 3. Open the generated page
open docs/index.html   # macOS
xdg-open docs/index.html  # Linux
```

## 📄 License

This project is open source. News content belongs to the respective publishers.
