"""F1 — Co-Planner. 대화 턴 관리와 의도(intent) 라우팅의 진입점.

모든 AI 기능(F2~F5)의 진입점이자 컨테이너다.
- F1 자체는 '의도에 맞춰 대화하는 인터페이스'다. 매 턴 직전 맥락을 유지한 채 응답한다(F1-2).
- 대화 원본은 메모리(session_state)에 저장되어 언제든 열람할 수 있다(F1-4).

할 일 추출·분해·제안·확정(F2~F5)의 구조화 처리는 각 모듈이 담당하며,
route() 가 그 연결 지점이다(F1 대화에서 필요 시 호출).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import streamlit as st

from features import CONVERSATIONS, call_llm

if TYPE_CHECKING:  # 타입 힌트 전용. 런타임 로드 시 F2~F6 스텁을 끌어오지 않는다.
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

    @property
    def hint(self) -> str:
        """의도별 입력 안내(플레이스홀더 등에 쓴다)."""
        return {
            Intent.BRAIN_DUMP: "머릿속에 뒤섞인 생각을 떠오르는 대로 쏟아내 보세요…",
            Intent.BREAKDOWN: "쪼개고 싶은 큰 일(목표)을 적어보세요…",
            Intent.SINGLE_ADD: "추가할 할 일을 한 문장으로 적어보세요…",
            Intent.SITUATION: "지금 바뀐 상황이나 에너지 상태를 들려주세요…",
        }[self]


@dataclass
class Message:
    """대화 한 턴의 메시지.

    error=True 는 앱이 만든 오류·설정 안내(예: 키 미설정)다. 화면에는 보이지만,
    실제 어시스턴트 발화가 아니므로 다음 턴의 LLM 맥락에서는 제외한다. (F1-2 충실도)
    """

    role: str   # "user" | "assistant"
    content: str
    error: bool = False


@dataclass
class Conversation:
    """하나의 대화 세션. 직전 맥락을 유지한다(F1-2). 원본을 보관한다(F1-4)."""

    intent: Intent
    messages: list = field(default_factory=list)  # list[Message]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


# ── 시스템 프롬프트(Co-Planner 페르소나 + 의도별 안내) ──────────────
_BASE_SYSTEM = """당신은 'Co-Planner'입니다. 해야 할 일을 알아도 시작하지 못하는 사람\
(ADHD 성향 포함)이 뒤섞인 생각을 실행 가능한 행동으로 바꾸고, 죄책감 없이 '지금 할 첫 단계'에\
착수하도록 돕습니다.

