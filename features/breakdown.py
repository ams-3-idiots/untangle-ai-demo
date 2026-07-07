"""F3 — 쪼개기. 목표만 있는 큰 일을 질문으로 구체화한 뒤 작은 단위로 분해한다.

담당 요구사항 (docs/FEATURES.md §3):
- F3-1 사용자는 목표만 있는 큰 일을 입력한다. (입력 수집은 app.py, 여기선 텍스트를 받는다)
- F3-2 5개 항목의 맥락을 '선택지' 질문으로, 앞선 답에 맞춰 한 번에 하나씩 구체화해 나간다. (start→advance)
- F3-3 이미 분명한 항목은 건너뛰고, 모두 분명하면 구체화 자체를 건너뛴다. (pending=None → 바로 decompose)
- F3-4 구체화된 일을 작은 단위(≤5)로 분해한다. (decompose, MAX_STEPS)
- F3-5 다른 할 일과 구별되는 '지금 할 첫 단계'(즉시 실행 행동)를 함께 제시한다. (Proposal.first_step_id)
- F3-6 결과 할 일 중 하나를 골라 더 잘게 다시 쪼갤 수 있다. (resplit, splice_step)
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

MAX_STEPS = 5  # 한눈에 부담 없는 분량 (F3-4)
MAX_QUESTIONS = 5  # 구체화 항목이 5개 — 항목당 최대 한 번, 총 5문항까지만 (F3-2)

# 구체화가 파악해야 할 5개 항목 (F3-2). (key, 짧은 이름, 뜻) — 진행은 key 로 추적한다.
CLARIFY_ITEMS = [
    ("why", "왜 하는가", "목적·동기 — 우선순위·의미의 기준"),
    (
        "progress",
        "지금까지 얼마나 진행하셨나요",
        "현재 진행 상태 — 분해의 시작점, 이미 한 일은 제외",
    ),
    ("done", "최종 목표가 무엇인가요?", "완료 기준·원하는 결과물 — 분해의 종착점·범위"),
    (
        "capacity",
        "시간은 얼마나 투자할 수 있나요?",
        "가용 시간·에너지 — 각 단계 크기를 실제 가능한 분량으로",
    ),
    (
        "blocker",
        "무엇 때문에 일을 수행하기 힘든가요?",
        "걸림돌·막히는 지점 — '지금 할 첫 단계' 설계의 근거",
    ),
]
CLARIFY_LABELS = {key: name for key, name, _ in CLARIFY_ITEMS}  # key → 화면용 이름
_ITEM_KEYS = set(CLARIFY_LABELS)

# 분해가 어려운(너무 막연한) 입력에 대한 재입력 안내 (decompose 빈 결과)
_REPROMPT = (
    "이 일을 더 작게 나누기 어려웠어요. 무엇을 이루고 싶은지 한 문장만 더 "
    "구체적으로 적어줄래요?"
)


# ── 구체화 세션 상태(여러 턴에 걸친 진행) ──────────────────────────
@dataclass
class Question:
    """구체화용 선택지 질문 하나. (F3-2)

    dimension 은 이 질문이 다루는 5개 항목(CLARIFY_ITEMS) 중 하나의 key. 진행 추적에 쓴다.
    """

    question: str
    options: list = field(default_factory=list)  # list[str] — 고르기 쉬운 선택지 2~4개
    dimension: str = ""


@dataclass
class BreakdownSession:
    """진행 중인 쪼개기 세션. 목표와 지금까지의 답·다룬 항목, 다음에 물을 질문을 보관한다.

    구체화는 5개 항목(CLARIFY_ITEMS)을 '한 번에 하나씩', 앞선 답에 맞춰 동적으로 물어본다(F3-2).
    - pending 이 있으면 아직 물어볼 질문이 남은 것, None 이면 구체화가 끝난 것이다(F3-3 포함).
    - covered 에는 이미 다룬(답했거나 건너뛴) 항목 key 를 쌓아 재질문·무한 반복을 막는다.
    """

    goal: str
    answers: dict = field(default_factory=dict)  # {질문: 고른/적은 답}
    covered: list = field(default_factory=list)  # 이미 다룬 항목 key (건너뜀 포함)
    pending: Optional[Question] = None  # 지금 물어볼 질문 (없으면 구체화 종료)


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
    return session.pending is not None


def current_question(session: BreakdownSession) -> Optional[Question]:
    """지금 물어볼 질문(없으면 None)."""
    return session.pending


def _mark_covered(session: BreakdownSession, dimension: str) -> None:
    """항목 하나를 '다룸'으로 표시한다(중복 없이). 진행이 반드시 앞으로 나아가게 한다."""
    if dimension in _ITEM_KEYS and dimension not in session.covered:
        session.covered.append(dimension)


def answer(session: BreakdownSession, choice: str) -> None:
    """현재 질문의 답(고른 선택지 또는 직접 입력)을 기록하고 그 항목을 '다룸'으로 표시한다.

    다음 질문 준비(advance)는 LLM 호출이라, 화면(app.py)이 스피너·오류 처리와 함께 부른다.
    """
    q = session.pending
    if q is None:
        return
    if choice and choice.strip():
        session.answers[q.question] = choice.strip()
    _mark_covered(session, q.dimension)
    session.pending = None


def skip_current(session: BreakdownSession) -> None:
    """현재 질문을 답하지 않고 그 항목만 건너뛴다. (F3-3 부분 건너뛰기)"""
    q = session.pending
    if q is None:
        return
    _mark_covered(session, q.dimension)
    session.pending = None


def skip_all(session: BreakdownSession) -> None:
    """남은 구체화를 모두 건너뛰고 바로 분해로 넘어간다. (F3-3)"""
    session.pending = None
    for key, _, _ in CLARIFY_ITEMS:
        _mark_covered(
            session, key
        )  # 전부 다룬 것으로 표시 → advance 가 재질문하지 않게


# ── 1단계: 구체화 — 다음 질문 하나를 동적으로 생성 (F3-1, F3-2, F3-3) ─
_ITEM_LINES = "\n".join(
    f"- {key}: {name} — {hint}" for key, name, hint in CLARIFY_ITEMS
)

_CLARIFY_SYSTEM = f"""당신은 목표만 있는 큰 일을 실행 계획으로 옮기기 전에, 꼭 필요한 맥락을 사용자와 함께 좁혀가는 도우미입니다.
아래 5개 항목의 맥락을 '한 번에 하나씩' 물어 파악합니다. (key: 이름 — 뜻)
{_ITEM_LINES}

