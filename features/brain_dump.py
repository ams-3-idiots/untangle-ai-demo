"""F2 — 브레인덤프. 뒤섞인 생각에서 실행 가능한 할 일 후보를 추출한다.

담당 요구사항 (docs/FEATURES.md §2):
- F2-1 사용자는 정리되지 않은 긴 생각을 한 번에 입력한다. (입력 수집은 app.py, 여기선 텍스트를 받는다)
- F2-2 입력에서 실행 가능한 할 일 후보를 추출한다. (LLM 단일 통로 call_llm 사용)
- F2-3 추출 결과는 부담 없는 분량 — 5개 이하. (MAX_TODOS)
- F2-4 추출이 어려운(추상적·비실행적) 입력엔 빈 결과 + 재입력 안내 텍스트를 돌려준다.
- F2-5 어떤 후보를 실제 목록에 담을지는 사용자가 결정한다. (확정은 confirm 모듈이 담당, GP-1)

이 모듈은 로직만 담는다(레이어 규칙): Streamlit 위젯을 그리지 않고, 입력은 인자·출력은
Proposal 로만 주고받는다. call_llm 설정/호출 오류(LLMConfigError 등)는 잡지 않고 그대로 올려
화면(app.py)에서 안내 메시지로 바꾸게 한다. (F1 respond() 경로와 동일한 방침)
"""
from __future__ import annotations

import json
import re

from features import call_llm
from features.confirm import Proposal
from features.todo import Todo

MAX_TODOS = 5  # 한눈에 부담 없는 분량 (F2-3)

# 추출이 어려운 입력에 대한 재입력 안내 (F2-4)
_REPROMPT = (
    "실행 가능한 할 일을 찾기 어려웠어요. 지금 마음에 걸리는 일을 "
    "'무엇을 · 어떻게' 정도로 조금만 더 구체적으로 적어줄래요?"
)

# 추출기 시스템 프롬프트. Co-Planner 페르소나가 아니라 '추출 전용' 규칙을 준다.
# 실행 가능한 후보만, 5개 이하로, 없으면 빈 목록으로, JSON 만 반환하도록 강하게 못 박는다.
_SYSTEM = """당신은 뒤섞인 생각에서 '실행 가능한 할 일'만 골라내는 추출기입니다.
사용자가 머릿속을 자유롭게 쏟아낸 글을 읽고, 그 안에 실제로 담긴 할 일 후보를 뽑습니다.

추출 규칙:
- 구체적이고 바로 착수할 수 있는 행동만 뽑습니다. 짧은 한 줄로, 되도록 동사로 끝맺습니다. (예: "치과 예약 전화하기")
- 막연한 감정·상태·바람(예: "불안하다", "정리 좀 하고 싶다")은 할 일이 아니므로 뽑지 않습니다.
- 글에 실제로 드러난 일만 뽑습니다. 없는 일을 지어내지 않습니다.
- 하나의 큰 목표는 그대로 한 줄로 두고 잘게 쪼개지 않습니다. (쪼개기는 다른 기능이 합니다)
- 비슷하거나 겹치는 항목은 하나로 합칩니다.
- 최대 5개까지만 뽑습니다. 후보가 더 많으면 지금 손대기 좋은 것부터 5개를 고릅니다.
- 실행 가능한 할 일이 하나도 없으면 빈 목록을 반환합니다.

memo 에는 꼭 필요할 때만 아주 짧은 보충(맥락·마감 등)을 적고, 없으면 빈 문자열로 둡니다.

출력은 아래 JSON 형식 '그대로만' 내보냅니다. 코드펜스나 설명 문장을 덧붙이지 않습니다.
{"todos": [{"title": "치과 예약 전화하기", "memo": ""}]}
실행 가능한 할 일이 없으면 정확히 이렇게 답합니다: {"todos": []}"""


