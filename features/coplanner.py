"""F1 — Co-Planner. 대화 턴 관리와 의도(intent) 라우팅의 진입점.

모든 AI 기능(F2~F5)은 여기서 의도에 따라 호출된다.
대화 원본은 메모리(session_state)에 저장되어 언제든 열람할 수 있다. (F1-4)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

import streamlit as st

from features import CONVERSATIONS, brain_dump, breakdown, single_add, suggest
from features.confirm import Proposal


class Intent(Enum):
    """대화 시작 전 입력받는 의도. (F1-3)"""

    BRAIN_DUMP = "brain_dump"
    BREAKDOWN = "breakdown"
    SINGLE_ADD = "single_add"
    SITUATION = "situation"

    @property
    def label(self) -> str:
        return {
            Intent.BRAIN_DUMP: "🧠 브레인덤프",
            Intent.BREAKDOWN: "✂️ 쪼개기",
            Intent.SINGLE_ADD: "➕ 한 줄 추가",
            Intent.SITUATION: "🔄 상황 공유",
        }[self]


@dataclass
class Message:
    """대화 한 턴의 메시지."""

    role: str   # "user" | "assistant"
    content: str


@dataclass
class Conversation:
    """하나의 대화 세션. 직전 맥락을 유지한다(F1-2). 원본을 보관한다(F1-4)."""

    intent: Intent
    messages: list[Message] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


def route(intent: Intent, user_text: str) -> Proposal:
    """의도에 따라 알맞은 기능으로 입력을 전달한다. (F1-3 라우팅)"""
    if intent is Intent.BRAIN_DUMP:
        return brain_dump.extract(user_text)
    if intent is Intent.BREAKDOWN:
        return breakdown.decompose(user_text)
    if intent is Intent.SINGLE_ADD:
        return single_add.parse(user_text)
    return suggest.suggest_now(user_text)


def save_conversation(conversation: Conversation) -> None:
    """대화 원본을 메모리에 보관한다. 언제든 열람 가능. (F1-4)"""
    st.session_state[CONVERSATIONS].append(conversation)


def list_conversations() -> list[Conversation]:
    """저장된 대화 전체를 반환한다. (F1-4)"""
    return st.session_state.get(CONVERSATIONS, [])