규칙:
- 사용자 프롬프트의 '목표'와 '지금까지의 답'을 보고, 아직 다루지 않은 항목 중 실행을 가장 크게 가르는 것 하나만 고릅니다.
- 목표 문장이나 앞선 답으로 이미 충분히 분명한 항목은 묻지 않고 건너뜁니다.
- 아직 다루지 않은 항목이 없거나 남은 것도 이미 분명하면 더 묻지 않습니다. (needs_more=false)
- 질문은 고르기 쉬운 '선택지'를 먼저 제시해 답하게 합니다. 자유 서술을 강요하지는 않으며, 사용자가 자유롭게 적은 답도 맥락으로 반영합니다.
- 선택지는 이 목표·앞선 답에 맞춘, 서로 뚜렷이 다르고 실제 있을 법한 것 2~4개. '기타'는 넣지 않습니다(직접 입력도 가능).
- 질문·선택지는 짧고 담백한 한국어로 씁니다.

출력은 아래 JSON '그대로만' 내보냅니다. 코드펜스나 설명 문장을 덧붙이지 않습니다.
더 물을 게 있으면: {{"needs_more": true, "dimension": "<위 key 중 하나>", "question": "…", "options": ["…", "…"]}}
더 물을 게 없으면 정확히: {{"needs_more": false}}"""


def start(goal: str) -> BreakdownSession:
    """큰 일을 받아 첫 구체화 질문을 준비한다(불필요하면 바로 분해로). (F3-1~F3-3)

    - 반환된 세션의 pending 이 None 이면 구체화가 불필요한 것(F3-3) → 화면이 바로 분해로 넘어간다.
    - pending 이 있으면 화면(app.py)이 한 번에 하나씩 물어보고, answer()→advance() 로 이어간다.
    """
    session = BreakdownSession(goal=(goal or "").strip())
    if not session.goal:
        return session  # 빈 입력은 질문 없이 그대로(방어) — app 이 재입력 유도
    advance(session)  # 첫 질문 준비 (또는 '구체화 불필요' 판단 → pending=None)
    return session


def advance(session: BreakdownSession) -> None:
    """지금까지의 답을 반영해 다음에 물을 구체화 질문 하나를 준비한다(없으면 종료). (F3-2, F3-3)

    남은 항목 중 아직 불분명한 것 하나를 골라 선택지 질문으로 만든다. 모두 분명하거나 질문
    상한(MAX_QUESTIONS)에 이르면 pending 을 비워 구체화를 끝낸다(→ 분해).
    LLM 호출 실패 시 예외를 그대로 올린다. 다만 pending 은 호출 전에 비워 두므로, 호출자가
    예외를 잡아 '지금까지의 맥락으로 분해'로 자연스럽게 넘어갈 수 있다.
    """
    session.pending = None
    if not session.goal:
        return
    if len(session.covered) >= MAX_QUESTIONS:  # 5개 항목을 모두 다룸 → 구체화 종료
        return
    session.pending = _next_question(session)


def _next_question(session: BreakdownSession) -> Optional[Question]:
    """LLM 으로 남은 항목 중 아직 불분명한 것 하나를 선택지 질문으로 만든다(없으면 None)."""
    raw = call_llm(
        prompt=_clarify_prompt(session),
        system=_CLARIFY_SYSTEM,
        temperature=0.4,
        max_tokens=500,
    )
    return _to_question(_parse_json(raw), session)


def _clarify_prompt(session: BreakdownSession) -> str:
    """구체화 LLM 에 줄 사용자 프롬프트: 목표 + 지금까지의 답 + 아직 안 다룬 항목."""
    lines = [f"큰 일(목표): {session.goal}", ""]
    if session.answers:
        lines.append("지금까지 사용자가 고르거나 적은 답:")
        lines.extend(f"- {q} → {a}" for q, a in session.answers.items())
    else:
        lines.append("아직 받은 답이 없습니다.")
    remaining = [
        (k, name, hint) for k, name, hint in CLARIFY_ITEMS if k not in session.covered
    ]
    lines.append("")
    lines.append("아직 다루지 않은 항목 (이 중 아직 불분명한 것 하나만 골라 질문):")
    lines.extend(f"- {k}: {name} — {hint}" for k, name, hint in remaining)
    return "\n".join(lines)


# ── 2단계: 작은 단위로 분해 + '지금 할 첫 단계' 선정 (F3-4, F3-5) ───
_DECOMPOSE_SYSTEM = f"""당신은 큰 일을 '지금 바로 착수할 수 있는' 작은 단위로 쪼개는 도우미입니다.
목표와, 있다면 사용자가 고른 맥락을 반영해 순서대로 실행할 작은 할 일로 나눕니다.

