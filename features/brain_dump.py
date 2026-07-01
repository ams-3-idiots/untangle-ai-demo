"""F2 — 브레인덤프. 뒤섞인 생각에서 실행 가능한 할 일 후보를 추출한다.

담당 요구사항: F2-1 ~ F2-5 (docs/FEATURES.md §2)
- 자유로운 긴 입력을 받아(F2-1) 실행 가능한 할 일 후보를 추출한다(F2-2).
- 결과는 5개 이하로 제시하고(F2-3), 추출이 어려우면 빈 결과와 재입력 안내를 준다(F2-4).
- 확정 전에는 데이터에 반영하지 않고 Proposal(확정 대기)만 만든다. 반영 여부는 사용자가 정한다(F2-5, GP-1).
"""
from __future__ import annotations

import json

import features
from features.confirm import Proposal
from features.todo import Todo

MAX_TODOS = 5  # 한눈에 부담 없는 분량 (F2-3)

_SYSTEM = (
    "너는 ADHD 성향 사용자를 돕는 한국어 코플래너야. "
    "사용자가 뒤섞인 생각을 쏟아내면, 그 안에서 '지금 바로 실행할 수 있는' 작은 할 일만 골라낸다. "
    "부담을 주지 않도록 개수는 최대 5개로 제한하고, 각 할 일은 동사로 시작하는 구체적인 행동으로 쓴다. "
    "추상적인 다짐·감정·모호한 목표는 할 일로 만들지 않는다."
)

_INSTRUCTION = (
    "아래 사용자의 생각에서 실행 가능한 할 일 후보를 최대 {max}개까지 뽑아줘.\n"
    "- 각 항목은 title(동사로 시작하는 구체적 행동)과 note(한 줄 보충 설명, 없으면 빈 문자열)로 구성한다.\n"
    "- 실행 가능한 할 일을 하나도 뽑기 어렵다면 todos 를 빈 배열([])로 두고, "
    "reason 에 무엇을 더 구체적으로 적으면 좋을지 한국어로 부드럽게 안내한다.\n"
    "- 반드시 아래 JSON 형식으로만 답한다. 코드펜스나 다른 설명 텍스트는 넣지 않는다.\n"
    '{{"todos": [{{"title": "...", "note": "..."}}], "reason": "..."}}\n\n'
    "사용자의 생각:\n{text}"
)


def extract(text: str) -> Proposal:
    """자유로운 생각 입력에서 할 일 후보를 추출해 제안으로 만든다. (F2-2)

    - 결과는 5개 이하로 제한한다. (F2-3)
    - 추출이 어려우면(추상적·비실행적) 빈 제안과 재입력 안내를 반환한다. (F2-4)
    - 확정 전에는 데이터에 반영하지 않는다(Proposal 만 만든다). (F2-5, GP-1)
    """
    text = (text or "").strip()
    if not text:
        return Proposal(
            drafts=[],
            note="생각을 조금만 적어주면 할 일로 정리해 볼게요.",
            source="brain_dump",
        )

    try:
        raw = features.call_llm(
            _INSTRUCTION.format(max=MAX_TODOS, text=text), system=_SYSTEM
        )
        data = _parse(raw)
    except Exception:
        # 키 미설정·네트워크·응답 파싱 실패 등 — 앱을 죽이지 않고 안내로 대체한다.
        return Proposal(
            drafts=[],
            note="지금은 AI 정리를 불러오지 못했어요. API 키 설정을 확인하거나 잠시 후 다시 시도해 주세요.",
            source="brain_dump",
        )

    drafts: list[Todo] = []
    for item in data.get("todos") if isinstance(data.get("todos"), list) else []:
        if isinstance(item, dict):
            title = str(item.get("title", "")).strip()
            memo = str(item.get("note", "")).strip()
        else:
            title, memo = str(item).strip(), ""
        if not title:
            continue
        drafts.append(Todo(title=title, memo=memo, source="brain_dump"))
        if len(drafts) >= MAX_TODOS:  # 5개 이하 보장 (F2-3)
            break

    if not drafts:  # 추출이 어려운 입력 — 빈 결과 + 재입력 안내 (F2-4)
        reason = str(data.get("reason", "")).strip()
        note = reason or "실행 가능한 할 일을 찾기 어려워요. 하고 싶은 '행동' 위주로 조금 더 구체적으로 적어줄래요?"
        return Proposal(drafts=[], note=note, source="brain_dump")

    return Proposal(
        drafts=drafts,
        note="이런 할 일들을 뽑아봤어요. 실제로 추가할 항목만 골라서 확정해 주세요.",
        source="brain_dump",
    )


def _parse(raw: str) -> dict:
    """LLM 응답 문자열에서 JSON 객체를 뽑아 파싱한다(코드펜스·잡텍스트 방어)."""
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("응답에서 JSON 객체를 찾지 못했습니다.")
    result = json.loads(text[start : end + 1])
    if not isinstance(result, dict):
        raise ValueError("JSON 객체 형식이 아닙니다.")
    return result
