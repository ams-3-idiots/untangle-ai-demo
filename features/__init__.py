"""features — 기능 로직 패키지.

화면(app.py, pages/) 뒤에서 동작하는 로직을 모은다.
- UI 위젯 렌더링은 하지 않는다(그건 pages/ 의 역할).
- 데이터는 별도 DB 없이 st.session_state(메모리)에 보관한다.
- 모든 LLM 호출은 call_llm() 한 통로로만 한다. (레이어 규칙)
"""
from __future__ import annotations

import streamlit as st

# ── 메모리 저장소(session_state) 키 ────────────────────────────────
TODOS = "todos"                  # 확정된 오늘 할 일          list[todo.Todo]              (F7)
ARCHIVED = "archived"            # 확정에서 제외돼 보관된 항목  list[todo.Todo]              (F6-3)
CONVERSATIONS = "conversations"  # 저장된 대화 원본           list[coplanner.Conversation] (F1-4)
PENDING = "pending"              # 확정 대기 중인 AI 제안      confirm.Proposal | None      (GP-1)


def init_state() -> None:
    """앱/페이지 진입 시 메모리 저장소를 초기화한다(이미 있으면 유지)."""
    st.session_state.setdefault(TODOS, [])
    st.session_state.setdefault(ARCHIVED, [])
    st.session_state.setdefault(CONVERSATIONS, [])
    st.session_state.setdefault(PENDING, None)


# ── LLM 단일 통로 ────────────────────────────────────────────────
# 기본 프로바이더·모델은 st.secrets 로 덮어쓸 수 있다(아래 _secret 참고).
_DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS = 1024
_DEFAULT_TEMPERATURE = 0.3


def _secret(key: str, default=None):
    """st.secrets 에서 값을 안전하게 읽는다.

    secrets.toml 파일이 없거나 키가 없어도 예외를 던지지 않고 default 를 돌려준다.
    (키 설정 전이라도 앱은 떠 있어야 하므로 — 실제 호출 시에만 명확한 오류를 낸다.)
    """
    try:
        return st.secrets[key]
    except Exception:
        return default


def _resolve_provider():
    """사용할 LLM 프로바이더를 정한다.

    - LLM_PROVIDER("anthropic" | "openai") 로 강제할 수 있다.
    - 지정이 없으면 키가 있는 쪽을 쓰되 Claude 를 우선한다.
    - 어느 키도 없으면 None 을 돌려준다(call_llm 이 안내 오류를 낸다).
    """
    forced = str(_secret("LLM_PROVIDER", "")).strip().lower()
    has_anthropic = bool(_secret("ANTHROPIC_API_KEY"))
    has_openai = bool(_secret("OPENAI_API_KEY"))
    if forced in ("anthropic", "claude"):
        return "anthropic" if has_anthropic else None
    if forced in ("openai", "gpt"):
        return "openai" if has_openai else None
    if has_anthropic:
        return "anthropic"
    if has_openai:
        return "openai"
    return None


def call_llm(prompt: str, *, system: str = "") -> str:
    """LLM(OpenAI/Claude) 호출 지점 — 모든 AI 기능이 공유하는 단일 통로.

    키는 st.secrets(`.streamlit/secrets.toml`)에서 읽는다. (ENVIRONMENT.md §6)
    프로바이더는 키 존재 여부로 자동 선택하며 `LLM_PROVIDER` 로 덮어쓸 수 있다.
    features/*.py 의 추출·분해·제안 로직은 반드시 이 함수를 통해서만 LLM 을 부른다.
    """
    provider = _resolve_provider()
    if provider == "anthropic":
        return _call_anthropic(prompt, system)
    if provider == "openai":
        return _call_openai(prompt, system)
    raise RuntimeError(
        "LLM API 키가 설정되지 않았어요. `.streamlit/secrets.toml` 에 "
        "ANTHROPIC_API_KEY 또는 OPENAI_API_KEY 를 넣어주세요."
    )


def _call_anthropic(prompt: str, system: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=_secret("ANTHROPIC_API_KEY"))
    kwargs = {
        "model": _secret("ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_MODEL),
        "max_tokens": _DEFAULT_MAX_TOKENS,
        "temperature": _DEFAULT_TEMPERATURE,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return "".join(getattr(block, "text", "") for block in resp.content).strip()


def _call_openai(prompt: str, system: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=_secret("OPENAI_API_KEY"))
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=_secret("OPENAI_MODEL", _DEFAULT_OPENAI_MODEL),
        messages=messages,
        temperature=_DEFAULT_TEMPERATURE,
        max_tokens=_DEFAULT_MAX_TOKENS,
    )
    return (resp.choices[0].message.content or "").strip()
