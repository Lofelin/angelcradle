"""
LLM 客户端抽象层：provider 配置、调用、JSON 解析。

全局基础设施——被 womb/ 和 cradle/ 共同消费。

[INPUT]: 环境变量 DEEPSEEK_API_KEY / ANTHROPIC_API_KEY / LLM_PROVIDER
[OUTPUT]: 导出 PROVIDERS, create_client, call_llm, parse_json, get_model
[POS]: 项目根级 LLM 基础设施
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import os
import re

import anthropic
from openai import OpenAI


# ============================================================
# LLM providers
# ============================================================

PROVIDERS = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_MODEL",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    "anthropic": {
        "api_key_env": "ANTHROPIC_API_KEY",
        "model_env": "ANTHROPIC_MODEL",
        "default_model": "claude-sonnet-4-6",
    },
    "4sapi": {
        "api_key_env": "FSAPI_API_KEY",
        "model_env": "FSAPI_MODEL",
        "base_url": "https://4sapi.com/v1",
        "default_model": "gemini-3.1-pro-preview",
    },
}


def get_model(provider: str) -> str:
    """Get model name from env var, fallback to provider default."""
    config = PROVIDERS.get(provider, {})
    return os.environ.get(config.get("model_env", ""), config.get("default_model", ""))


def create_client(provider: str):
    """创建 LLM 客户端实例。"""
    config = PROVIDERS.get(provider)
    if not config:
        raise ValueError(f"Unknown provider '{provider}', available: {', '.join(PROVIDERS)}")
    api_key = os.environ.get(config["api_key_env"], "")
    if not api_key:
        raise ValueError(f"Missing env var {config['api_key_env']}")
    if provider == "anthropic":
        return anthropic.Anthropic(api_key=api_key)
    return OpenAI(api_key=api_key, base_url=config.get("base_url"))


def call_llm(prompt: str, client, model: str, provider: str, max_tokens: int = 4096) -> str:
    """调用 LLM，返回原始文本响应。"""
    if provider == "anthropic":
        response = client.messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text if response.content else ""
    else:
        response = client.chat.completions.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content or ""

    if not text.strip():
        raise RuntimeError(f"LLM returned empty response (provider={provider}, model={model})")

    return text


def parse_json(raw: str) -> dict:
    """Parse JSON from LLM output. Attempts repair for common LLM JSON errors."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    # First try: direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Repair attempt: fix missing braces in arrays
    repaired = re.sub(
        r',\s*"(\w+)":\s*"',
        lambda m: m.group(0) if _is_inside_object(cleaned, m.start()) else ', {"' + m.group(1) + '": "',
        cleaned,
    )
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Repair attempt: balance braces/brackets
    open_braces = cleaned.count('{') - cleaned.count('}')
    open_brackets = cleaned.count('[') - cleaned.count(']')
    if open_braces > 0 or open_brackets > 0:
        repaired = cleaned + '}' * open_braces + ']' * open_brackets
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    # All repairs failed
    raise json.JSONDecodeError("All parse attempts failed", cleaned, 0)


def _is_inside_object(text: str, pos: int) -> bool:
    """Rough check if position is inside a JSON object (not between array items)."""
    depth = 0
    for i in range(pos):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
    return depth > 1
