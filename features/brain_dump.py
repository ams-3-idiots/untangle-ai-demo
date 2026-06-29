"""F2 — 브레인덤프. 뒤섞인 생각에서 실행 가능한 할 일 후보를 추출한다."""
from __future__ import annotations

from features.confirm import Proposal
from features.todo import Todo

MAX_TODOS = 5  # 한눈에 부담 없는 분량 (F2-3)


def extract(text: str) -> Proposal:
    """자유로운 생각 입력에서 할 일 후보를 추출해 제안으로 만든다. (F2-2)

    - 결과는 5개 이하로 제한한다. (F2-3)
    - 추출이 어려우면(추상적·비실행적) 빈 제안을 반환한다. (F2-4)
    """
    # TODO(F2): features.call_llm 으로 실제 추출 로직 구현
    drafts = [
        Todo(title=line.strip(), source="brain_dump")
        for line in text.splitlines()
        if line.strip()
    ][:MAX_TODOS]
    note = "" if drafts else "실행 가능한 할 일을 찾기 어려워요. 좀 더 구체적으로 적어줄래요?"
    return Proposal(drafts=drafts, note=note, source="brain_dump")