분해 규칙:
- '지금 할 첫 단계'(first_step) 1개와, 그다음 순서대로 실행할 작은 할 일(steps)을 만듭니다. 첫 단계를 포함해 모두 합쳐 {MAX_STEPS}개를 넘지 않습니다. 너무 잘게 쪼개 부담을 주지 않습니다.
- steps 의 각 할 일은 구체적이고 바로 할 수 있는 행동으로, 짧은 한 줄. 되도록 동사로 끝맺고 실행 순서대로 나열합니다.
- first_step 은 steps 와 '질적으로 다릅니다'. 고민·준비 없이 5초 안에 몸으로 시작할 수 있는 가장 작은 물리적 한 동작으로 씁니다. (예: "책상에 앉기", "노트북 펼치기", "인터넷에 '동네 치과' 검색해보기")
- memo 에는 꼭 필요할 때만 아주 짧은 보충(왜/팁)을 적고, 없으면 빈 문자열로 둡니다.
- 도저히 나눌 것이 없으면 steps 를 빈 목록으로, first_step 을 빈 값으로 둡니다.

출력은 아래 JSON '그대로만' 내보냅니다. 코드펜스나 설명 문장을 덧붙이지 않습니다.
{{"first_step": {{"title": "인터넷에 '동네 치과' 검색해보기", "memo": ""}}, "steps": [{{"title": "후기 좋은 곳 두어 곳 추리기", "memo": ""}}]}}
나눌 것이 없으면 정확히 이렇게 답합니다: {{"first_step": {{"title": "", "memo": ""}}, "steps": []}}"""

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
    - 결과는 첫 단계 포함 5개 이하로 제한하고(F3-4), 즉시 실행 행동인 첫 단계는 Proposal.first_step_id 로 표시한다(F3-5).
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
    return Proposal(
        drafts=drafts, note=note, source="breakdown", first_step_id=first_id
    )


def resplit(step_title: str, goal: Optional[str] = None) -> Proposal:
    """결과 할 일 중 사용자가 고른 한 단계가 여전히 크면 더 잘게 다시 쪼갠다. (F3-6)

    step_title 을 새 목표로 삼아 decompose(finer=True) 를 호출한다.
    goal 은 원래 큰 목표(맥락 유지용, 선택).
    """
    answers = {"원래 목표": goal} if goal else None
    return decompose(step_title, answers, finer=True)


def splice_step(proposal: Proposal, target_id: str, finer_drafts: list) -> Proposal:
    """분해 결과에서 사용자가 고른 target 할 일을 더 잘게 나눈 하위 단계들로 교체한다. (F3-6)

    재쪼개기가 나머지 할 일을 버리지 않게, 원래 목록의 순서를 지키며 target 자리에만
    하위 단계들을 끼워 넣는다(형제는 유지). 곧 '새로 쪼개진 일들 + 고른 일을 뺀 나머지'다.
    '지금 할 첫 단계'는 그 첫 단계 자체를 쪼갰을 때만 하위의 첫 번째로 옮기고,
    다른 할 일을 쪼갰다면 기존 첫 단계를 그대로 유지한다. (F3-5)
    """
    new_drafts: list = []
    for draft in proposal.drafts:
        if draft.id == target_id:
            new_drafts.extend(finer_drafts)
        else:
            new_drafts.append(draft)
    # 첫 단계를 쪼갰다면 새 첫 단계는 하위의 첫 번째, 아니면 기존 첫 단계 유지.
    if proposal.first_step_id == target_id and finer_drafts:
        first_id = finer_drafts[0].id
    else:
        first_id = proposal.first_step_id
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


def _to_question(data, session: BreakdownSession) -> Optional[Question]:
    """파싱 결과에서 유효한 선택지 질문 하나를 만든다(없으면 None → 구체화 종료). (F3-2, F3-3)

    - needs_more 가 false 이거나 형식이 어긋나면 None.
    - 남은(안 다룬) 항목이 없으면 None.
    - 질문 문자열과 선택지(2개 이상)가 모두 있어야 유효로 본다.
    - dimension 은 '아직 안 다룬' key 로 보정한다(엉뚱/중복이면 남은 첫 항목). 진행이 반드시
      앞으로 나아가도록(무한 반복 방지).
    """
    if not isinstance(data, dict) or data.get("needs_more") is False:
        return None
    remaining = [k for k, _, _ in CLARIFY_ITEMS if k not in session.covered]
    if not remaining:
        return None

    text = data.get("question")
    opts = data.get("options")
    if not isinstance(text, str) or not text.strip():
        return None
    if not isinstance(opts, list):
        return None
    clean = [o.strip() for o in opts if isinstance(o, str) and o.strip()]
    if len(clean) < 2:  # 선택지는 최소 2개
        return None

    dim = data.get("dimension")
    if not isinstance(dim, str) or dim not in _ITEM_KEYS or dim in session.covered:
        dim = remaining[0]
    return Question(question=text.strip(), options=clean[:4], dimension=dim)


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
    """파싱된 JSON 에서 '지금 할 첫 단계'와 나머지 작은 단위를 Todo 로 만든다.

    반환: (drafts: list[Todo], first_index: int) — first_index 는 항상 0(맨 앞이 첫 단계).
    - first_step(즉시 실행 행동)을 맨 앞에 두고, steps(작은 할 일)를 순서대로 잇는다. (F3-5)
    - 제목이 빈 항목은 버리고, 제목 기준 중복(대소문자 무시)을 제거한다.
    - 첫 단계를 포함해 MAX_STEPS(5) 를 넘지 않는다. (F3-4)
    - first_step 이 없거나 무효면(옛 형식·누락) 살아남은 첫 항목을 '지금 할 첫 단계'로 삼는다(방어).
    """
    first_step = None
    steps: list = []
    if isinstance(data, dict):
        first_step = data.get("first_step")
        raw_steps = data.get("steps")
        if isinstance(raw_steps, list):
            steps = raw_steps
    elif isinstance(data, list):
        steps = data

    drafts: list = []
    seen = set()

    def _push(item) -> None:
        """유효한 항목 하나를 Todo 로 만들어 drafts 에 더한다(빈 제목·중복은 건너뜀)."""
        if isinstance(item, str):
            title, memo = item.strip(), ""
        elif isinstance(item, dict):
            title, memo = _first_str(item, _TITLE_KEYS), _first_str(item, _MEMO_KEYS)
        else:
            return
        if not title:
            return
        key = title.lower()
        if key in seen:
            return
        seen.add(key)
        drafts.append(Todo(title=title, memo=memo, source="breakdown"))

    _push(first_step)  # 맨 앞: 즉시 실행 가능한 '지금 할 첫 단계' (F3-5)
    for item in steps:
        if len(drafts) >= MAX_STEPS:  # 첫 단계 포함 부담 없는 분량 (F3-4)
            break
        _push(item)

    if not drafts:
        return [], 0
    return drafts, 0
