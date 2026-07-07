"""F4 — 단일 할 일 추가(AI). 자연어 한 문장에서 속성을 추출해 한 건을 만든다.

담당 요구사항 (docs/FEATURES.md §4):
- F4-1 사용자는 자연어 한 문장으로 단일 할 일을 추가한다. (입력 수집은 app.py, 여기선 텍스트를 받는다)
- F4-2 입력에서 속성(제목·날짜·시간·우선순위·반복)을 추출해 채운다. (LLM 단일 통로 call_llm)
- F4-3 정보가 모호·부족하면 최소 항목만 확인한다(과도한 질문 금지). → 단서 없는 속성은 비워 두고,
       확정 패널에서 사용자가 필요한 것만 손본다. 별도 되묻기 대화는 하지 않는다.
- F4-4 추출 결과는 사용자 확정 후에만 반영된다. (commit_edited / confirm, GP-1)
- F4-5 한 문장 입력 = 한 할 일. 다수 후보를 만들지 않는다(브레인덤프와 분리).

이 모듈은 로직만 담는다(레이어 규칙): Streamlit 위젯을 그리지 않고, 입력은 인자·출력은
Proposal / Todo 로만 주고받는다. call_llm 설정/호출 오류(LLMConfigError 등)는 잡지 않고 그대로
올려 화면(app.py)에서 안내 메시지로 바꾼다. (F2·F3 모듈과 동일 방침)
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from typing import Optional

from features import call_llm
from features.confirm import Proposal, clear_pending
from features.todo import Todo, add_todo, priority_value

# 할 일로 볼 수 없는 입력(감정·상태·질문·빈 문장)에 대한 재입력 안내 (F4-1)
_REPROMPT = (
    "추가할 할 일을 찾지 못했어요. '무엇을 한다'처럼 한 문장으로 또렷하게 적어줄래요? "
    '(예: "내일 오후 3시 치과 예약 전화하기")'
)

# 추출기 시스템 프롬프트. Co-Planner 페르소나가 아니라 '한 건 추출 전용' 규칙을 준다.
# 한 문장 = 한 할 일(F4-5), 단서 있는 속성만 채우고(F4-3 과도한 추정 금지), JSON 만 반환.
_SYSTEM = """당신은 자연어 한 문장에서 '할 일 한 건'과 그 속성을 뽑아내는 추출기입니다.
사용자가 적은 한 문장을 읽고, 하나의 할 일과 제목·날짜·시간·우선순위·반복을 채웁니다.

추출 규칙:
- 반드시 '할 일 하나'만 만듭니다. 여러 일이 섞여 있어도 가장 핵심 하나만 뽑고, 여러 개로 늘리지 않습니다.
- title: 짧고 실행 가능한 한 줄. 되도록 동사로 끝맺습니다. 날짜·시각 표현은 제목에서 덜어냅니다. (예: "치과 예약 전화하기")
- due_date: 예정/마감 날짜를 "YYYY-MM-DD"로. 주어진 '오늘'을 기준으로 '내일·이번 주 금요일' 같은 상대 표현을 실제 날짜로 환산합니다. 날짜 단서가 없으면 null.
- due_time: 시각을 24시간 "HH:MM"으로. '오후 3시'→"15:00". 시각 단서가 없으면 null.
- priority: 문장에 드러난 중요도만 "높음"·"중간"·"낮음" 중 하나로 정합니다.('급함·꼭·중요'는 높음 등) 단서가 없으면 "없음".
- recurrence: 반복 표현이 있으면 짧은 한국어로 적습니다.("매일"·"매주 월요일"·"매월 1일") 없으면 null.
- 문장에 단서가 없는 속성은 지어내지 않습니다. 반드시 null(또는 우선순위는 "없음")로 둡니다. (과도한 추정 금지)
- 할 일로 볼 수 없는 입력(감정·상태·질문·빈 문장)이면 title 을 빈 문자열("")로 둡니다.

