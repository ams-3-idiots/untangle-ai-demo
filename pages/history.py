"""저장된 대화 열람 화면 (F1-4).

대화 원본은 features.coplanner 가 session_state(메모리)에 보관한다. (UI만 담당)
"""
from __future__ import annotations

import streamlit as st

import features
from features import coplanner

st.set_page_config(page_title="대화 기록", page_icon="💬")
features.init_state()

st.title("💬 대화 기록")

conversations = coplanner.list_conversations()
if not conversations:
    st.caption("저장된 대화가 아직 없어요.")

for conv in conversations:
    with st.expander(f"{conv.intent.label} · {conv.id[:8]}"):
        for msg in conv.messages:
            st.chat_message(msg.role).write(msg.content)
