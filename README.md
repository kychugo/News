# 🇭🇰 Hong Kong & World News Aggregator 香港新聞聚合

A lightweight, automated news aggregator that pulls headlines from multiple sources and publishes them as a static website updated every hour. Articles are automatically removed after **3 days** to keep the feed fresh.

AI-powered features (editorial & multi-model news arena) are regenerated 4 times daily via [pollinations.ai](https://gen.pollinations.ai).

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

## 🤖 AI Features

### AI Editorial (社評)

An AI writes a balanced, insightful 3–4 paragraph editorial (in both English and Cantonese) about the most significant news theme of the day.

### AI News Arena (新聞擂台)

Six different AI models — OpenAI, Gemini, Claude, GLM, DeepSeek, and Qwen — debate the day's top story, each building on the previous responses. Available in both English and Cantonese.

Both features are generated **4 times daily** (00:00, 06:00, 12:00, 18:00 UTC) by the [AI Features workflow](.github/workflows/ai_features.yml) and powered by [pollinations.ai](https://gen.pollinations.ai).

## ⚙️ How It Works

1. A [GitHub Actions](.github/workflows/fetch_news.yml) workflow runs **every hour**.
2. `fetch_news.py` fetches the latest articles from all sources via **RSS feeds** (RTHK, HK Free Press, The Standard, Asia Times, Coconuts HK, SCMP, BBC, Google News) and **web scraping** (TVB News).
3. New articles are merged with cached articles from `docs/news.json`, deduplicating by URL.
4. Articles older than **3 days** are automatically removed from the cache.
5. All articles are rendered into a responsive HTML page saved to `docs/index.html`.
6. The page is automatically deployed to **GitHub Pages**.
7. A separate [AI Features workflow](.github/workflows/ai_features.yml) runs 4 times daily, generating AI editorial and arena content via `ai_features.py` and committing `docs/ai_content.json`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for a deeper explanation of the system design.

## 🛠️ Tech Stack

- **Python 3.12** – core language
- **feedparser** – RSS/Atom feed parsing
- **requests + BeautifulSoup4** – HTTP client with custom headers/timeout and web scraping
- **pollinations.ai** – AI text generation API (editorial & news arena)
- **GitHub Actions** – scheduled automation & CI/CD
- **GitHub Pages** – static site hosting

## 🔑 API Key Setup

The AI features use [pollinations.ai](https://gen.pollinations.ai), which requires an API key for authenticated (rate-limit-free) access.

### 1. Get a pollinations.ai API key

Visit **<https://enter.pollinations.ai>** and sign up to obtain a **Secret Key** (`sk_…`).  
See [APIDOCS.md](APIDOCS.md) for full API documentation.

### 2. Add the key as a Repository Secret

1. Go to your repository on GitHub.
2. Navigate to **Settings → Secrets and variables → Actions**.
3. Click **New repository secret**.
4. Set **Name** to `POLLINATIONS_API_KEY` and **Value** to your secret key.
5. Click **Add secret**.

The [AI Features workflow](.github/workflows/ai_features.yml) automatically reads `POLLINATIONS_API_KEY` and passes it to `ai_features.py` as the `Authorization: Bearer` header.

> **Note:** If no API key is set, the workflow will still run, but API calls may be rate-limited or blocked by pollinations.ai.

## 🚀 Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Fetch news and generate the HTML page
python fetch_news.py

# 3. (Optional) Generate AI editorial & arena content
#    Set your API key first:
export POLLINATIONS_API_KEY=sk_your_key_here
python ai_features.py

# 4. Regenerate HTML with AI content included
python fetch_news.py

# 5. Open the generated page
open docs/index.html   # macOS
xdg-open docs/index.html  # Linux
```

## 📄 License

This project is open source. News content belongs to the respective publishers.
