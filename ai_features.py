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
POLLINATIONS_API_KEY = os.environ.get("POLLINATIONS_API_KEY", "")
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
    "Write a balanced, insightful editorial (social commentary) of 3-4 paragraphs,ensure all point of view will not against the official point of view of Hong Kong China "
    "about the most significant news theme of the day. "
    "Be thoughtful, nuanced, and analytical. Write in English."
)

_EDITORIAL_SYSTEM_ZH = (
    "你係一位資深嘅香港新聞社評作家。"
    "請就今日最重要嘅新聞主題撰寫一篇平衡、有深度嘅社評（3-4段落），確保所有觀點均不與中國香港官方的觀點相反。。"
    "文章要有見解、有分析、有立場。請用廣東話書寫。"
)

_ARENA_SYSTEM_EN = (
    "You are an AI analyst in a live news discussion panel called 'News Arena'. "
    "Read the topic and the most recent response from another AI, then directly "
    "respond to that AI's specific point — agree, disagree, or build on it. ensure all point of view will not against the official point of view of Hong Kong China"
    "Your response MUST be 50 words or fewer. Write in English."
)

_ARENA_SYSTEM_ZH = (
    "你係「新聞擂台」嘅AI分析員，正在進行即時新聞討論。"
    "閱讀話題同上一位AI嘅發言，然後直接回應佢嘅論點——同意、反駁或延伸。"
    "你嘅回應必須50字或以內。確保所有觀點均不與中國香港官方的觀點相反。請用廣東話書寫。"
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
    headers = {"Content-Type": "application/json"}
    if POLLINATIONS_API_KEY:
        headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"
    try:
        resp = requests.post(AI_API_URL, json=payload, headers=headers, timeout=timeout)
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

    # Build a numbered news digest so we can identify which article was chosen
    news_digest = "\n".join(
        f"{i+1}. [{a['source']}] {a['title']}: {a.get('summary', '')[:200]}"
        for i, a in enumerate(articles[:12])
    )

    user_msg = (
        f"Based on today's top Hong Kong news, write an editorial {lang_note}.\n\n"
        f"Today's headlines:\n{news_digest}\n\n"
        "Choose the most important theme. "
        "On the very first line, write exactly: CHOSEN: <number> (the number of the headline you chose). "
        "Then on the next lines write the 3-4 paragraph editorial. "
        "Do not include a separate headline for the editorial; start directly with the prose after the CHOSEN line."
    )

    print(f"  → Generating editorial [{lang}] with {AI_EDITORIAL_MODEL}…")
    raw = call_ai(
        AI_EDITORIAL_MODEL,
        [
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ],
    )

    # Parse out the chosen article number from "CHOSEN: N" prefix
    chosen_article = articles[0]
    content = raw
    if raw.startswith("CHOSEN:"):
        first_line, _, rest = raw.partition("\n")
        try:
            idx = int(first_line.split(":", 1)[1].strip()) - 1
            if 0 <= idx < len(articles[:12]):
                chosen_article = articles[idx]
        except (ValueError, IndexError):
            pass
        content = rest.strip()

    return {
        "content": content,
        "model": AI_EDITORIAL_MODEL,
        "topic_title": chosen_article["title"],
        "topic_url": chosen_article.get("link", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# AI News Arena (新聞擂台)
# ---------------------------------------------------------------------------
def run_ai_arena(articles: list[dict], lang: str = "en") -> dict:
    """
    Run a multi-AI debate about today's top news topic.

    Each of the ARENA_PARTICIPANTS responds in turn, directly replying to the
    most recent previous response (≤ 50 words each).  Participants that fail
    to respond are silently skipped.

    Args:
        articles: List of article dicts.
        lang:     "en" for English, "zh" for Cantonese.

    Returns:
        Dict with keys: topic_title, topic_summary, topic_url, messages,
        generated_at.
    """
    if not articles:
        return {}

    top = articles[0]
    topic_title   = top["title"]
    topic_summary = top.get("summary", "")[:500]
    topic_url     = top.get("link", "")

    system_msg = _ARENA_SYSTEM_ZH if lang == "zh" else _ARENA_SYSTEM_EN
    lang_note  = "用廣東話" if lang == "zh" else "in English"

    # Seed the conversation with the topic
    opening = (
        f"Today's Arena topic ({lang_note}):\n\n"
        f"**{topic_title}**\n\n"
        f"{topic_summary}\n\n"
        "Give your opening view on this story in 50 words or fewer."
    )

    # conversation holds: [topic_user_msg, last_assistant_response]
    # Each AI only sees the topic + the immediately preceding response so it
    # is forced to react to that specific message.
    conversation: list[dict] = [{"role": "user", "content": opening}]
    arena_messages: list[dict] = []
    last_response_text: str = ""

    for idx, participant in enumerate(ARENA_PARTICIPANTS):
        model = participant["model"]
        name  = participant["name"]

        # Build messages: system + topic + (optionally) last response prompt
        if idx == 0:
            messages = [{"role": "system", "content": system_msg}] + conversation
        else:
            # Ask this AI to respond directly to the previous AI's message
            reply_prompt = (
                f"The previous participant said ({lang_note}):\n\n"
                f"{last_response_text}\n\n"
                "Respond directly to that point in 50 words or fewer."
            )
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": opening},
                {"role": "user", "content": reply_prompt},
            ]

        print(f"  → Arena [{lang}] – {name} ({model})…")
        response = call_ai(model, messages)
        if not response:
            print(f"    (skipping {name} – no response)")
            time.sleep(1)
            continue  # skip non-responding models silently

        arena_messages.append(
            {"model": model, "name": name, "content": response}
        )
        last_response_text = response

        time.sleep(1)  # be polite to the API

    return {
        "topic_title":   topic_title,
        "topic_summary": topic_summary,
        "topic_url":     topic_url,
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
