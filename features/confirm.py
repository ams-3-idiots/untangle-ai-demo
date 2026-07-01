"""F6 — 편집·확정·보관 (공통 모듈).

모든 AI 결과물(Proposal)은 사용자가 확정하기 전까지 실제 데이터에 반영되지 않는다(GP-1).
확정 시 선택된 항목만 할 일로 커밋하고, 나머지는 유실 없이 보관한다(F6-3).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

import streamlit as st

from features import ARCHIVED, PENDING
from features.todo import Todo, add_todo


@dataclass
class Proposal:
    """확정 전 AI 제안(staging 단위). 1~5번 기능의 출력이 이 형태로 모인다. (GP-1)"""

    drafts: list[Todo] = field(default_factory=list)  # 사용자가 확정할 할 일 후보
    note: str = ""                                    # 제안 설명/이유 (F5-3 등)
    source: str = ""                                  # 출처 기능(brain_dump 등)
    first_step_id: Optional[str] = None               # '지금 할 첫 단계' draft id (F3-5)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


def stage(proposal: Proposal) -> None:
    """AI 제안을 확정 대기 상태로 올린다. (아직 데이터 미반영 — GP-1)"""
    st.session_state[PENDING] = proposal


def get_pending() -> Optional[Proposal]:
    """확정 대기 중인 제안을 반환한다(없으면 None)."""
    return st.session_state.get(PENDING)


def clear_pending() -> None:
    """확정 대기 제안을 비운다."""
    st.session_state[PENDING] = None


def confirm(selected_ids: list[str]) -> None:
    """선택한 후보만 할 일로 반영하고, 나머지는 보관한다. (F6-2, F6-3)"""
    proposal = get_pending()
    if proposal is None:
        return
    for draft in proposal.drafts:
        if draft.id in selected_ids:
            add_todo(draft)                          # 실행 데이터에 반영 (F6-2)
        else:
            st.session_state[ARCHIVED].append(draft)  # 유실 없이 보관 (F6-3)
    clear_pending()
