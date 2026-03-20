"""
ai_features.py
AI-powered features for the Hong Kong News page.

Features:
  1. AI Editorial (社評)  – one AI writes an editorial on the day's top news.
  2. AI News Arena (新聞擂台) – six different AI models debate the same topic,
     each responding to previous participants' remarks.

Both features are generated in English AND Cantonese so the user can toggle
the platform language in the browser.

API: pollinations.ai  (https://gen.pollinations.ai/v1/chat/completions)
See APIDOCS.md for full documentation.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AI_API_URL = "https://gen.pollinations.ai/v1/chat/completions"
AI_CONTENT_FILE = os.path.join(os.path.dirname(__file__), "docs", "ai_content.json")

AI_EDITORIAL_MODEL = "openai"

# Participants in the News Arena (新聞擂台)
ARENA_PARTICIPANTS = [
    {"model": "openai-fast",    "name": "OpenAI"},
    {"model": "gemini-search",  "name": "Gemini"},
    {"model": "claude-fast",    "name": "Claude"},
    {"model": "glm",            "name": "GLM"},
    {"model": "deepseek",       "name": "DeepSeek"},
    {"model": "qwen-character", "name": "Qwen"},
]

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
_EDITORIAL_SYSTEM_EN = (
    "You are a seasoned Hong Kong news editorial writer. "
    "Write a balanced, insightful editorial (social commentary) of 3-4 paragraphs "
    "about the most significant news theme of the day. "
    "Be thoughtful, nuanced, and analytical. Write in English."
)

_EDITORIAL_SYSTEM_ZH = (
    "你係一位資深嘅香港新聞社評作家。"
    "請就今日最重要嘅新聞主題撰寫一篇平衡、有深度嘅社評（3-4段落）。"
    "文章要有見解、有分析、有立場。請用廣東話書寫。"
)

_ARENA_SYSTEM_EN = (
    "You are an AI analyst taking part in a live news discussion panel called "
    "'News Arena'. You will read a topic and any prior responses from other AI "
    "systems, then add your own analytical perspective. "
    "Be engaging, direct, and willing to agree or push back on prior points. "
    "Keep your response to 2-3 focused paragraphs. Write in English."
)

_ARENA_SYSTEM_ZH = (
    "你係「新聞擂台」嘅一個AI分析員，正在進行即時新聞討論。"
    "你會閱讀話題同其他AI嘅發言，然後加入你自己嘅分析觀點。"
    "保持直接、有見地，可以同意或反駁前面嘅意見。"
    "你嘅回應保持2-3段落。請用廣東話書寫。"
)


# ---------------------------------------------------------------------------
# API wrapper
# ---------------------------------------------------------------------------
def call_ai(model: str, messages: list[dict], timeout: int = 90) -> str:
    """
    Call the pollinations.ai chat completions API.

    Returns the assistant's text content, or an empty string on failure.
    """
    payload = {"model": model, "messages": messages}
    try:
        resp = requests.post(AI_API_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return (content or "").strip()
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ AI call failed [{model}]: {exc}")
        return ""


# ---------------------------------------------------------------------------
# AI Editorial (社評)
# ---------------------------------------------------------------------------
def generate_editorial(articles: list[dict], lang: str = "en") -> dict:
    """
    Generate an AI-written editorial based on today's top news articles.

    Args:
        articles: List of article dicts (title, summary, source …).
        lang:     "en" for English, "zh" for Cantonese.

    Returns:
        Dict with keys: content, model, topic_title, generated_at.
    """
    if not articles:
        return {}

    system_msg = _EDITORIAL_SYSTEM_ZH if lang == "zh" else _EDITORIAL_SYSTEM_EN
    lang_note = "用廣東話" if lang == "zh" else "in English"

    # Build a news digest for the AI
    news_digest = "\n".join(
        f"- [{a['source']}] {a['title']}: {a.get('summary', '')[:200]}"
        for a in articles[:12]
    )

    user_msg = (
        f"Based on today's top Hong Kong news, write an editorial {lang_note}.\n\n"
        f"Today's headlines:\n{news_digest}\n\n"
        "Choose the most important theme and write a 3-4 paragraph editorial. "
        "Do not include a headline; start directly with the editorial prose."
    )

    print(f"  → Generating editorial [{lang}] with {AI_EDITORIAL_MODEL}…")
    content = call_ai(
        AI_EDITORIAL_MODEL,
        [
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ],
    )

    return {
        "content": content,
        "model": AI_EDITORIAL_MODEL,
        "topic_title": articles[0]["title"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# AI News Arena (新聞擂台)
# ---------------------------------------------------------------------------
def run_ai_arena(articles: list[dict], lang: str = "en") -> dict:
    """
    Run a multi-AI debate about today's top news topic.

    Each of the ARENA_PARTICIPANTS responds in turn, building on what the
    previous speakers have said.

    Args:
        articles: List of article dicts.
        lang:     "en" for English, "zh" for Cantonese.

    Returns:
        Dict with keys: topic_title, topic_summary, messages, generated_at.
    """
    if not articles:
        return {}

    top = articles[0]
    topic_title   = top["title"]
    topic_summary = top.get("summary", "")[:500]

    system_msg = _ARENA_SYSTEM_ZH if lang == "zh" else _ARENA_SYSTEM_EN
    lang_note  = "用廣東話" if lang == "zh" else "in English"

    # Seed the conversation with the topic
    opening = (
        f"Today's Arena topic ({lang_note}):\n\n"
        f"**{topic_title}**\n\n"
        f"{topic_summary}\n\n"
        "Share your analysis and perspective on this story."
    )

    # We keep a rolling conversation window so later participants can read
    # the earlier exchanges, but we cap it to avoid token bloat.
    conversation: list[dict] = [{"role": "user", "content": opening}]
    arena_messages: list[dict] = []

    for idx, participant in enumerate(ARENA_PARTICIPANTS):
        model = participant["model"]
        name  = participant["name"]

        messages = [{"role": "system", "content": system_msg}] + conversation

        print(f"  → Arena [{lang}] – {name} ({model})…")
        response = call_ai(model, messages)
        if not response:
            response = f"[{name} did not respond]"

        arena_messages.append(
            {"model": model, "name": name, "content": response}
        )

        # Append the response so the next participant can read it
        conversation.append(
            {"role": "assistant", "content": f"[{name}]: {response}"}
        )

        # Prompt for the next participant (except after the last one)
        if idx < len(ARENA_PARTICIPANTS) - 1:
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        f"Continue the discussion {lang_note}. "
                        "Respond to the points made so far and add your own analysis."
                    ),
                }
            )

        # Keep conversation window manageable: topic + last 4 exchanges
        if len(conversation) > 9:
            conversation = conversation[:1] + conversation[-8:]

        time.sleep(1)  # be polite to the API

    return {
        "topic_title":   topic_title,
        "topic_summary": topic_summary,
        "messages":      arena_messages,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Master generation function
# ---------------------------------------------------------------------------
def generate_ai_content(articles: list[dict]) -> dict:
    """
    Generate all AI content (editorial + arena) in both English and Cantonese.

    Returns a dict suitable for saving to ai_content.json.
    """
    print("── AI Editorial ──────────────────────────────────")
    editorial_en = generate_editorial(articles, lang="en")
    editorial_zh = generate_editorial(articles, lang="zh")

    print("── AI Arena ──────────────────────────────────────")
    arena_en = run_ai_arena(articles, lang="en")
    arena_zh = run_ai_arena(articles, lang="zh")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "editorial": {
            "en": editorial_en,
            "zh": editorial_zh,
        },
        "arena": {
            "en": arena_en,
            "zh": arena_zh,
        },
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------
def save_ai_content(content: dict) -> None:
    """Save AI content dict to docs/ai_content.json."""
    os.makedirs(os.path.dirname(AI_CONTENT_FILE), exist_ok=True)
    with open(AI_CONTENT_FILE, "w", encoding="utf-8") as fh:
        json.dump(content, fh, ensure_ascii=False, indent=2)
    print(f"AI content saved → {AI_CONTENT_FILE}")


def load_ai_content() -> dict:
    """Load AI content from docs/ai_content.json, or return empty dict."""
    if not os.path.exists(AI_CONTENT_FILE):
        return {}
    try:
        with open(AI_CONTENT_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    import sys

    news_file = os.path.join(os.path.dirname(__file__), "docs", "news.json")
    if not os.path.exists(news_file):
        print("ERROR: docs/news.json not found. Run fetch_news.py first.")
        sys.exit(1)

    with open(news_file, "r", encoding="utf-8") as fh:
        articles: list[dict] = json.load(fh)

    print(f"Loaded {len(articles)} articles from {news_file}")

    content = generate_ai_content(articles)
    save_ai_content(content)
    print("Done!")


if __name__ == "__main__":
    main()
