"""features — 기능 로직 패키지.

화면(app.py, pages/) 뒤에서 동작하는 로직을 모은다.
- UI 위젯 렌더링은 하지 않는다(그건 pages/ 의 역할).
- 데이터는 별도 DB 없이 st.session_state(메모리)에 보관한다.
- 모든 LLM 호출은 call_llm() 한 통로로만 한다(provider 교체·키 관리를 한 곳에서).
"""
from __future__ import annotations

from typing import List, Optional

import streamlit as st

# ── 메모리 저장소(session_state) 키 ────────────────────────────────
TODOS = "todos"                  # 확정된 오늘 할 일          list[todo.Todo]              (F7)
ARCHIVED = "archived"            # 확정에서 제외돼 보관된 항목  list[todo.Todo]              (F6-3)
CONVERSATIONS = "conversations"  # 저장된 대화 원본           list[coplanner.Conversation] (F1-4)
PENDING = "pending"              # 확정 대기 중인 AI 제안      confirm.Proposal | None      (GP-1)
ACTIVE_CONV = "active_conv"      # 진행 중인 대화             coplanner.Conversation | None (F1-2)
BREAKDOWN = "breakdown"          # 진행 중인 쪼개기 세션       breakdown.BreakdownSession | None (F3)

# ── LLM 설정 (st.secrets, ENVIRONMENT.md §6) ──────────────────────
# LLM_PROVIDER   : "openai" | "anthropic" (없으면 키 존재로 자동 판별)
# OPENAI_API_KEY / ANTHROPIC_API_KEY : 각 provider 키
# OPENAI_MODEL   / ANTHROPIC_MODEL    : 모델 이름(선택, 아래 기본값 사용)
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"


class LLMConfigError(RuntimeError):
    """LLM 설정(키·provider) 문제. UI에서 잡아 안내 메시지로 바꾼다."""


def init_state() -> None:
    """앱/페이지 진입 시 메모리 저장소를 초기화한다(이미 있으면 유지)."""
    st.session_state.setdefault(TODOS, [])
    st.session_state.setdefault(ARCHIVED, [])
    st.session_state.setdefault(CONVERSATIONS, [])
    st.session_state.setdefault(PENDING, None)
    st.session_state.setdefault(ACTIVE_CONV, None)
    st.session_state.setdefault(BREAKDOWN, None)


# ── LLM 단일 통로 ────────────────────────────────────────────────
def _secret(key: str, default=None):
    """st.secrets 에서 값을 안전하게 읽는다.

    secrets.toml 이 아예 없으면 접근 자체가 예외를 던질 수 있어 넓게 잡는다.
    """
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


def _resolve_provider() -> str:
    """사용할 provider 를 정한다: 명시 설정 > 키 존재 자동 판별."""
    provider = str(_secret("LLM_PROVIDER") or "").strip().lower()
    if provider in ("anthropic", "claude"):
        return "anthropic"
    if provider in ("openai", "gpt"):
        return "openai"
    # 자동 판별: 키가 있는 쪽을 쓴다(Anthropic 우선).
    if _secret("ANTHROPIC_API_KEY"):
        return "anthropic"
    if _secret("OPENAI_API_KEY"):
        return "openai"
    raise LLMConfigError(
        "LLM API 키가 설정되지 않았어요. .streamlit/secrets.toml 에 "
        "OPENAI_API_KEY 또는 ANTHROPIC_API_KEY 를 넣어주세요."
    )


def call_llm(
    prompt: Optional[str] = None,
    *,
    system: str = "",
    messages: Optional[List[dict]] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """LLM(OpenAI/Claude) 호출 — 모든 AI 기능이 공유하는 단일 통로.

    - prompt   : 단발성 사용자 입력(문자열). messages 와 택일한다.
    - messages : [{"role": "user"/"assistant", "content": ...}] 형태의 다중 턴
                 대화. 직전 맥락을 그대로 넘겨 이어서 응답하게 한다. (F1-2)
    - system   : 시스템 프롬프트(역할·규칙).

    provider·모델·키는 st.secrets 에서 읽는다(코드에 키를 두지 않는다).
    설정 문제는 LLMConfigError 로 올려 화면에서 안내로 바꾼다.
    """
    if messages is None:
        messages = [{"role": "user", "content": prompt or ""}]

    provider = _resolve_provider()
    if provider == "anthropic":
        return _call_anthropic(system, messages, temperature, max_tokens)
    return _call_openai(system, messages, temperature, max_tokens)


def _call_openai(system, messages, temperature, max_tokens) -> str:
    from openai import OpenAI  # 지연 임포트(기동 비용·선택적 사용)

    api_key = _secret("OPENAI_API_KEY")
    if not api_key:
        raise LLMConfigError("OPENAI_API_KEY 가 없어요. .streamlit/secrets.toml 을 확인해주세요.")

    model = _secret("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    client = OpenAI(api_key=api_key)

    chat_messages = []
    if system:
        chat_messages.append({"role": "system", "content": system})
    chat_messages.extend(messages)

    resp = client.chat.completions.create(
        model=model,
        messages=chat_messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def _call_anthropic(system, messages, temperature, max_tokens) -> str:
    from anthropic import Anthropic  # 지연 임포트

    api_key = _secret("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMConfigError("ANTHROPIC_API_KEY 가 없어요. .streamlit/secrets.toml 을 확인해주세요.")

    model = _secret("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
    client = Anthropic(api_key=api_key)

    # anthropic: system 은 top-level 인자. messages 는 user 로 시작하고 교대해야 한다.
    kwargs = dict(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    if system:
        kwargs["system"] = system

    try:
        resp = client.messages.create(temperature=temperature, **kwargs)
    except Exception as exc:
        # 일부 최신 모델(예: Opus 4.8)은 temperature 를 받지 않는다 — 그때만 빼고 재시도.
        if "temperature" in str(exc).lower():
            resp = client.messages.create(**kwargs)
        else:
            raise
    # content 는 블록 리스트 — 텍스트 블록만 모은다.
    parts = [
        block.text
        for block in resp.content
        if getattr(block, "type", None) == "text"
    ]
    return "".join(parts).strip()
