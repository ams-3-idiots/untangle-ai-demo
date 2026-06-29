"""F3 — 쪼개기. 목표만 있는 큰 일을 질문으로 구체화한 뒤 작은 단위로 분해한다."""
from __future__ import annotations

from typing import Optional

from features.confirm import Proposal
from features.todo import Todo


def clarifying_questions(goal: str) -> list[str]:
    """실행에 필요한 맥락을 묻는 질문을 만든다. (F3-2)

    사용자는 이 질문을 건너뛰고도 진행할 수 있어야 한다. (F3-3)
    """
    # TODO(F3): features.call_llm 으로 맥락 질문 생성
    return ["언제까지 끝내야 하나요?", "지금 가진 자료나 도구가 있나요?"]


def decompose(goal: str, answers: Optional[dict] = None) -> Proposal:
    """큰 일을 작은 단위로 분해하고 '지금 할 첫 단계'를 함께 제시한다. (F3-4, F3-5)

    answers 는 clarifying_questions 에 대한 답(선택). 없어도 진행한다(F3-3).
    재쪼개기(F3-6)는 분해 결과의 한 항목을 다시 이 함수에 넣어 처리한다.
    """
    # TODO(F3): features.call_llm 으로 분해 + 첫 단계 식별
    steps = [
        Todo(title=f"[첫 단계] {goal} — 가장 작은 시작 동작", source="breakdown"),
        Todo(title=f"{goal} — 다음 단계", source="breakdown"),
    ]
    return Proposal(drafts=steps, note="첫 단계부터 가볍게 시작해보세요.", source="breakdown")
