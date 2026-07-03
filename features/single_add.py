"""F4 — 단일 할 일 추가(AI). 자연어 한 문장에서 속성을 추출해 한 건을 만든다.

담당 요구사항 (docs/FEATURES.md §4):
- F4-1 사용자는 자연어 한 문장으로 단일 할 일을 추가한다. (입력 수집은 app.py, 여기선 텍스트를 받는다)
- F4-2 입력에서 속성(제목·날짜·시간·우선순위·반복)을 추출해 채운다. (LLM 단일 통로 call_llm)
- F4-3 정보가 모호·부족하면 필요한 최소 항목만 '질문으로' 확인한다(과도한 질문 금지).
       → 할 일 내용(제목)이 모호해 그대로 담으면 엉뚱해질 때만, 있을 법한 해석을 이지선다로 한두 개만
       되묻는다. 단서가 '없을 뿐'인 선택 속성(날짜·시간·우선순위·반복)은 묻지 않고 비워 둔 채 확정
       패널에서 사용자가 채운다.
- F4-4 추출 결과는 사용자 확정 후에만 반영된다. (commit_edited / confirm, GP-1)
- F4-5 한 문장 입력 = 한 할 일. 다수 후보를 만들지 않는다(브레인덤프와 분리).

이 모듈은 로직만 담는다(레이어 규칙): Streamlit 위젯을 그리지 않고, 입력은 인자·출력은
Proposal / SingleAddSession / Todo 로만 주고받는다. 다만 되묻기(F4-3)는 여러 턴에 걸친 상태를
가지므로, F3 breakdown 처럼 진행 상태를 session_state(SINGLE_ADD 키)에 보관한다. call_llm 설정/호출
오류(LLMConfigError 등)는 잡지 않고 그대로 올려 화면(app.py)에서 안내 메시지로 바꾼다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional

import streamlit as st

from features import SINGLE_ADD, call_llm
from features.confirm import Proposal, clear_pending
from features.todo import Todo, add_todo, priority_value

MAX_QUESTIONS = 2  # 되묻기는 최대 2개까지만 — 필요한 최소 항목만(과도한 질문 금지, F4-3)

# 할 일로 볼 수 없는 입력(감정·상태·질문·빈 문장)에 대한 재입력 안내 (F4-1)
_REPROMPT = (
    "추가할 할 일을 찾지 못했어요. '무엇을 한다'처럼 한 문장으로 또렷하게 적어줄래요? "
    '(예: "내일 오후 3시 치과 예약 전화하기")'
)

# 추출기 시스템 프롬프트. Co-Planner 페르소나가 아니라 '한 건 추출 전용' 규칙을 준다.
# 한 문장 = 한 할 일(F4-5), 단서 있는 속성만 채우고(과도한 추정 금지), 꼭 필요할 때만 되묻고(F4-3),
# JSON 만 반환한다.
_SYSTEM = """당신은 자연어 한 문장에서 '할 일 한 건'과 그 속성을 뽑아내는 추출기입니다.
사용자가 적은 말을 읽고, 하나의 할 일과 제목·날짜·시간·우선순위·반복을 채웁니다.

추출 규칙:
- 반드시 '할 일 하나'만 만듭니다. 여러 일이 섞여 있어도 가장 핵심 하나만 뽑고, 여러 개로 늘리지 않습니다.
- title: 짧고 실행 가능한 한 줄. 되도록 동사로 끝맺습니다. 날짜·시각 표현은 제목에서 덜어냅니다. (예: "치과 예약 전화하기")
- due_date: 예정/마감 날짜를 "YYYY-MM-DD"로. 주어진 '오늘'을 기준으로 '내일·이번 주 금요일' 같은 상대 표현을 실제 날짜로 환산합니다. 날짜 단서가 없으면 null.
- due_time: 시각을 24시간 "HH:MM"으로. '오후 3시'→"15:00". 시각 단서가 없으면 null.
- priority: 문장에 드러난 중요도만 "높음"·"중간"·"낮음" 중 하나로 정합니다.('급함·꼭·중요'는 높음 등) 단서가 없으면 "없음".
- recurrence: 반복 표현이 있으면 짧은 한국어로 적습니다.("매일"·"매주 월요일"·"매월 1일") 없으면 null.
- 문장에 단서가 없는 속성은 지어내지 않습니다. 반드시 null(또는 우선순위는 "없음")로 둡니다. (과도한 추정 금지)

