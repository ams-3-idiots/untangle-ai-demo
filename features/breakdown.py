"""F3 — 쪼개기. 목표만 있는 큰 일을 질문으로 구체화한 뒤 작은 단위로 분해한다.

담당 요구사항 (docs/FEATURES.md §3):
- F3-1 사용자는 목표만 있는 큰 일을 입력한다. (입력 수집은 app.py, 여기선 텍스트를 받는다)
- F3-2 왜/언제까지 등 꼭 필요한 맥락을 '이지선다' 질문으로 구체화해 나간다. (start → 질문 생성)
- F3-3 첫 입력이 이미 충분히 분명하면 F3-2를 건너뛴다. (needs_clarification=false → 바로 decompose)
- F3-4 구체화된 일을 작은 단위(≤5)로 분해한다. (decompose, MAX_STEPS)
- F3-5 분해 결과 중 '지금 할 첫 단계' 하나를 선정해 제시한다. (Proposal.first_step_id)
- F3-6 첫 단계가 여전히 크면 더 잘게 다시 쪼갤 수 있다. (resplit)
- F3-7 분해 결과는 사용자 확정 후에만 반영된다. (confirm 모듈이 담당, GP-1)

이 모듈은 로직만 담는다(레이어 규칙): Streamlit 위젯을 그리지 않고, 입력은 인자·출력은
Proposal / BreakdownSession 으로만 주고받는다. 다만 쪼개기는 여러 턴에 걸친 상태(구체화 진행)를
가지므로, F2 confirm 의 PENDING 처럼 진행 상태를 session_state(BREAKDOWN 키)에 보관한다.
call_llm 설정/호출 오류(LLMConfigError 등)는 잡지 않고 그대로 올려 화면(app.py)에서 안내로 바꾼다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import streamlit as st

from features import BREAKDOWN, call_llm
from features.confirm import Proposal
from features.todo import Todo

MAX_STEPS = 5      # 한눈에 부담 없는 분량 (F3-4)
MAX_QUESTIONS = 3  # 구체화 질문은 최대 3개까지만 (부담 최소화, F3-2)

# 분해가 어려운(너무 막연한) 입력에 대한 재입력 안내 (decompose 빈 결과)
_REPROMPT = (
    "이 일을 더 작게 나누기 어려웠어요. 무엇을 이루고 싶은지 한 문장만 더 "
    "구체적으로 적어줄래요?"
)


# ── 구체화 세션 상태(여러 턴에 걸친 진행) ──────────────────────────
@dataclass
class Question:
    """구체화용 이지선다 질문 하나. (F3-2)"""

    question: str
    options: list = field(default_factory=list)  # list[str] — 고르기 쉬운 선택지 2~4개


@dataclass
class BreakdownSession:
    """진행 중인 쪼개기 세션. 목표와 구체화 질문·답변, 진행 위치를 보관한다.

    구체화 질문은 미리 만들어 두고 '한 번에 하나씩'(cursor) 물어본다(Co-Planner 원칙).
    cursor 가 questions 끝에 도달하면 구체화가 끝난 것으로 본다(F3-3 건너뛰기 포함).
    """

    goal: str
    questions: list = field(default_factory=list)  # list[Question]
    answers: dict = field(default_factory=dict)    # {질문: 고른/적은 답}
    cursor: int = 0                                 # 지금 물어볼 질문 인덱스


# ── 세션 상태 접근자 (confirm 의 stage/get_pending 와 같은 역할) ────
def get_session() -> Optional[BreakdownSession]:
    """진행 중인 쪼개기 세션을 반환한다(없으면 None)."""
    return st.session_state.get(BREAKDOWN)


def set_session(session: BreakdownSession) -> None:
    """쪼개기 세션을 저장한다(진행 상태 보관)."""
    st.session_state[BREAKDOWN] = session


def clear_session() -> None:
    """쪼개기 세션을 비운다(확정·취소·새 대화 시)."""
    st.session_state[BREAKDOWN] = None


# ── 구체화 진행 제어 (F3-2, F3-3) ─────────────────────────────────
def is_clarifying(session: BreakdownSession) -> bool:
    """아직 물어볼 구체화 질문이 남았는지."""
    return session.cursor < len(session.questions)


def current_question(session: BreakdownSession) -> Optional[Question]:
    """지금 물어볼 질문(없으면 None)."""
    return session.questions[session.cursor] if is_clarifying(session) else None


def answer(session: BreakdownSession, choice: str) -> None:
    """현재 질문에 대한 답(고른 선택지 또는 직접 입력)을 기록하고 다음으로 넘어간다."""
    q = current_question(session)
    if q is None:
        return
    if choice and choice.strip():
        session.answers[q.question] = choice.strip()
    session.cursor += 1


def skip_current(session: BreakdownSession) -> None:
    """현재 질문을 답하지 않고 넘어간다. (F3-3 부분 건너뛰기)"""
    if is_clarifying(session):
        session.cursor += 1


def skip_all(session: BreakdownSession) -> None:
    """남은 질문을 모두 건너뛴다. (F3-3 — 구체화 없이 바로 분해)"""
    session.cursor = len(session.questions)


# ── 1단계: 구체화 필요 판단 + 이지선다 질문 생성 (F3-1, F3-2, F3-3) ─
_START_SYSTEM = f"""당신은 목표만 있는 큰 일을 함께 구체화하는 도우미입니다.
사용자가 적은 큰 일(목표)을 읽고, 실행 계획을 세우는 데 꼭 필요한 맥락이 빠졌는지 판단합니다.

