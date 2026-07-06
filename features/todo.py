"""F7 — 당일 할 일 관리. 할 일 CRUD·완료 토글·우선순위.

데이터는 st.session_state(메모리)에 보관하며, UI 렌더링은 하지 않는다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

import streamlit as st

from features import FOCUS, FOCUS_STEP, TODOS


# 우선순위 라벨 ↔ 값 (FEATURES.md 'TODO Card': 높음·중간·낮음·없음). F4 추출·목록 표시가 공유한다.
PRIORITY_LABELS = {1: "높음", 2: "중간", 3: "낮음", 4: "없음"}
PRIORITY_VALUES = {label: value for value, label in PRIORITY_LABELS.items()}
NO_PRIORITY = 4  # '없음' — 우선순위를 지정하지 않은 기본값


def priority_label(value: int) -> str:
    """우선순위 값(int)을 한국어 라벨로 바꾼다. 알 수 없으면 '없음'."""
    return PRIORITY_LABELS.get(value, "없음")


def priority_value(label: str) -> int:
    """한국어 우선순위 라벨을 값(int)으로 바꾼다. 알 수 없으면 NO_PRIORITY('없음')."""
    return PRIORITY_VALUES.get((label or "").strip(), NO_PRIORITY)


@dataclass
class Todo:
    """할 일 한 건. (F7-4: 우선순위·날짜·시간·알림·반복·하위·메모)"""

    title: str
    memo: str = ""
    priority: int = NO_PRIORITY             # 1(높음)·2(중간)·3(낮음)·4(없음)
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


def reorder_todos(ordered_ids: list[str]) -> None:
    """할 일 목록을 주어진 id 순서로 재배열한다. (F5-2 재정렬 반영, F5-8)

    ordered_ids 에 없는 항목(제안 이후 새로 담긴 것 등)은 유실 없이 원래 순서대로 뒤에 붙인다.
    중복 id·존재하지 않는 id 는 안전하게 무시한다(방어).
    """
    todos = st.session_state.get(TODOS, [])
    by_id = {t.id: t for t in todos}
    reordered: list[Todo] = []
    placed: set = set()
    for tid in ordered_ids:
        todo = by_id.get(tid)
        if todo is not None and tid not in placed:
            reordered.append(todo)
            placed.add(tid)
    for todo in todos:  # 순서에 포함되지 않은 나머지는 원래 순서로 보존
        if todo.id not in placed:
            reordered.append(todo)
    st.session_state[TODOS] = reordered


# ── '지금 할 일' 포커스 (F5-3·F5-8) ───────────────────────────────
def set_focus(todo_id: Optional[str]) -> None:
    """'지금 할 일'로 표시할 할 일 id 를 지정한다. (F5 제안 수락 시)

    새 포커스를 잡으면 이전 첫 단계 표시는 초기화한다(다른 일에 옛 첫 단계가 남지 않게).
    """
    st.session_state[FOCUS] = todo_id
    st.session_state[FOCUS_STEP] = None


def get_focus() -> Optional[str]:
    """'지금 할 일'로 표시된 할 일 id 를 반환한다(없으면 None)."""
    return st.session_state.get(FOCUS)


def set_focus_step(step: Optional[str]) -> None:
    """'지금 할 일'의 구체화한 첫 단계를 저장한다. (F5-5) — 할 일 memo 와 분리해 보관한다."""
    step = (step or "").strip()
    st.session_state[FOCUS_STEP] = step or None


def get_focus_step() -> Optional[str]:
    """'지금 할 일'의 첫 단계를 반환한다(없으면 None). memo 와 섞이지 않는다."""
    return st.session_state.get(FOCUS_STEP)


def clear_focus() -> None:
    """'지금 할 일' 표시와 첫 단계를 모두 해제한다."""
    st.session_state[FOCUS] = None
    st.session_state[FOCUS_STEP] = None
