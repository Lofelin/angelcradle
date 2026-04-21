"""
LLM 客户端抽象层：provider 配置、调用、JSON 解析。

全局基础设施——被 womb/ 和 cradle/ 共同消费。

[INPUT]: 环境变量 DEEPSEEK_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY / LLM_PROVIDER
         可选覆盖 base_url: DEEPSEEK_BASE_URL / FSAPI_BASE_URL / GEMINI_BASE_URL
[OUTPUT]: 导出 PROVIDERS, create_client, call_llm, parse_json, get_model
[POS]: 项目根级 LLM 基础设施
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

import anthropic
from openai import OpenAI

logger = logging.getLogger(__name__)


# ============================================================
# LLM providers
# ============================================================

PROVIDERS = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "model_env": "DEEPSEEK_MODEL",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "default_base_url": "https://api.deepseek.com",
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
        "base_url_env": "FSAPI_BASE_URL",
        "default_base_url": "https://4sapi.com/v1",
        "default_model": "gemini-3.1-pro-preview",
    },
    # Google Gemini 官方端点（OpenAI 兼容层，零新依赖）
    # 文档: https://ai.google.dev/gemini-api/docs/openai
    "gemini": {
        "api_key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "base_url_env": "GEMINI_BASE_URL",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-flash-latest",
    },
}


def _get_base_url(config: dict) -> str | None:
    """从 env 读 base_url，未设则用 default_base_url。anthropic 无 base_url 返回 None。"""
    env_name = config.get("base_url_env")
    if env_name:
        override = os.environ.get(env_name, "").strip()
        if override:
            return override
    return config.get("default_base_url")


def get_model(provider: str) -> str:
    """Get model name from env var, fallback to provider default."""
    config = PROVIDERS.get(provider, {})
    return os.environ.get(config.get("model_env", ""), config.get("default_model", ""))


def create_client(provider: str):
    """创建 LLM 客户端实例。

    openai SDK 默认会在网络错误/超时时内部重试 2 次，每次都独占完整 timeout 窗口,
    导致上层观察到的耗时是 3x timeout,且我们自己已经有 _call_with_retry 和 stages 层
    重试,SDK 内部重试只会让故障面放大。这里显式关掉。
    """
    config = PROVIDERS.get(provider)
    if not config:
        raise ValueError(f"Unknown provider '{provider}', available: {', '.join(PROVIDERS)}")
    api_key = os.environ.get(config["api_key_env"], "")
    if not api_key:
        raise ValueError(f"Missing env var {config['api_key_env']}")
    if provider == "anthropic":
        return anthropic.Anthropic(api_key=api_key, max_retries=0)
    return OpenAI(api_key=api_key, base_url=_get_base_url(config), max_retries=0)


# 单次 LLM 请求超时（秒）。上游卡住时避免 SSE 心跳无限延长。
# 默认 180s：早期器官等长 prompt 在慢 provider 上可能 90s 不够。
LLM_REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "180"))

# 429 重试：Gemini 免费档 5 RPM / 12s 一个槽；指数退避 15/30/45/60s 够消化一个分钟窗口
_RETRY_BASE_DELAY = float(os.environ.get("LLM_RETRY_BASE_DELAY", "15"))
_RETRY_MAX_ATTEMPTS = int(os.environ.get("LLM_RETRY_MAX_ATTEMPTS", "4"))


def _is_rate_limit(exc: BaseException) -> bool:
    """识别 429 限流错误，兼容 openai / anthropic / google 各家 SDK 的封装。"""
    if type(exc).__name__ == "RateLimitError":
        return True
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None) if resp is not None else None
    return status == 429


def _call_with_retry(fn):
    """对 LLM 调用做 429 重试；其他异常直接抛。"""
    last_exc: BaseException | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return fn()
        except Exception as e:
            if not _is_rate_limit(e) or attempt == _RETRY_MAX_ATTEMPTS - 1:
                raise
            delay = _RETRY_BASE_DELAY * (attempt + 1)
            logger.warning("LLM 限流 (429), %.1fs 后重试 (第 %d 次)", delay, attempt + 1)
            time.sleep(delay)
            last_exc = e
    if last_exc:
        raise last_exc


def _estimate_tokens(text: str) -> int:
    """粗估 token 数：中文按 1.5 token/字，英文按 1.3 token/词。"""
    import re as _re
    chinese_chars = len(_re.findall(r'[\u4e00-\u9fff]', text))
    remaining = _re.sub(r'[\u4e00-\u9fff]', '', text)
    english_words = len(remaining.split())
    return int(chinese_chars * 1.5 + english_words * 1.3)


def _extract_usage(response, provider: str) -> str:
    """从 LLM 响应中提取 token 用量（如果有）。"""
    try:
        if provider == "anthropic":
            u = response.usage
            return f"input={u.input_tokens} output={u.output_tokens}"
        else:
            u = response.usage
            if u:
                return f"input={u.prompt_tokens} output={u.completion_tokens}"
    except Exception:
        pass
    return ""


def call_llm(
    prompt: str, client, model: str, provider: str,
    max_tokens: int = 4096, timeout: float | None = None,
    metadata: dict | None = None,
) -> str:
    """调用 LLM，返回原始文本响应。带超时兜底避免上游卡死；429 自动重试。"""
    t = timeout if timeout is not None else LLM_REQUEST_TIMEOUT

    est = _estimate_tokens(prompt)
    logger.info(
        "┌─ LLM 请求 [%s/%s] prompt≈%d tokens\n%s",
        provider, model, est, prompt,
    )

    t0 = time.time()

    if provider == "anthropic":
        def _do():
            return client.with_options(timeout=t).messages.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        response = _call_with_retry(_do)
        text = response.content[0].text if response.content else ""
    else:
        def _do():
            return client.with_options(timeout=t).chat.completions.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        response = _call_with_retry(_do)
        text = response.choices[0].message.content or ""

    elapsed = time.time() - t0
    usage = _extract_usage(response, provider)
    logger.info(
        "└─ LLM 响应 [%s/%s] %.1fs %s\n%s",
        provider, model, elapsed, usage, text,
    )

    if not text.strip():
        raise RuntimeError(f"LLM returned empty response (provider={provider}, model={model})")

    if metadata:
        from llm_log import persist_llm_call
        persist_llm_call(metadata, prompt, text, provider, model, elapsed, usage)

    return text


def call_llm_chat(
    system: str, messages: list[dict], client, model: str, provider: str,
    max_tokens: int = 4096, timeout: float | None = None,
    metadata: dict | None = None,
) -> str:
    """调用 LLM（chat 格式：system prompt + 多轮消息），返回原始文本响应；429 自动重试。"""
    t = timeout if timeout is not None else LLM_REQUEST_TIMEOUT

    # 拼接所有文本估算 token
    all_text = system + " ".join(m.get("content", "") for m in messages)
    est = _estimate_tokens(all_text)
    msg_text = "\n".join(f"  [{m['role']}] {m.get('content', '')}" for m in messages)
    logger.info(
        "┌─ LLM Chat 请求 [%s/%s] ≈%d tokens\n  [system] %s\n%s",
        provider, model, est, system, msg_text,
    )

    t0 = time.time()

    if provider == "anthropic":
        def _do():
            return client.with_options(timeout=t).messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=messages,
            )
        response = _call_with_retry(_do)
        text = response.content[0].text if response.content else ""
    else:
        # OpenAI-compatible: system 作为第一条消息
        all_messages = [{"role": "system", "content": system}] + messages
        def _do():
            return client.with_options(timeout=t).chat.completions.create(
                model=model, max_tokens=max_tokens,
                messages=all_messages,
            )
        response = _call_with_retry(_do)
        text = response.choices[0].message.content or ""

    elapsed = time.time() - t0
    usage = _extract_usage(response, provider)
    logger.info(
        "└─ LLM Chat 响应 [%s/%s] %.1fs %s\n%s",
        provider, model, elapsed, usage, text,
    )

    if not text.strip():
        raise RuntimeError(f"LLM returned empty response (provider={provider}, model={model})")

    if metadata:
        from llm_log import persist_llm_call
        prompt_data = {"system": system, "messages": messages}
        persist_llm_call(metadata, prompt_data, text, provider, model, elapsed, usage)

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

    # Repair attempt: escape unescaped quotes inside value strings.
    # LLM 经常在 "summary": "...话..."内容..."" 里直插半角引号,这里做保守的扫描修复。
    escaped = _escape_inner_value_quotes(cleaned)
    if escaped != cleaned:
        try:
            return json.loads(escaped)
        except json.JSONDecodeError:
            pass

    # All repairs failed
    raise json.JSONDecodeError("All parse attempts failed", cleaned, 0)


def _escape_inner_value_quotes(text: str) -> str:
    """
    状态机扫描：当位于 value 字符串内部时,若遇到未转义的 `"` 且其后不是
    JSON 结构终止符 (逗号/右括号/行尾) ,则将其视为字符串内容中的半角引号
    并补上反斜杠。仅处理 value,不动 key,避免误伤。
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    in_value_string = False
    expect_value = False  # 刚刚遇到 ':' ,下一个字符串应当是 value
    while i < n:
        ch = text[i]
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
                in_value_string = expect_value
                expect_value = False
            elif ch == ':':
                expect_value = True
            elif ch in '{[,}]':
                expect_value = False
            i += 1
            continue
        # 字符串内
        if ch == '\\' and i + 1 < n:
            out.append(ch)
            out.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            if in_value_string:
                # 前瞻：跳过空白后是否跟着 JSON 终止符
                j = i + 1
                while j < n and text[j] in ' \t':
                    j += 1
                is_terminator = j >= n or text[j] in ',}\n\r]'
                if not is_terminator:
                    out.append('\\"')
                    i += 1
                    continue
            in_string = False
            in_value_string = False
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _is_inside_object(text: str, pos: int) -> bool:
    """Rough check if position is inside a JSON object (not between array items)."""
    depth = 0
    for i in range(pos):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
    return depth > 1
