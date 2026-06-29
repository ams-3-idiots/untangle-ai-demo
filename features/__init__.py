"""features — 기능 로직 패키지.

화면(app.py, pages/) 뒤에서 동작하는 로직을 모은다.
- UI 위젯 렌더링은 하지 않는다(그건 pages/ 의 역할).
- 데이터는 별도 DB 없이 st.session_state(메모리)에 보관한다.
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


def call_llm(prompt: str, *, system: str = "") -> str:
    """LLM(OpenAI/Claude) 호출 지점 — 모든 AI 기능이 공유하는 단일 통로.

    TODO: st.secrets 에서 API 키를 읽어 실제 provider 를 호출하도록 구현한다.
          (features/*.py 의 추출·분해·제안 로직이 이 함수를 사용한다.)
    """
    raise NotImplementedError("LLM 연동 미구현 — features.call_llm 을 구현하세요.")
