"""오늘 할 일 목록 화면 (F7).

features.todo 의 로직을 호출해 할 일을 보여주고 관리한다. (UI만 담당)
할 일에 지정된 속성(우선순위·날짜·시간·반복)은 제목 아래 배지로 함께 보여준다.
(F4 한 줄 추가가 채운 속성이 목록에서 드러나도록 — F6-1/F6-4)
"""

from __future__ import annotations

import streamlit as st

import features
from features import todo

st.set_page_config(page_title="오늘 할 일", page_icon="✅")
features.init_state()

st.title("✅ 오늘 할 일")

# 우선순위 배지는 '높음·중간'만 강조한다. 낮음·없음은 목록을 차분하게 유지하려 표시하지 않는다.
_PRIORITY_ICON = {1: "🔴", 2: "🟡"}


def _meta_chips(item) -> str:
    """할 일에 지정된 속성을 한 줄 배지 문자열로 만든다(지정된 것만)."""
    chips = []
    if item.priority in _PRIORITY_ICON:
        chips.append(f"{_PRIORITY_ICON[item.priority]} {todo.priority_label(item.priority)}")
    if item.due_date is not None:
        when = item.due_date.strftime("%m-%d")
        if item.due_time is not None:
            when += " " + item.due_time.strftime("%H:%M")
        chips.append("📅 " + when)
    elif item.due_time is not None:
        chips.append("⏰ " + item.due_time.strftime("%H:%M"))
    if item.recurrence:
        chips.append("🔁 " + item.recurrence)
    return " · ".join(chips)


todos = todo.list_todos()
if not todos:
    st.caption("아직 할 일이 없어요. 메인 화면에서 생각을 정리해보세요.")

# F7-1: 목록 표시 / F7-3: 완료 토글 / F7-2: 삭제
for item in todos:
    col1, col2 = st.columns([0.88, 0.12])
    checked = col1.checkbox(item.title, value=item.done, key=f"todo_{item.id}")
    meta = _meta_chips(item)
    if meta:
        col1.caption(meta)  # 우선순위·날짜·시간·반복 배지 (F4 추출 속성 노출)
    if checked != item.done:
        todo.toggle_done(item.id)  # 즉시 되돌릴 수 있음(F7-3), 비징벌 표현(F7-5)
        st.rerun()
    if col2.button("🗑", key=f"del_{item.id}"):
        todo.delete_todo(item.id)
        st.rerun()
