"""untangle-ai — Co-Planner 메인 화면 (F1).

Streamlit 진입점. `streamlit run app.py` 로 실행한다.
이 파일은 화면(UI)만 담당하고, 실제 로직은 features/* 를 호출한다.
"""
from __future__ import annotations

import streamlit as st

import features
from features import confirm, coplanner
from features.coplanner import Conversation, Intent, Message, route

st.set_page_config(page_title="untangle-ai", page_icon="🧶", layout="centered")
features.init_state()  # 메모리 저장소(session_state) 초기화

st.title("🧶 untangle-ai")
st.caption("뒤섞인 생각을 '지금 할 첫 단계'로 — Co-Planner")

# F1-3: 대화 시작 전 의도 선택
intent = st.radio(
    "무엇을 도와드릴까요?",
    options=list(Intent),
    format_func=lambda i: i.label,
    horizontal=True,
)

# F1-2: 현재 대화의 직전 맥락 표시
active = st.session_state.get("active_conv")
if active is not None and active.intent is intent:
    for msg in active.messages:
        st.chat_message(msg.role).write(msg.content)

# F1: 자유 텍스트 입력으로 턴 진행
user_text = st.chat_input("생각을 자유롭게 적어보세요…")
if user_text:
    # 의도가 바뀌었거나 첫 입력이면 새 대화를 시작해 원본을 보관한다. (F1-4)
    if active is None or active.intent is not intent:
        active = Conversation(intent=intent)
        coplanner.save_conversation(active)
        st.session_state["active_conv"] = active

    active.messages.append(Message("user", user_text))

    # 의도에 맞는 기능으로 라우팅 → AI 제안 생성 (확정 전 미반영, GP-1)
    proposal = route(intent, user_text)
    if proposal.drafts:
        confirm.stage(proposal)   # 확정할 후보가 있을 때만 확정 UI를 띄운다
    else:
        confirm.clear_pending()   # 빈 결과(F2-4)는 확정 UI 없이 안내 메시지만 남긴다
    active.messages.append(
        Message("assistant", proposal.note or "제안을 준비했어요. 아래에서 확인해주세요.")
    )
    st.rerun()

# F6: 확정 대기 중인 제안 편집·확정 (확정 전에는 데이터에 반영되지 않음)
pending = confirm.get_pending()
if pending is not None:
    st.divider()
    st.subheader("AI 제안")
    st.caption("확정하기 전에는 할 일에 반영되지 않아요. 최종 결정은 사용자에게 있어요.")
    if pending.note:
        st.info(pending.note)

    selected = []
    for draft in pending.drafts:
        if st.checkbox(draft.title, value=True, key=f"draft_{draft.id}"):
            selected.append(draft.id)
        if draft.memo:
            st.caption(draft.memo)

    col1, col2 = st.columns(2)
    if col1.button("선택 항목 확정", type="primary"):
        confirm.confirm(selected)  # 선택분 반영(F6-2) + 나머지 보관(F6-3)
        st.rerun()
    if col2.button("취소"):
        confirm.clear_pending()
        st.rerun()

# 안내: 자세한 할 일/대화 기록은 사이드바의 페이지에서
st.divider()
st.caption("← 사이드바에서 '오늘 할 일'과 '대화 기록'을 볼 수 있어요.")
