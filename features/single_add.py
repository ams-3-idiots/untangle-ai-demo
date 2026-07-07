"""F4 — 단일 할 일 추가(AI). 자연어 한 문장에서 속성을 추출해 한 건을 만든다."""

from __future__ import annotations

from features.confirm import Proposal
from features.todo import Todo


def parse(sentence: str) -> Proposal:
    """한 문장에서 속성(제목·날짜·시간·우선순위·반복)을 추출한다. (F4-2)

    - 정보가 모호·부족하면 최소 항목만 확인한다(과도한 질문 금지). (F4-3)
    - 한 문장 입력 = 한 할 일. 다수 후보를 만들지 않는다(브레인덤프와 분리). (F4-5)
    """
    # TODO(F4): features.call_llm 으로 속성 추출(날짜/시간/우선순위/반복)
    todo = Todo(title=sentence.strip(), source="single_add")
    return Proposal(drafts=[todo], source="single_add")
