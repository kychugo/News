# 🇭🇰 Hong Kong News Aggregator 香港新聞聚合

A lightweight, automated Hong Kong news aggregator that pulls headlines from multiple sources and publishes them as a static website updated every hour.

## 🌐 Live Website

**[https://kychugo.github.io/News/](https://kychugo.github.io/News/)**

## 📰 News Sources

| Provider | Language | URL |
|---|---|---|
| **RTHK** (Radio Television Hong Kong) | English | [https://news.rthk.hk/rthk/en/](https://news.rthk.hk/rthk/en/) |
| **RTHK** (香港電台) | 中文 | [https://news.rthk.hk/rthk/ch/](https://news.rthk.hk/rthk/ch/) |
| **HK Free Press** | English | [https://www.hongkongfp.com/](https://www.hongkongfp.com/) |
| **The Standard** | English | [https://www.thestandard.com.hk/](https://www.thestandard.com.hk/) |
| **Asia Times** | English | [https://asiatimes.com/](https://asiatimes.com/) |
| **Coconuts Hong Kong** | English | [https://coconuts.co/hongkong/](https://coconuts.co/hongkong/) |
| **TVB News** (無綫新聞) | 中文 | [https://news.tvb.com/tc](https://news.tvb.com/tc) |

## ⚙️ How It Works

1. A [GitHub Actions](.github/workflows/fetch_news.yml) workflow runs **every hour**.
2. `fetch_news.py` fetches the latest articles from RTHK (English & 中文), HK Free Press, The Standard, Asia Times, and Coconuts HK via **RSS feeds**, and from TVB News via **web scraping**.
3. The articles are rendered into a responsive HTML page saved to `docs/index.html`.
4. The page is automatically deployed to **GitHub Pages**.

## 🛠️ Tech Stack

- **Python 3.12** – core language
- **feedparser** – RSS/Atom feed parsing
- **requests + BeautifulSoup4** – web scraping
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