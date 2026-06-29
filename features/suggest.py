"""F5 — 대화형 안내·제안. 바뀐 상황·에너지에 맞춰 재정렬하고 '지금 할 일'을 제안한다."""
from __future__ import annotations

from features.confirm import Proposal
from features.todo import Todo, list_todos


def suggest_now(situation: str) -> Proposal:
    """현재 할 일과 전달된 상황을 바탕으로 '지금 할 일' 하나를 이유와 함께 제안한다.

    - 기존 당일 할 일을 재해석·재정렬한다. (F5-2)
    - 제안은 단일·즉시 실행 가능한 단위로 제시한다. (F5-3, F5-4)
    - 막연하면 첫 단계 수준까지 구체화한다(쪼개기 연계, F5-5).
    - 에너지 상태에 맞춰 난이도·부하를 조정한다. (F5-6)
    """
    # TODO(F5): features.call_llm 으로 재정렬 + 단일 제안(이유 포함)
    todos = list_todos()
    pick = todos[0] if todos else Todo(title="가장 작은 일 하나 고르기", source="suggest")
    return Proposal(
        drafts=[pick],
        note=f"'{situation}' 상황이라면, 지금은 이 일이 가장 하기 좋아요.",
        source="suggest",
    )