판단 규칙:
- 이미 목적(왜)·기한(언제까지)·범위가 충분히 분명해서 바로 쪼갤 수 있으면 질문하지 않습니다. (needs_clarification=false)
- 부족할 때만, 실행을 가르는 핵심 맥락을 '이지선다(선택지 2~4개)' 질문으로 최대 {MAX_QUESTIONS}개까지 만듭니다.
- 질문은 '왜 하는지', '언제까지', '지금 상황/범위'처럼 답을 고르기 쉬운 것으로 합니다.
- 선택지는 서로 뚜렷이 다르고 실제 있을 법한 것으로 2~4개. 사용자가 직접 답할 수도 있으니 '기타'는 넣지 않습니다.
- 질문·선택지는 짧고 담백한 한국어로 씁니다.

출력은 아래 JSON '그대로만' 내보냅니다. 코드펜스나 설명 문장을 덧붙이지 않습니다.
{{"needs_clarification": true, "questions": [{{"question": "언제까지 끝내야 하나요?", "options": ["이번 주 안", "이번 달 안", "정해진 기한 없음"]}}]}}
구체화가 필요 없으면 정확히 이렇게 답합니다: {{"needs_clarification": false, "questions": []}}"""


def start(goal: str) -> BreakdownSession:
    """큰 일을 받아 구체화가 필요한지 판단하고, 필요하면 이지선다 질문을 만든다. (F3-1~F3-3)

    - 반환된 세션의 questions 가 비어 있으면 구체화가 불필요한 것(F3-3) → 바로 분해로 넘어간다.
    - 질문이 있으면 화면(app.py)이 한 번에 하나씩 물어보고, 답을 answer()로 기록한다.
    """
    goal = (goal or "").strip()
    session = BreakdownSession(goal=goal)
    if not goal:
        return session  # 빈 입력은 질문 없이 그대로(방어) — app 이 재입력 유도

    raw = call_llm(
        prompt=goal,
        system=_START_SYSTEM,
        temperature=0.4,
        max_tokens=600,
    )
    session.questions = _to_questions(_parse_json(raw))
    return session


# ── 2단계: 작은 단위로 분해 + '지금 할 첫 단계' 선정 (F3-4, F3-5) ───
_DECOMPOSE_SYSTEM = f"""당신은 큰 일을 '지금 바로 착수할 수 있는' 작은 단위로 쪼개는 도우미입니다.
목표와, 있다면 사용자가 고른 맥락을 반영해 순서대로 실행할 작은 할 일로 나눕니다.