되물을 질문(questions) — 필요한 최소 항목만, 과도한 질문 금지:
- 기본값은 빈 배열([])입니다. 제목이 이미 또렷하면 절대 되묻지 않습니다. 대부분의 입력은 그대로 담깁니다.
- 단서가 '없을 뿐'인 선택 속성(날짜·시간·우선순위·반복)은 절대 묻지 않습니다. 비워 두면 사용자가 확정 화면에서 직접 채웁니다.
- 다만 '할 일 같긴 한데 무슨 행동인지'가 모호한 입력(예: "병원", "엄마", "그거 처리")은 그대로 담으면 엉뚱해집니다.
  이때만 title 에 가장 그럴듯한 잠정 제목을 넣고, questions 에 있을 법한 행동 2~4개를 '선택지(options)'로 담아 한 개(최대 두 개)만 되묻습니다.
- 선택지는 서로 뚜렷이 다르고 실제 있을 법한 것으로 씁니다. 사용자가 직접 답할 수도 있으니 '기타'는 넣지 않습니다.
- 질문·선택지는 짧고 담백한 한국어로 씁니다.

정말로 할 일이 아닌 입력만 거절합니다:
- 감정·상태·인사·잡담·순수 질문(예: "너무 피곤해", "안녕", "이거 뭐지?", 빈 문장)이면 title 을 빈 문자열("")로 둡니다.
- 무언가 하려는 낌새가 조금이라도 있으면 거절하지 말고, 잠정 제목 + 되묻기로 살립니다.

