"""저장된 대화 열람 화면 (F1-4).

대화 원본은 features.coplanner 가 session_state(메모리)에 보관한다. (UI만 담당)
가장 최근 대화가 위로 오도록 보여준다.
"""
from __future__ import annotations

import streamlit as st

import features
from features import coplanner

st.set_page_config(page_title="대화 기록", page_icon="💬")
features.init_state()

st.title("💬 대화 기록")
st.caption("나눈 대화 원본이 그대로 저장돼요. 언제든 다시 열어볼 수 있어요.")

conversations = coplanner.list_conversations()
if not conversations:
    st.info("저장된 대화가 아직 없어요. 메인 화면에서 대화를 시작해보세요.")

# 최근 대화가 위로 오도록 역순으로 나열한다. (F1-4)
for conv in reversed(conversations):
    turns = sum(1 for m in conv.messages if m.role == "user")
    preview = next((m.content for m in conv.messages if m.role == "user"), "(빈 대화)")
    title = f"{conv.intent.label} · {turns}턴 · {preview[:24]}"
    with st.expander(title):
        if not conv.messages:
            st.caption("아직 주고받은 메시지가 없어요.")
        for msg in conv.messages:
            st.chat_message(msg.role).write(msg.content)