def extract(text: str) -> Proposal:
    """자유로운 생각 입력에서 할 일 후보를 추출해 제안(Proposal)으로 만든다. (F2-2)

    - 결과는 5개 이하로 제한한다. (F2-3)
    - 추출이 어려우면(추상적·비실행적) 빈 제안 + 재입력 안내를 반환한다. (F2-4)
    - 반영 여부는 사용자에게 남긴다 — 여기선 확정 없이 후보만 만든다. (F2-5, GP-1)
    """
    text = (text or "").strip()
    if not text:
        # 빈 입력은 호출 없이 곧바로 재입력 안내. (방어)
        return Proposal(drafts=[], note=_REPROMPT, source="brain_dump")

    raw = call_llm(
        prompt=text,
        system=_SYSTEM,
        temperature=0.3,   # 추출은 안정성이 중요 — 낮은 온도
        max_tokens=800,
    )
    drafts = _to_drafts(_parse_json(raw))
    note = "" if drafts else _REPROMPT  # F2-4: 빈 결과엔 재입력 안내
    return Proposal(drafts=drafts, note=note, source="brain_dump")


# ── 파싱 유틸 (LLM 출력 방어) ─────────────────────────────────────
def _parse_json(raw: str):
    """LLM 응답에서 JSON 을 최대한 안전하게 뽑아 파싱한다.

    코드펜스(```json …```)나 앞뒤 설명이 섞여도 본문의 JSON 을 찾아 파싱한다.
    실패하면 None 을 반환한다 → 빈 결과(F2-4)로 이어진다.
    """
    if not raw:
        return None

    # 1) 코드펜스가 있으면 그 안쪽만 취한다.
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    candidate = (fenced.group(1) if fenced else raw).strip()

    # 2) 통째로 파싱 시도.
    try:
        return json.loads(candidate)
    except Exception:
        pass

    # 3) 본문에서 첫 JSON 객체/배열 블록만 잘라 재시도.
    match = re.search(r"(\{.*\}|\[.*\])", candidate, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            return None
    return None


_TITLE_KEYS = ("title", "task", "todo", "name")
_MEMO_KEYS = ("memo", "note", "reason", "description")


def _iter_items(data):
    """파싱 결과에서 후보 항목 리스트를 꺼낸다.

    {"todos": [...]} 형태와 바로 [...] 형태를 모두 받아들인다.
    다른 키 이름(tasks/items/candidates)도 관대하게 허용하고,
    래핑 없이 단일 할 일 객체({"title": ...})만 온 경우도 한 항목으로 취급한다.
    """
    if isinstance(data, dict):
        for key in ("todos", "tasks", "items", "candidates"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        if any(k in data for k in _TITLE_KEYS):
            return [data]  # 단일 객체를 통째로 버리지 않는다
        return []
    if isinstance(data, list):
        return data
    return []


def _first_str(item: dict, keys) -> str:
    """딕셔너리에서 keys 순서대로 비어있지 않은 '문자열' 값을 찾아 돌려준다(없으면 "")."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _title_memo(item):
    """후보 한 항목에서 (제목, 메모)를 뽑는다. 문자열·딕셔너리 모두 허용.

    제목·메모는 '문자열' 값만 받아들인다. LLM 이 리스트·숫자 등 이상한 타입을 넣어도
    쓰레기 제목을 만들지 않는다(문자열이 아니면 제목이 비어 _to_drafts 에서 버려진다).
    """
    if isinstance(item, str):
        return item.strip(), ""
    if isinstance(item, dict):
        return _first_str(item, _TITLE_KEYS), _first_str(item, _MEMO_KEYS)
    return "", ""


def _to_drafts(data) -> list[Todo]:
    """파싱된 JSON 에서 유효한 후보만 추려 Todo 리스트로 만든다. (F2-2, F2-3)

    - 제목이 빈 항목은 버린다.
    - 제목 기준 중복(대소문자 무시)을 제거한다.
    - MAX_TODOS(5) 개를 넘지 않는다. (F2-3)
    """
    drafts: list[Todo] = []
    seen = set()
    for item in _iter_items(data):
        title, memo = _title_memo(item)
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        drafts.append(Todo(title=title, memo=memo, source="brain_dump"))
        if len(drafts) >= MAX_TODOS:  # 부담 없는 분량 (F2-3)
            break
    return drafts
