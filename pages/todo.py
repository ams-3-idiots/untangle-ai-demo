"""오늘 할 일 목록 화면 (F7).

features.todo 의 로직을 호출해 할 일을 보여주고 관리한다. (UI만 담당)
"""
from __future__ import annotations

import streamlit as st

import features
from features import todo

st.set_page_config(page_title="오늘 할 일", page_icon="✅")
features.init_state()

st.title("✅ 오늘 할 일")

todos = todo.list_todos()
if not todos:
    st.caption("아직 할 일이 없어요. 메인 화면에서 생각을 정리해보세요.")

# F7-1: 목록 표시 / F7-3: 완료 토글 / F7-2: 삭제
for item in todos:
    col1, col2 = st.columns([0.88, 0.12])
    checked = col1.checkbox(item.title, value=item.done, key=f"todo_{item.id}")
    if checked != item.done:
        todo.toggle_done(item.id)  # 즉시 되돌릴 수 있음(F7-3), 비징벌 표현(F7-5)
        st.rerun()
    if col2.button("🗑", key=f"del_{item.id}"):
        todo.delete_todo(item.id)
        st.rerun()