출력은 아래 JSON '그대로만' 내보냅니다. 코드펜스나 설명 문장을 덧붙이지 않습니다.
{"title": "치과 예약 전화하기", "due_date": "2026-07-03", "due_time": "15:00", "priority": "높음", "recurrence": null, "memo": ""}
할 일이 아니면 정확히 이렇게 답합니다: {"title": ""}"""


def parse(sentence: str, *, today: Optional[date] = None) -> Proposal:
    """한 문장에서 속성을 추출해 '한 건'의 할 일 제안을 만든다. (F4-2, F4-5)

    - 상대 날짜('내일' 등) 환산 기준일을 today 로 주입할 수 있다(기본 date.today()).
    - 할 일로 볼 수 없는 입력(감정·질문·빈 문장)이면 빈 제안 + 재입력 안내를 돌려준다. (F4-1)
    - 반영 여부는 사용자에게 남긴다 — 여기선 확정 없이 후보만 만든다. (F4-4, GP-1)
    """
    sentence = (sentence or "").strip()
    if not sentence:
        return Proposal(drafts=[], note=_REPROMPT, source="single_add")

    today = today or date.today()
    raw = call_llm(
        prompt=_user_prompt(sentence, today),
        system=_SYSTEM,
        temperature=0.2,  # 추출은 안정성이 중요 — 낮은 온도
        max_tokens=400,
    )
    todo = _to_todo(_parse_json(raw))
    if todo is None:  # F4-1: 할 일이 아님 → 빈 결과 + 재입력 안내
        return Proposal(drafts=[], note=_REPROMPT, source="single_add")
    return Proposal(drafts=[todo], source="single_add")  # F4-5: 정확히 한 건


def commit_edited(
    *,
    title: str,
    priority_label: str = "없음",
    due_date: Optional[date] = None,
    due_time: Optional[time] = None,
    recurrence: str = "",
    memo: str = "",
) -> Optional[Todo]:
    """확정 패널에서 사용자가 검토·수정한 단일 할 일을 오늘 할 일에 반영한다. (F4-4, GP-1)

    확정 처리는 features 안에서 한다(ARCHITECTURE: 확정은 features 로직).
    제목이 비면 아무것도 반영하지 않고 None 을 돌려준다(방어).
    """
    title = (title or "").strip()
    if not title:
        return None
    todo = Todo(
        title=title,
        memo=(memo or "").strip(),
        priority=priority_value(priority_label),
        due_date=due_date,
        due_time=due_time,
        recurrence=(recurrence or "").strip() or None,
        source="single_add",
    )
    add_todo(todo)  # 실행 데이터에 반영 (F4-4, F6-2)
    clear_pending()  # 확정했으니 대기 제안 정리
    return todo


# ── 프롬프트/파싱 유틸 ────────────────────────────────────────────
_WEEKDAYS = "월화수목금토일"


def _user_prompt(sentence: str, today: date) -> str:
    """추출 LLM 에 넘길 사용자 프롬프트(오늘 날짜 + 문장)를 만든다.

    상대 날짜('내일' 등)를 실제 날짜로 환산하려면 기준일(오늘)이 필요하다.
    """
    weekday = _WEEKDAYS[today.weekday()]
    return f"오늘: {today.isoformat()} ({weekday})\n문장: {sentence}"


def _parse_json(raw: str):
    """LLM 응답에서 JSON 을 최대한 안전하게 뽑아 파싱한다. (brain_dump/breakdown 과 동일 방침)

    코드펜스(```json …```)나 앞뒤 설명이 섞여도 본문의 JSON 을 찾아 파싱한다.
    실패하면 None 을 반환한다 → 빈 결과(재입력 안내)로 이어진다.
    """
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    candidate = (fenced.group(1) if fenced else raw).strip()
    try:
        return json.loads(candidate)
    except Exception:
        pass
    match = re.search(r"(\{.*\}|\[.*\])", candidate, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            return None
    return None


_TITLE_KEYS = ("title", "task", "todo", "name")
_MEMO_KEYS = ("memo", "note", "description")
_PRIORITY_KEYS = ("priority", "importance")
_DATE_KEYS = ("due_date", "date", "due")
_TIME_KEYS = ("due_time", "time")
_RECUR_KEYS = ("recurrence", "repeat", "recurring")


def _first_str(item: dict, keys) -> str:
    """딕셔너리에서 keys 순서대로 비어있지 않은 '문자열' 값을 찾아 돌려준다(없으면 "")."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# LLM 이 지시를 어기고 감싸서 보낼 수 있는 래퍼 키(형제 brain_dump._iter_items 와 같은 방침).
_WRAP_KEYS = ("todos", "tasks", "items", "candidates", "todo", "task")


def _unwrap(data):
    """배열/래퍼로 감싼 응답에서 단일 항목 dict 를 꺼낸다. (F4-5 견고성)

    프롬프트는 평면 객체 {"title": ...} 를 요구하지만, LLM 이 {"todos":[{…}]}·[{…}]·
    {"todo":{…}} 처럼 감싸 보내도 유효한 한 건을 '할 일 아님'으로 오판하지 않게 한 겹 푼다.
    """
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), None)
    if not isinstance(data, dict):
        return None
    # 제목 키가 문자열로 바로 있으면 그대로 단일 객체로 본다.
    if any(isinstance(data.get(k), str) and data.get(k).strip() for k in _TITLE_KEYS):
        return data
    # 아니면 알려진 래퍼 키를 한 겹 푼다(리스트면 첫 dict, dict면 그대로).
    for key in _WRAP_KEYS:
        val = data.get(key)
        if isinstance(val, list):
            item = next((x for x in val if isinstance(x, dict)), None)
            if item is not None:
                return item
        elif isinstance(val, dict):
            return val
    return data  # 래퍼가 없으면 원본 그대로(제목이 없으면 _to_todo 가 None 처리)


def _to_todo(data) -> Optional[Todo]:
    """파싱된 JSON 에서 단일 할 일 Todo 를 만든다. 제목이 없으면 None. (F4-2, F4-5)

    - 배열/래퍼로 감싸 와도 한 겹 풀어(_unwrap) 유효한 한 건을 살린다.
    - 제목이 없으면(할 일이 아님) None → 호출부가 재입력 안내로 잇는다.
    - 우선순위는 라벨→값으로, 날짜·시간은 안전 파싱한다(형식이 어긋나면 비운다).
    - 날짜·시간도 _first_str 로 문자열만 취해, LLM 이 이상한 타입을 넣어도 쓰레기 값을 만들지 않는다.
    """
    item = _unwrap(data)
    if not isinstance(item, dict):
        return None
    title = _first_str(item, _TITLE_KEYS)
    if not title:
        return None
    return Todo(
        title=title,
        memo=_first_str(item, _MEMO_KEYS),
        priority=priority_value(_first_str(item, _PRIORITY_KEYS)),
        due_date=_parse_date(_first_str(item, _DATE_KEYS)),
        due_time=_parse_time(_first_str(item, _TIME_KEYS)),
        recurrence=_first_str(item, _RECUR_KEYS) or None,
        source="single_add",
    )


def _parse_date(value) -> Optional[date]:
    """'YYYY-MM-DD' 계열 문자열을 date 로. 형식이 어긋나면 None(비움)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(value) -> Optional[time]:
    """'HH:MM' 계열 문자열을 time 으로. 형식이 어긋나면 None(비움)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None