출력은 아래 JSON '그대로만' 내보냅니다. 코드펜스나 설명 문장을 덧붙이지 않습니다.
명확: {"title": "치과 예약 전화하기", "due_date": "2026-07-03", "due_time": "15:00", "priority": "높음", "recurrence": null, "memo": "", "questions": []}
모호(되묻기): {"title": "병원 일 처리하기", "due_date": null, "due_time": null, "priority": "없음", "recurrence": null, "memo": "", "questions": [{"question": "어떤 걸 하려는 거예요?", "options": ["병원 예약 전화하기", "진료 받으러 가기", "서류 떼러 가기"]}]}
할 일 아님: {"title": ""}"""


# ── 되묻기 세션 상태(여러 턴에 걸친 진행) ──────────────────────────
@dataclass
class Question:
    """되묻기용 이지선다 질문 하나. (F4-3)"""

    question: str
    options: list = field(default_factory=list)  # list[str] — 고르기 쉬운 선택지 2~4개


@dataclass
class SingleAddSession:
    """진행 중인 한 줄 추가 세션. 원문·잠정 추출·되물을 질문·답을 보관한다. (F4-3)

    - draft: 지금까지의 최선 추출(없으면 None = '할 일 아님').
    - questions: 확인할 이지선다 질문. 비어 있으면 되묻지 않고 바로 확정 패널로 간다.
    - cursor 가 questions 끝에 도달하면 확인이 끝난 것으로 본다(한 번에 하나씩 물어본다).
    - note: '할 일 아님'일 때 재입력 안내 문구.
    """

    sentence: str
    draft: Optional[Todo] = None
    questions: list = field(default_factory=list)   # list[Question]
    answers: dict = field(default_factory=dict)      # {질문: 고른/적은 답}
    cursor: int = 0                                   # 지금 물어볼 질문 인덱스
    note: str = ""


# ── 세션 상태 접근자 (breakdown 의 get/set/clear 와 같은 역할) ──────
def get_session() -> Optional[SingleAddSession]:
    """진행 중인 한 줄 추가 세션을 반환한다(없으면 None)."""
    return st.session_state.get(SINGLE_ADD)


def set_session(session: SingleAddSession) -> None:
    """한 줄 추가 세션을 저장한다(되묻기 진행 상태 보관)."""
    st.session_state[SINGLE_ADD] = session


def clear_session() -> None:
    """한 줄 추가 세션을 비운다(확정·취소·새 대화 시)."""
    st.session_state[SINGLE_ADD] = None


# ── 되묻기 진행 제어 (F4-3) ───────────────────────────────────────
def is_clarifying(session: SingleAddSession) -> bool:
    """아직 물어볼 확인 질문이 남았는지."""
    return session.cursor < len(session.questions)


def current_question(session: SingleAddSession) -> Optional[Question]:
    """지금 물어볼 질문(없으면 None)."""
    return session.questions[session.cursor] if is_clarifying(session) else None


def answer(session: SingleAddSession, choice: str) -> None:
    """현재 질문에 대한 답(고른 선택지 또는 직접 입력)을 기록하고 다음으로 넘어간다."""
    q = current_question(session)
    if q is None:
        return
    if choice and choice.strip():
        session.answers[q.question] = choice.strip()
    session.cursor += 1


def skip_all(session: SingleAddSession) -> None:
    """남은 질문을 모두 건너뛴다. (F4-3 — 되묻기 없이 지금 정보로 바로 확정 패널로)"""
    session.cursor = len(session.questions)


# ── 1단계: 속성 추출 + (필요하면) 되물을 질문 생성 (F4-2, F4-3) ─────
def start(sentence: str, *, today: Optional[date] = None) -> SingleAddSession:
    """한 문장에서 속성을 추출하고, 최소 항목이 모호하면 되물을 질문을 만든다. (F4-2, F4-3)

    - 상대 날짜('내일' 등) 환산 기준일을 today 로 주입할 수 있다(기본 date.today()).
    - questions 가 비어 있으면 되묻기 불필요 → 화면(app.py)이 바로 확정 패널을 연다.
    - questions 가 있으면 화면이 한 번에 하나씩 물어보고, 답을 answer()로 기록한 뒤 build_proposal 로 마무리한다.
    - 할 일로 볼 수 없는 입력(감정·질문·빈 문장)이면 draft=None + 재입력 안내(note). (F4-1)
    - 반영 여부는 사용자에게 남긴다 — 여기선 확정 없이 후보/질문만 만든다. (F4-4, GP-1)
    """
    sentence = (sentence or "").strip()
    if not sentence:
        return SingleAddSession(sentence="", note=_REPROMPT)

    today = today or date.today()
    raw = call_llm(
        prompt=_user_prompt(sentence, today),
        system=_SYSTEM,
        temperature=0.2,   # 추출은 안정성이 중요 — 낮은 온도
        max_tokens=500,
    )
    data = _parse_json(raw)
    todo = _to_todo(data)
    questions = _to_questions(data)
    if todo is None:
        if questions:
            # '할 일 같긴 한데 행동이 모호' — 제목을 비워 왔어도 되물어 살린다. 잠정 제목은 원문.
            # (사용자가 되묻기를 건너뛰면 이 원문을 확정 패널에서 직접 다듬을 수 있다, GP-1)
            todo = Todo(title=sentence, source="single_add")
        else:  # F4-1: 정말로 할 일이 아님 → 재입력 안내
            return SingleAddSession(sentence=sentence, note=_REPROMPT)
    return SingleAddSession(sentence=sentence, draft=todo, questions=questions)


# ── 2단계: 확정 후보(Proposal) 만들기 ─────────────────────────────
def to_proposal(session: SingleAddSession) -> Proposal:
    """세션의 최선 추출을 그대로 확정 후보로 만든다(되묻기 없이/건너뛰고 갈 때). (F4-5)

    draft 가 없으면(할 일 아님) 빈 제안 + 재입력 안내를 돌려준다. (F4-1)
    """
    if session.draft is None:
        return Proposal(drafts=[], note=session.note or _REPROMPT, source="single_add")
    return Proposal(drafts=[session.draft], source="single_add")  # F4-5: 정확히 한 건


def build_proposal(session: SingleAddSession, *, today: Optional[date] = None) -> Proposal:
    """되묻기 답을 반영해 최종 한 건의 확정 후보를 만든다. (F4-2, F4-3, F4-5)

    - 답이 없으면(모두 건너뜀) 다시 LLM 을 부르지 않고 최선 추출(draft)을 그대로 쓴다.
    - 답이 있으면 원문 + 확인 내용을 함께 넘겨 최종 한 건을 다시 추출한다(F3 decompose 와 같은 방침).
      재추출이 실패하면 최선 추출로 안전하게 폴백한다.
    - 반영 여부는 사용자에게 남긴다 — 여기선 확정 없이 후보만 만든다. (F4-4, GP-1)
    """
    picked = {q: a for q, a in session.answers.items() if a and a.strip()}
    if not picked:
        return to_proposal(session)

    today = today or date.today()
    raw = call_llm(
        prompt=_user_prompt(session.sentence, today, picked),
        system=_SYSTEM,
        temperature=0.2,
        max_tokens=500,
    )
    todo = _to_todo(_parse_json(raw))
    if todo is None:  # 재추출 실패 → 최선 추출로 폴백(유실 방지)
        return to_proposal(session)
    return Proposal(drafts=[todo], source="single_add")


def parse(sentence: str, *, today: Optional[date] = None) -> Proposal:
    """한 문장에서 '한 건'의 할 일 제안을 만드는 단발 진입점. (F4-2, F4-5)

    coplanner.route() 같은 비대화 경로용 — 되묻기(F4-3)를 진행할 수 없으므로 질문은 무시하고
    최선 추출을 그대로 후보로 돌려준다. 대화형 되묻기 흐름은 app.py 가 start/build_proposal 로 몬다.
    """
    return to_proposal(start(sentence, today=today))


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
    add_todo(todo)     # 실행 데이터에 반영 (F4-4, F6-2)
    clear_pending()    # 확정했으니 대기 제안 정리
    clear_session()    # 되묻기 세션도 정리
    return todo


# ── 프롬프트/파싱 유틸 ────────────────────────────────────────────
_WEEKDAYS = "월화수목금토일"


def _user_prompt(sentence: str, today: date, clarifications: Optional[dict] = None) -> str:
    """추출 LLM 에 넘길 사용자 프롬프트(오늘 날짜 + 문장 + 확인 내용)를 만든다.

    상대 날짜('내일' 등)를 실제 날짜로 환산하려면 기준일(오늘)이 필요하다.
    clarifications 가 있으면 되묻기 답을 함께 넘겨 최종 추출에 반영하게 한다(F4-3 마무리).
    """
    weekday = _WEEKDAYS[today.weekday()]
    lines = [f"오늘: {today.isoformat()} ({weekday})", f"문장: {sentence}"]
    if clarifications:
        lines.append("\n사용자가 확인해 준 내용:")
        lines.extend(f"- {q} → {a}" for q, a in clarifications.items())
        lines.append(
            "\n이 확인 내용을 반영해 최종 한 건을 추출하세요. "
            "더는 되묻지 말고 questions 는 빈 배열([])로 두세요."
        )
    return "\n".join(lines)


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


def _to_questions(data) -> list:
    """파싱된 JSON 에서 유효한 이지선다 되묻기 질문만 추린다. (F4-3)

    - _to_todo 와 똑같이 _unwrap 으로 배열/래퍼를 한 겹 푼다. LLM 이 {"todos":[{…questions…}]}·
      [{…}] 처럼 감싸 보내도 제목만 살고 질문이 통째로 유실돼 되묻기가 조용히 건너뛰어지는 것을 막는다.
    - questions 배열의 각 항목은 질문 문자열 + 선택지(2개 이상)가 모두 있어야 유효로 본다.
      (선택지를 못 만들 애매한 질문은 버려, 결국 되묻지 않고 확정 패널로 가게 한다 — 과도한 질문 금지)
    - 최대 MAX_QUESTIONS(2) 개까지만 남긴다.
    """
    container = _unwrap(data)
    if not isinstance(container, dict):
        return []
    raw_questions = container.get("questions")
    if not isinstance(raw_questions, list):
        return []

    questions: list = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        text = item.get("question")
        opts = item.get("options")
        if not isinstance(text, str) or not text.strip():
            continue
        if not isinstance(opts, list):
            continue
        clean = [o.strip() for o in opts if isinstance(o, str) and o.strip()]
        if len(clean) < 2:  # 이지선다는 최소 2개 선택지
            continue
        questions.append(Question(question=text.strip(), options=clean[:4]))
        if len(questions) >= MAX_QUESTIONS:
            break
    return questions


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