분해 규칙:
- {MAX_STEPS}개 이하로 나눕니다. 너무 잘게 쪼개 부담을 주지 않습니다.
- 각 할 일은 구체적이고 바로 할 수 있는 행동으로, 짧은 한 줄. 되도록 동사로 끝맺습니다.
- 실행 순서대로 나열합니다.
- 그중 '지금 할 첫 단계' 하나를 고릅니다. 가장 작고, 지금 당장 시작할 수 있어야 합니다. (first_step_index)
- memo 에는 꼭 필요할 때만 아주 짧은 보충(왜/팁)을 적고, 없으면 빈 문자열로 둡니다.
- 도저히 나눌 것이 없으면 빈 목록을 반환합니다.

출력은 아래 JSON '그대로만' 내보냅니다. 코드펜스나 설명 문장을 덧붙이지 않습니다.
{{"steps": [{{"title": "치과 목록 검색하기", "memo": ""}}], "first_step_index": 0}}
나눌 것이 없으면 정확히 이렇게 답합니다: {{"steps": [], "first_step_index": 0}}"""

_FINER_HINT = (
    "\n\n참고: 아래 목표는 이미 한 번 쪼갠 결과의 한 단계입니다. "
    "지금 당장의 물리적 행동(전화 걸기·파일 열기 등) 수준으로 '더 잘게' 나눠주세요."
)


def decompose(
    goal: str,
    answers: Optional[dict] = None,
    *,
    finer: bool = False,
) -> Proposal:
    """구체화된 일을 작은 단위로 분해하고 '지금 할 첫 단계'를 함께 제시한다. (F3-4, F3-5)

    - answers: 구체화 질문에 대한 답(선택). 없어도 진행한다(F3-3).
    - finer=True: 재쪼개기(F3-6) — 한 단계를 더 잘게 나누도록 지시를 강화한다.
    - 결과는 5개 이하로 제한하고(F3-4), 첫 단계는 Proposal.first_step_id 로 표시한다(F3-5).
    - 반영 여부는 사용자에게 남긴다 — 여기선 확정 없이 후보만 만든다. (F3-7, GP-1)
    """
    goal = (goal or "").strip()
    if not goal:
        return Proposal(drafts=[], note=_REPROMPT, source="breakdown")

    system = _DECOMPOSE_SYSTEM + (_FINER_HINT if finer else "")
    raw = call_llm(
        prompt=_decompose_prompt(goal, answers),
        system=system,
        temperature=0.4,
        max_tokens=800,
    )
    drafts, first_index = _to_steps(_parse_json(raw))
    if not drafts:
        return Proposal(drafts=[], note=_REPROMPT, source="breakdown")

    first_id = drafts[first_index].id
    note = "작은 단위로 쪼갰어요. '지금 할 첫 단계'부터 가볍게 시작해보세요."
    return Proposal(drafts=drafts, note=note, source="breakdown", first_step_id=first_id)


def resplit(step_title: str, goal: Optional[str] = None) -> Proposal:
    """'지금 할 첫 단계'가 여전히 크면 그 단계를 더 잘게 다시 쪼갠다. (F3-6)

    step_title 을 새 목표로 삼아 decompose(finer=True) 를 호출한다.
    goal 은 원래 큰 목표(맥락 유지용, 선택).
    """
    answers = {"원래 목표": goal} if goal else None
    return decompose(step_title, answers, finer=True)


def splice_first_step(proposal: Proposal, target_id: str, finer_drafts: list) -> Proposal:
    """분해 결과에서 target 단계를 더 잘게 나눈 하위 단계들로 교체한다(형제 단계는 유지). (F3-6)

    재쪼개기가 나머지 단계를 버리지 않게, 원래 목록의 순서를 지키며 target 자리에만
    하위 단계들을 끼워 넣는다. 새 '지금 할 첫 단계'는 하위 단계의 첫 번째로 둔다.
    """
    new_drafts: list = []
    for draft in proposal.drafts:
        if draft.id == target_id:
            new_drafts.extend(finer_drafts)
        else:
            new_drafts.append(draft)
    first_id = finer_drafts[0].id if finer_drafts else proposal.first_step_id
    return Proposal(
        drafts=new_drafts,
        note=proposal.note,
        source="breakdown",
        first_step_id=first_id,
    )


def _decompose_prompt(goal: str, answers: Optional[dict]) -> str:
    """분해 LLM 에 넘길 사용자 프롬프트를 만든다(목표 + 고른 맥락)."""
    lines = [f"목표: {goal}"]
    picked = {k: v for k, v in (answers or {}).items() if v}
    if picked:
        lines.append("\n사용자가 고른 맥락:")
        lines.extend(f"- {q}: {a}" for q, a in picked.items())
    else:
        lines.append("\n(추가 맥락 없음)")
    return "\n".join(lines)


# ── 파싱 유틸 (LLM 출력 방어) ─────────────────────────────────────
def _parse_json(raw: str):
    """LLM 응답에서 JSON 을 최대한 안전하게 뽑아 파싱한다.

    코드펜스(```json …```)나 앞뒤 설명이 섞여도 본문의 JSON 을 찾아 파싱한다.
    실패하면 None 을 반환한다 → 빈 결과(질문 없음/분해 없음)로 이어진다.
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