지켜야 할 원칙:
- 따뜻하고 담백한 한국어로, 짧고 부담 없게 말합니다. 한 번에 너무 많은 내용을 쏟아내지 않습니다.
- 결정권은 늘 사용자에게 있습니다. 당신은 선택지와 제안을 줄 뿐, 대신 확정하지 않습니다.
- 미완료나 밀린 일로 사용자를 탓하거나 죄책감을 주지 않습니다. 언제든 다시 시작하도록 격려합니다.
- 막연한 것은 작게 쪼개 '지금 할 수 있는 가장 작은 한 걸음'으로 좁혀 줍니다.
- 확인이 필요하면 한 번에 하나씩, 고르기 쉬운 형태(이지선다 등)로 가볍게 묻습니다."""

_INTENT_SYSTEM = {
    Intent.BRAIN_DUMP: (
        "지금은 '브레인덤프' 모드입니다. 사용자가 머릿속을 자유롭게 쏟아내도록 편하게 받아줍니다. "
        "들은 내용을 가볍게 정리해 비춰 주되, 아직 할 일 목록을 강요하지 않습니다. "
        "사용자가 원하면 실행 가능한 후보를 부담 없는 분량으로 몇 개만 짚어 줍니다."
    ),
    Intent.BREAKDOWN: (
        "지금은 '쪼개기' 모드입니다. 목표만 있는 큰 일을 함께 구체화합니다. "
        "왜 하는지·언제까지인지 등 꼭 필요한 맥락을 한 번에 하나씩 이지선다로 가볍게 묻고, "
        "준비가 되면 작은 실행 단위와 '지금 할 첫 단계' 하나를 이야기해 줍니다."
    ),
    Intent.SINGLE_ADD: (
        "지금은 '한 줄 추가' 모드입니다. 사용자의 한 문장에서 할 일 하나를 이해합니다. "
        "정보가 부족할 때만 꼭 필요한 최소한만 되묻고(과도한 질문 금지), 여러 개로 늘리지 않습니다."
    ),
    Intent.SITUATION: (
        "지금은 '상황 공유' 모드입니다. 바뀐 상황·에너지 상태를 듣고, 지금 하기 좋은 일 하나를 "
        "이유와 함께 제안합니다. 제안은 즉시 실행 가능한 단위로, 에너지에 맞춰 부하를 조절합니다."
    ),
}


def system_prompt(intent: Intent) -> str:
    """의도에 맞춘 Co-Planner 시스템 프롬프트를 만든다."""
    return _BASE_SYSTEM + "\n\n" + _INTENT_SYSTEM[intent]


def _context_messages(conversation: Conversation) -> list:
    """대화에서 LLM 에 넘길 맥락을 만든다.

    - 앱이 만든 오류·안내(error=True)는 제외한다 — 어시스턴트가 실제로 한 말이 아니므로
      맥락을 오염시키지 않는다. (F1-2 충실도)
    - 같은 역할이 연달아 오면 하나로 합친다(직전 턴이 오류였을 때 user 가 연달아 붙는 경우 등).
      OpenAI·Anthropic 모두에서 안전한 형태(역할 교대)로 정규화한다.
    """
    messages: list = []
    for m in conversation.messages:
        if m.error:
            continue
        if messages and messages[-1]["role"] == m.role:
            messages[-1]["content"] += "\n" + m.content
        else:
            messages.append({"role": m.role, "content": m.content})
    return messages


def respond(conversation: Conversation) -> str:
    """직전 맥락 전체를 넘겨 Co-Planner의 다음 응답을 생성한다. (F1-1, F1-2)

    오류 안내를 뺀 실제 대화 맥락만 LLM 에 전달해 연속성을 지킨다.
    LLM 설정 문제(LLMConfigError)나 호출 실패는 상위(app.py)에서 잡아 안내로 바꾼다.
    """
    llm_messages = _context_messages(conversation)
    return call_llm(messages=llm_messages, system=system_prompt(conversation.intent))


def route(intent: Intent, user_text: str) -> Proposal:
    """의도에 따라 구조화 기능(F2~F5)으로 입력을 전달한다.

    F1 대화 인터페이스는 respond() 로 대화를 이어가고, 할 일 후보·분해·제안 등
    '확정 대상(Proposal)'이 필요할 때 이 진입점을 통해 각 기능을 호출한다.
    (F2~F5 구현 시 여기서 연결한다.)

    F2~F5 모듈은 여기서 지연 임포트한다 — 아직 스텁인 그 모듈들이 F1 로드 경로(app.py)에
    묶이지 않게 하여, 개발 중 한 모듈이 깨져도 메인 화면은 영향받지 않게 한다.
    """
    from features import brain_dump, breakdown, single_add, suggest

    if intent is Intent.BRAIN_DUMP:
        return brain_dump.extract(user_text)
    if intent is Intent.BREAKDOWN:
        # 쪼개기는 구체화(질문)→분해로 이어지는 여러 턴 흐름이라 app.py 가 breakdown.start/
        # decompose 를 직접 몰아준다(F3). route()는 구체화를 건너뛴 단발 분해 진입점만 제공한다.
        return breakdown.decompose(user_text)
    if intent is Intent.SINGLE_ADD:
        return single_add.parse(user_text)
    return suggest.suggest_now(user_text)


def save_conversation(conversation: Conversation) -> None:
    """대화 원본을 메모리에 보관한다. 언제든 열람 가능. (F1-4)"""
    st.session_state[CONVERSATIONS].append(conversation)


def list_conversations() -> list:
    """저장된 대화 전체를 반환한다. (F1-4)"""
    return st.session_state.get(CONVERSATIONS, [])
