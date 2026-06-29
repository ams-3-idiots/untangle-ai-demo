"""F7 — 당일 할 일 관리. 할 일 CRUD·완료 토글·우선순위.

데이터는 st.session_state(메모리)에 보관하며, UI 렌더링은 하지 않는다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

import streamlit as st

from features import TODOS


@dataclass
class Todo:
    """할 일 한 건. (F7-4: 우선순위·날짜·시간·알림·반복·하위·메모)"""

    title: str
    memo: str = ""
    priority: int = 3                       # 1(높음) ~ 4(낮음)
    due_date: Optional[date] = None
    due_time: Optional[time] = None
    reminder: Optional[str] = None
    recurrence: Optional[str] = None
    subtasks: list["Todo"] = field(default_factory=list)
    done: bool = False
    source: str = "manual"                  # 생성 출처(brain_dump/breakdown/…)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


def list_todos() -> list[Todo]:
    """오늘 할 일 전체를 반환한다. (F7-1)"""
    return st.session_state.get(TODOS, [])


def add_todo(todo: Todo) -> None:
    """할 일을 추가한다. (F7-2)"""
    st.session_state[TODOS].append(todo)


def update_todo(todo_id: str, **changes) -> None:
    """할 일 속성을 수정한다. (F7-2, F7-4)"""
    for todo in st.session_state[TODOS]:
        if todo.id == todo_id:
            for key, value in changes.items():
                setattr(todo, key, value)
            break


def delete_todo(todo_id: str) -> None:
    """할 일을 삭제한다. (F7-2)"""
    st.session_state[TODOS] = [t for t in st.session_state[TODOS] if t.id != todo_id]


def toggle_done(todo_id: str) -> None:
    """완료 상태를 토글한다. (F7-3) — 미완료에 실패감을 주지 않는다(F7-5)."""
    for todo in st.session_state[TODOS]:
        if todo.id == todo_id:
            todo.done = not todo.done
            break