def _to_questions(data) -> list:
    """파싱 결과에서 유효한 이지선다 질문만 추린다. (F3-2)

    - needs_clarification 이 명시적으로 false 면 질문을 만들지 않는다(F3-3).
    - 질문 문자열과 선택지(2개 이상)가 모두 있어야 유효로 본다.
    - 최대 MAX_QUESTIONS 개까지만 남긴다.
    """
    if not isinstance(data, dict):
        return []
    if data.get("needs_clarification") is False:
        return []

    raw_questions = data.get("questions")
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


_TITLE_KEYS = ("title", "task", "todo", "name", "step")
_MEMO_KEYS = ("memo", "note", "reason", "description")


def _first_str(item: dict, keys) -> str:
    """딕셔너리에서 keys 순서대로 비어있지 않은 '문자열' 값을 찾아 돌려준다(없으면 "")."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _to_steps(data) -> tuple:
    """파싱된 JSON 에서 유효한 단계만 Todo 로 만들고, 첫 단계 인덱스를 함께 돌려준다.

    반환: (drafts: list[Todo], first_index: int) — first_index 는 drafts 기준 위치.
    - 제목이 빈 항목은 버리고, 제목 기준 중복(대소문자 무시)을 제거한다.
    - MAX_STEPS(5) 를 넘지 않는다. (F3-4)
    - LLM 의 first_step_index 는 '원본 steps' 기준이므로, 걸러지고 재정렬된 drafts 위치로
      다시 매핑한다. 고른 단계가 걸러졌거나(빈 제목·중복) 잘려나갔으면 첫 단계(0)로 대체한다. (F3-5)
    """
    steps = []
    if isinstance(data, dict):
        raw_steps = data.get("steps")
        if isinstance(raw_steps, list):
            steps = raw_steps
    elif isinstance(data, list):
        steps = data

    # 원본 steps 기준 first_step_index 를 읽어둔다(유효한 정수만). bool 은 int 하위형이라 제외.
    raw_index = None
    if isinstance(data, dict):
        idx = data.get("first_step_index")
        if isinstance(idx, int) and not isinstance(idx, bool):
            raw_index = idx

    drafts: list = []
    seen = set()
    first_index = 0  # 기본: 살아남은 첫 단계
    for orig_pos, item in enumerate(steps):
        if isinstance(item, str):
            title, memo = item.strip(), ""
        elif isinstance(item, dict):
            title, memo = _first_str(item, _TITLE_KEYS), _first_str(item, _MEMO_KEYS)
        else:
            continue
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        if orig_pos == raw_index:  # LLM 이 고른 첫 단계가 살아남았다면 그 위치로 매핑 (F3-5)
            first_index = len(drafts)
        drafts.append(Todo(title=title, memo=memo, source="breakdown"))
        if len(drafts) >= MAX_STEPS:  # 부담 없는 분량 (F3-4)
            break

    if not drafts:
        return [], 0
    first_index = max(0, min(first_index, len(drafts) - 1))  # 범위 보정(방어)
    return drafts, first_index
