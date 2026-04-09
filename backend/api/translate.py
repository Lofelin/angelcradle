"""
Translation API: fallback translation for keys not in frontend dictionary.
Uses the same LLM provider to translate, avoiding extra API keys.
"""

import os
from typing import Optional

from fastapi import APIRouter
from openai import OpenAI
import anthropic

router = APIRouter()

# Simple cache to avoid repeated translations
_cache: dict[str, dict[str, str]] = {}


def _translate_via_llm(text: str, target_lang: str) -> str:
    """Translate text using the configured LLM provider."""
    provider = os.environ.get("LLM_PROVIDER", "deepseek")

    prompt = f"Translate the following English text to {'Chinese (Simplified)' if target_lang == 'zh' else target_lang}. Return ONLY the translation, nothing else:\n\n{text}"

    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    elif provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()
    else:
        api_key = os.environ.get("FSAPI_API_KEY", "")
        model = os.environ.get("FSAPI_MODEL", "gemini-3-pro-previewv")
        client = OpenAI(api_key=api_key, base_url="https://4sapi.com")
        response = client.chat.completions.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()


@router.get("/translate")
def translate(text: str, lang: str = "zh"):
    """Translate a text string. Cached per text+lang pair."""
    cache_key = f"{lang}:{text}"
    if cache_key in _cache:
        return {"text": text, "lang": lang, "translation": _cache[cache_key]}

    try:
        translation = _translate_via_llm(text, lang)
        _cache[cache_key] = translation
        return {"text": text, "lang": lang, "translation": translation}
    except Exception as e:
        return {"text": text, "lang": lang, "translation": text, "error": str(e)}


@router.post("/translate/batch")
def translate_batch(texts: list[str], lang: str = "zh"):
    """Translate multiple texts at once."""
    results = []
    uncached = []
    uncached_indices = []

    for i, text in enumerate(texts):
        cache_key = f"{lang}:{text}"
        if cache_key in _cache:
            results.append({"text": text, "translation": _cache[cache_key]})
        else:
            results.append(None)
            uncached.append(text)
            uncached_indices.append(i)

    if uncached:
        joined = "\n---\n".join(uncached)
        prompt = (
            f"Translate each of the following English terms/phrases to {'Chinese (Simplified)' if lang == 'zh' else lang}. "
            f"Return ONLY the translations, one per line, separated by '---', in the same order:\n\n{joined}"
        )

        try:
            provider = os.environ.get("LLM_PROVIDER", "deepseek")
            if provider == "anthropic":
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
                client = anthropic.Anthropic(api_key=api_key)
                response = client.messages.create(
                    model=model, max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
            elif provider == "deepseek":
                api_key = os.environ.get("DEEPSEEK_API_KEY", "")
                model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
                client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
                response = client.chat.completions.create(
                    model=model, max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.choices[0].message.content.strip()
            else:
                api_key = os.environ.get("FSAPI_API_KEY", "")
                model = os.environ.get("FSAPI_MODEL", "gemini-3-pro-preview")
                client = OpenAI(api_key=api_key, base_url="https://4sapi.com")
                response = client.chat.completions.create(
                    model=model, max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.choices[0].message.content.strip()

            translations = [t.strip() for t in raw.split("---")]
            for j, idx in enumerate(uncached_indices):
                translation = translations[j] if j < len(translations) else uncached[j]
                cache_key = f"{lang}:{uncached[j]}"
                _cache[cache_key] = translation
                results[idx] = {"text": uncached[j], "translation": translation}
        except Exception:
            for j, idx in enumerate(uncached_indices):
                results[idx] = {"text": uncached[j], "translation": uncached[j]}

    return {"lang": lang, "results": results}
