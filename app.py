"""untangle-ai — Co-Planner 메인 화면 (F1).

Streamlit 진입점. `uv run streamlit run app.py` 로 실행한다.
이 파일은 화면(UI)만 담당하고, 실제 로직은 features/* 를 호출한다.

F1 인수 기준:
- F1-1 자유 텍스트 입력          → st.chat_input
- F1-2 턴 진행·직전 맥락 유지     → coplanner.respond(active) 에 대화 전체 전달
- F1-3 대화 시작 전 의도 선택     → 대화 전 st.radio, 시작 후 모드 고정
- F1-4 대화 원본 저장·열람        → 생성 즉시 save_conversation, '대화 기록' 페이지에서 열람
"""
from __future__ import annotations

import streamlit as st

import features
from features import ACTIVE_CONV, LLMConfigError, coplanner
from features.coplanner import Conversation, Intent, Message

st.set_page_config(page_title="untangle-ai", page_icon="🧶", layout="centered")
features.init_state()  # 메모리 저장소(session_state) 초기화

st.title("🧶 untangle-ai")
st.caption("뒤섞인 생각을 '지금 할 첫 단계'로 — Co-Planner")

active = st.session_state.get(ACTIVE_CONV)

# ── F1-3: 대화 시작 전 의도(intent) 선택 ──────────────────────────
if active is None:
    intent = st.radio(
        "무엇을 도와드릴까요?",
        options=list(Intent),
        format_func=lambda i: i.label,
        horizontal=True,
        key="intent_choice",
    )
    st.caption("의도를 고르고 아래에 자유롭게 입력하면 대화가 시작돼요.")
else:
    # 대화가 시작되면 모드를 고정한다. 바꾸려면 새 대화를 시작한다. (F1-3)
    intent = active.intent
    left, right = st.columns([0.72, 0.28])
    left.caption(f"현재 모드 · {intent.label}")
    if right.button("＋ 새 대화"):
        st.session_state[ACTIVE_CONV] = None
        st.rerun()

# ── F1-2: 지금까지의 대화(직전 맥락) 표시 ─────────────────────────
if active is not None:
    for msg in active.messages:
        st.chat_message(msg.role).write(msg.content)

# ── F1-1: 자유 텍스트 입력으로 턴 진행 ────────────────────────────
user_text = st.chat_input(intent.hint)
if user_text:
    # 첫 입력이면 새 대화를 만들어 원본을 즉시 보관한다. (F1-4)
    if active is None:
        active = Conversation(intent=intent)
        coplanner.save_conversation(active)
        st.session_state[ACTIVE_CONV] = active

    active.messages.append(Message("user", user_text))  # F1-1

    # 직전 맥락 전체를 넘겨 다음 응답을 생성한다. (F1-2)
    with st.spinner("Co-Planner가 생각 중…"):
        is_error = False
        try:
            reply = coplanner.respond(active)
            if not reply.strip():  # 빈 응답 방어(빈 말풍선·다음 턴 오염 방지)
                is_error = True
                reply = "⚠️ 빈 응답을 받았어요. 한 번만 더 말씀해 주시겠어요?"
        except LLMConfigError as exc:
            is_error = True
            reply = (
                f"⚠️ {exc}\n\n"
                "설정 방법은 README의 'API 키 설정'을 참고해주세요."
            )
        except Exception as exc:  # 호출 실패에도 대화가 끊기지 않게
            is_error = True
            reply = (
                "⚠️ 지금은 응답을 만들지 못했어요. 잠시 후 다시 시도해주세요. "
                f"({type(exc).__name__})"
            )

    # 오류·안내는 error=True 로 저장한다: 화면엔 보이되 다음 턴 맥락엔 섞이지 않는다. (F1-2)
    active.messages.append(Message("assistant", reply, error=is_error))
    st.rerun()

# 안내: 자세한 할 일/대화 기록은 사이드바의 페이지에서
st.divider()
st.caption("← 사이드바에서 '오늘 할 일'과 '대화 기록'을 볼 수 있어요. 대화는 자동 저장돼요.")
