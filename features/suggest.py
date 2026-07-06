"""F5 — 대화형 안내·제안 (상황 기반).

바뀐 상황·에너지 상태를 대화로 전달받아, 기존 당일 할 일을 재해석·재정렬하고
'지금 할 일' 하나를 이유와 함께 제안한다.

담당 요구사항 (docs/FEATURES.md §5):
- F5-1 사용자는 바뀐 상황(새 일·에너지 변화·돌발)을 대화로 전달한다. (입력 수집은 app.py, 여기선 텍스트를 받는다)
- F5-2 전달된 맥락에 맞춰 기존 당일 할 일을 재해석·재정렬한다. (Proposal.order_ids)
- F5-3 대화 마지막에 '지금 할 일' 하나를 이유와 함께 제안한다. (first_step_id = pick, note = 이유)
- F5-4 제안은 단일·즉시 실행 가능한 단위로 제시한다. (pick 하나 + first_step)
- F5-5 제안이 막연하면 첫 단계 수준까지 구체화해 제시한다(쪼개기 연계). (first_step / refine_first_step)
- F5-6 에너지 상태에 맞춰 일의 난이도·부하를 조정해 제안한다. (energy 반영 프롬프트)
- F5-7 사용자는 수락·거절·대안을 요청할 수 있다. (confirm_suggestion / clear_pending / exclude_ids)
- F5-8 제안·재정렬 결과는 사용자 확정 후 반영된다. (confirm_suggestion, GP-1)

이 모듈은 로직만 담는다(레이어 규칙): Streamlit 위젯을 그리지 않고, 입력은 인자·출력은
Proposal 로만 주고받는다. call_llm 설정/호출 오류(LLMConfigError 등)는 잡지 않고 그대로 올려
화면(app.py)에서 안내 메시지로 바꾼다. (F2~F4 모듈과 동일 방침)
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional

from features import call_llm
from features.confirm import Proposal, clear_pending
from features.todo import (
    Todo,
    list_todos,
    priority_label,
    reorder_todos,
    set_focus,
    set_focus_step,
)

_WEEKDAYS = "월화수목금토일"

# 상황·에너지 단서가 없는(빈) 입력에 대한 재입력 안내 (F5-1)
_REPROMPT = (
    "지금 상황이나 에너지 상태를 한 문장만 들려줄래요? "
    '(예: "갑자기 30분 비었어", "너무 지쳐서 가벼운 것만 하고 싶어")'
)
# 오늘 할 일이 하나도 없을 때(재정렬 대상이 없음)
_EMPTY_NOTE = (
    "아직 오늘 할 일이 없어요. 먼저 몇 개 담아두면, 상황에 맞춰 '지금 할 일'을 골라드릴게요."
)
# 대안 요청이 반복돼 고를 후보가 남지 않았을 때 (F5-7)
_ALL_EXCLUDED = (
    "지금 고를 만한 다른 일이 마땅치 않네요. 새로운 상황을 들려주거나 '오늘 할 일'을 살펴볼까요?"
)
_DEFAULT_REASON = "지금 상황에 맞춰 이 일부터 가볍게 시작하면 좋겠어요."


# ── 프롬프트 ──────────────────────────────────────────────────────
_SUGGEST_SYSTEM = """당신은 사용자의 '지금 상황·에너지'에 맞춰 오늘 할 일을 다시 정렬하고,
'지금 할 일' 딱 하나를 이유와 함께 골라주는 도우미입니다.

지켜야 할 것:
- 먼저 사용자가 전한 상황과 에너지 상태를 읽습니다. 에너지가 드러나지 않으면 "보통"으로 봅니다.
- 주어진 '오늘 할 일'을 상황에 맞게 다시 정렬합니다(order). 지금 하기 좋은 것·급한 것을 앞으로 둡니다.
- 그중 '지금 할 일' 하나만 고릅니다(pick_index). 여러 개를 고르지 않습니다. 지금 당장 착수할 수 있어야 합니다.
- 에너지에 맞춰 부하를 조절합니다. 에너지가 낮으면 작고 가벼운 일을, 높으면 좀 더 무게 있는 일을 골라도 됩니다.
- 고른 일이 막연하거나 크면 vague=true 로 두고, 지금 바로 할 수 있는 '첫 단계'(first_step)를 한 줄로 구체화합니다. 충분히 작으면 vague=false, first_step 은 "".
- reason 은 왜 지금 이 일인지 한두 문장으로. 따뜻하고 담백하게, 죄책감을 주지 않습니다.
- 반드시 주어진 목록 안의 일만 고릅니다. 목록에 없는 일을 지어내지 않습니다.
- '고르지 말 것'으로 표시된 번호는 pick 으로 고르지 않습니다.
- order·pick_index 는 목록에 매겨진 [번호](0부터)를 그대로 씁니다.

출력은 아래 JSON '그대로만' 내보냅니다. 코드펜스나 설명 문장을 덧붙이지 않습니다.
{"energy": "낮음", "order": [2, 0, 1, 3], "pick_index": 2, "reason": "지금은 에너지가 낮으니, 5분이면 끝나는 이 일부터 가볍게 시작해요.", "first_step": "책상 위 서류 한 장만 파일에 넣기", "vague": true}"""

_STARTER_SYSTEM = """당신은 사용자의 '지금 상황·에너지'를 듣고, 지금 바로 할 수 있는 아주 작은 일 하나를 골라주는 도우미입니다.
아직 오늘 할 일 목록이 비어 있으니, 상황에 맞는 가볍고 즉시 실행 가능한 할 일 '한 건'만 제안합니다.

- 딱 하나만. 5분 안팎으로 지금 당장 시작할 수 있는 구체적인 행동으로, 짧은 한 줄(되도록 동사로 끝맺음).
- reason 은 왜 지금 이 일인지 한 문장으로 따뜻하게.

출력은 아래 JSON '그대로만'. 코드펜스·설명 금지.
{"starter": "책상 위 서류 한 장만 치우기", "reason": "에너지가 낮을 땐 아주 작은 정돈 하나가 시작을 도와요."}"""


# ── 공개 진입점 ───────────────────────────────────────────────────
def suggest_now(
    situation: str,
    *,
    todos: Optional[list] = None,
    exclude_ids: Optional[list] = None,
    history: Optional[list] = None,
    today: Optional[date] = None,
) -> Proposal:
    """상황·에너지를 반영해 재정렬하고 '지금 할 일' 하나를 이유와 함께 제안한다. (F5-2~F5-6)

    - situation : 사용자가 방금 전한 상황·에너지 문장(F5-1).
    - todos     : 재정렬 대상(기본 list_todos()). 비어 있으면 작은 시작 하나를 제안한다.
    - exclude_ids: 대안 요청으로 pick 에서 제외할 할 일 id(F5-7).
    - history   : 이전 대화 맥락(Message 유사 객체 리스트). 여러 턴에 걸친 상황 공유를 잇는다(F5-1).
    - today     : 상대 날짜·요일 표기 기준(기본 date.today()).

    반영 여부는 사용자에게 남긴다 — 여기선 확정 없이 제안만 만든다. (F5-8, GP-1)
    """
    situation = (situation or "").strip()
    todos = list_todos() if todos is None else todos
    today = today or date.today()
    exclude_ids = list(exclude_ids or [])

    if not situation:
        return Proposal(drafts=[], note=_REPROMPT, source="suggest")

    if not todos:  # 재정렬 대상이 없음 → 상황에 맞는 작은 시작 하나 제안
        return _suggest_starter(situation, today)

    raw = call_llm(
        prompt=_suggest_prompt(situation, todos, exclude_ids, today, history),
        system=_SUGGEST_SYSTEM,
        temperature=0.4,
        max_tokens=700,
    )
    return _to_suggestion(_parse_json(raw), todos, exclude_ids)


def confirm_suggestion(proposal: Optional[Proposal]) -> Optional[Todo]:
    """제안을 수락해 재정렬과 '지금 할 일' 표시를 실제 데이터에 반영한다. (F5-8, GP-1)

    - 제안된 순서로 오늘 할 일을 재정렬한다(F5-2).
    - '지금 할 일'을 포커스로 표시한다(F5-3). order_ids 는 이미 pick 이 맨 앞이라 목록 최상단에 온다.
    - 구체화한 첫 단계(first_step)는 할 일 memo 를 건드리지 않고 별도 상태로 보존한다(F5-5, 유실 방지).
    반환: 반영된 '지금 할 일' Todo(없으면 None).
    """
    if proposal is None or proposal.source != "suggest":
        return None
    if proposal.order_ids:
        reorder_todos(proposal.order_ids)  # F5-2·F5-8: 재정렬 반영('지금 할 일'이 맨 위)

    pick = None
    pick_id = proposal.first_step_id
    if pick_id:
        set_focus(pick_id)  # '지금 할 일' 표시 (F5-3) — 이전 첫 단계 표시는 함께 초기화
        if proposal.first_step:
            set_focus_step(proposal.first_step)  # 첫 단계를 memo 와 분리해 보존 (F5-5)
        pick = _find_todo(pick_id)
    clear_pending()  # 확정했으니 대기 제안 정리
    return pick


def refine_first_step(proposal: Optional[Proposal]) -> Optional[Proposal]:
    """'지금 할 일'이 여전히 막연하면 쪼개기(F3)로 첫 단계를 더 잘게 구체화한다. (F5-5)

    breakdown.resplit 을 재사용해(쪼개기 연계) 나온 '지금 할 첫 단계'를 제안의 first_step 으로 교체한다.
    아직 확정 전이므로 실제 데이터는 건드리지 않는다(GP-1). 더 쪼갤 수 없으면 원안을 그대로 돌려준다.
    """
    if proposal is None or not proposal.first_step_id:
        return proposal
    pick = _find_todo(proposal.first_step_id)
    if pick is None:
        return proposal

    from features import breakdown  # 지연 임포트(쪼개기 연계, 순환 방지)

    finer = breakdown.resplit(pick.title)
    step = ""
    if finer is not None and finer.drafts:
        idx = 0
        if finer.first_step_id:
            idx = next(
                (i for i, d in enumerate(finer.drafts) if d.id == finer.first_step_id), 0
            )
        step = finer.drafts[idx].title
    if not step:
        return proposal  # 더 잘게 쪼갤 것이 없음 — 원안 유지

    return Proposal(
        drafts=proposal.drafts,
        source="suggest",
        note=proposal.note,
        first_step_id=proposal.first_step_id,
        order_ids=proposal.order_ids,
        energy=proposal.energy,
        first_step=step,
        excluded_ids=proposal.excluded_ids,
    )


# ── 목록이 비었을 때: 작은 시작 하나 제안 ─────────────────────────
def _suggest_starter(situation: str, today: date) -> Proposal:
    raw = call_llm(
        prompt=f"오늘: {today.isoformat()} ({_WEEKDAYS[today.weekday()]})\n"
        f"지금 상황(에너지 포함):\n{situation}",
        system=_STARTER_SYSTEM,
        temperature=0.5,
        max_tokens=300,
    )
    data = _parse_json(raw)
    title = _first_str(data, ("starter", "title", "task", "todo")) if isinstance(data, dict) else ""
    reason = _first_str(data, ("reason", "why", "note")) if isinstance(data, dict) else ""
    if not title:
        return Proposal(drafts=[], note=_EMPTY_NOTE, source="suggest")
    draft = Todo(title=title, source="suggest")
    return Proposal(
        drafts=[draft],
        source="suggest",
        note=reason or "아직 담긴 할 일이 없어서, 지금 상황에 맞는 작은 시작 하나를 골라봤어요.",
    )


# ── 프롬프트 조립 ─────────────────────────────────────────────────
def _suggest_prompt(situation, todos, exclude_ids, today, history) -> str:
    lines = [f"오늘: {today.isoformat()} ({_WEEKDAYS[today.weekday()]})"]

    ctx = _history_block(history)
    if ctx:
        lines.append("\n지난 대화:\n" + ctx)

    lines.append("\n지금 상황(에너지 포함):\n" + situation)

    lines.append("\n오늘 할 일 목록:")
    for i, t in enumerate(todos):
        lines.append(f"[{i}] {_todo_line(t)}")

    exclude = set(exclude_ids or [])
    if exclude:
        nums = [str(i) for i, t in enumerate(todos) if t.id in exclude]
        if nums:
            lines.append("\n고르지 말 것(방금 거절/대안 요청): [" + ", ".join(nums) + "]")
    return "\n".join(lines)


def _todo_line(t: Todo) -> str:
    """할 일 한 건을 프롬프트용 한 줄로 요약한다(지정된 속성만)."""
    parts = [t.title]
    if t.priority in (1, 2, 3):  # '없음'(4)은 굳이 표기하지 않는다
        parts.append("우선순위:" + priority_label(t.priority))
    if t.due_date is not None:
        when = t.due_date.strftime("%m-%d")
        if t.due_time is not None:
            when += " " + t.due_time.strftime("%H:%M")
        parts.append("마감:" + when)
    elif t.due_time is not None:
        parts.append("시간:" + t.due_time.strftime("%H:%M"))
    if t.recurrence:
        parts.append("반복:" + t.recurrence)
    if t.done:
        parts.append("(완료됨)")
    return " · ".join(parts)


def _history_block(history) -> str:
    """이전 대화(오류·안내 제외)를 최근 몇 턴만 프롬프트용으로 요약한다. (F5-1 맥락 유지)"""
    if not history:
        return ""
    lines = []
    for m in list(history)[-6:]:
        if getattr(m, "error", False):
            continue
        role = getattr(m, "role", None)
        content = getattr(m, "content", None)
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        who = "나" if role == "user" else "Co-Planner"
        lines.append(f"{who}: {content.strip()}")
    return "\n".join(lines)


# ── LLM 출력 → 제안(Proposal) ─────────────────────────────────────
def _to_suggestion(data, todos, exclude_ids) -> Proposal:
    """LLM JSON 을 재정렬·pick·이유가 담긴 Proposal 로 만든다. (F5-2~F5-6)

    파싱이 어긋나거나 pick 이 유효하지 않으면, 재정렬 없이 첫 후보를 그대로 제안한다(방어).
    """
    if not isinstance(data, dict):
        return _fallback_suggestion(todos, exclude_ids)

    energy = _norm_energy(data.get("energy"))
    order_ids = _order_ids(data.get("order"), todos)
    pick_id = _pick_id(data.get("pick_index"), order_ids, todos, exclude_ids)
    if pick_id is None:
        return _fallback_suggestion(todos, exclude_ids)

    reason = _first_str(data, ("reason", "why", "note")) or _DEFAULT_REASON
    first_step = _first_str(data, ("first_step", "step"))
    return Proposal(
        drafts=[],
        source="suggest",
        note=reason,
        first_step_id=pick_id,
        order_ids=_hoist_first(order_ids, pick_id),  # '지금 할 일'을 맨 위로 (F5-3)
        energy=energy,
        first_step=first_step,
        excluded_ids=list(exclude_ids or []),
    )


def _fallback_suggestion(todos, exclude_ids) -> Proposal:
    """LLM 출력이 무너졌을 때: 원래 순서를 지키고 제외되지 않은 첫 할 일을 제안한다."""
    order_ids = [t.id for t in todos]
    pick_id = _pick_id(None, order_ids, todos, exclude_ids)
    if pick_id is None:  # 모든 후보가 제외됨 (대안 요청 반복)
        return Proposal(drafts=[], note=_ALL_EXCLUDED, source="suggest")
    return Proposal(
        drafts=[],
        source="suggest",
        note=_DEFAULT_REASON,
        first_step_id=pick_id,
        order_ids=_hoist_first(order_ids, pick_id),  # '지금 할 일'을 맨 위로 (F5-3)
        excluded_ids=list(exclude_ids or []),
    )


def _hoist_first(order_ids: list, pick_id: Optional[str]) -> list:
    """'지금 할 일'(pick)을 재정렬 순서 맨 앞으로 올린다. (F5-3 '지금 할 일'=최상단)

    이렇게 해야 목록 재정렬·미리보기·수락 안내('맨 위로 올렸다')가 서로 어긋나지 않는다.
    pick 이 순서에 없거나 비어 있으면 원래 순서를 그대로 둔다(방어).
    """
    if not pick_id or pick_id not in order_ids:
        return order_ids
    return [pick_id] + [tid for tid in order_ids if tid != pick_id]


def _order_ids(order, todos) -> list:
    """LLM 의 order(인덱스 배열)를 실제 할 일 id 순서로 바꾼다. (F5-2)

    범위를 벗어난 값·중복·bool 은 버리고, 빠진 할 일은 원래 순서대로 뒤에 붙인다(유실 없음).
    """
    ids: list = []
    placed: set = set()
    if isinstance(order, list):
        for i in order:
            if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(todos):
                tid = todos[i].id
                if tid not in placed:
                    ids.append(tid)
                    placed.add(tid)
    for t in todos:
        if t.id not in placed:
            ids.append(t.id)
            placed.add(t.id)
    return ids


def _pick_id(pick_index, order_ids, todos, exclude_ids) -> Optional[str]:
    """'지금 할 일' 하나의 id 를 고른다. (F5-3·F5-4)

    LLM 이 고른 인덱스를 우선하되, 범위를 벗어나거나 제외 대상이면 재정렬 순서에서
    제외되지 않은 첫 항목으로 대체한다. 고를 것이 없으면 None.
    """
    exclude = set(exclude_ids or [])
    if (
        isinstance(pick_index, int)
        and not isinstance(pick_index, bool)
        and 0 <= pick_index < len(todos)
    ):
        pid = todos[pick_index].id
        if pid not in exclude:
            return pid
    for tid in order_ids:
        if tid not in exclude:
            return tid
    return None


def _norm_energy(value) -> str:
    """에너지 표기를 낮음/보통/높음 중 하나로 정규화한다(알 수 없으면 빈 문자열)."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    for level in ("낮음", "보통", "높음"):
        if level in text:
            return level
    low = text.lower()
    if "low" in low:
        return "낮음"
    if "high" in low:
        return "높음"
    if "medium" in low or "mid" in low:
        return "보통"
    return ""


# ── 파싱 유틸 (LLM 출력 방어, F2~F4 와 동일 방침) ─────────────────
def _parse_json(raw: str):
    """LLM 응답에서 JSON 을 최대한 안전하게 뽑아 파싱한다(실패 시 None)."""
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


def _first_str(item: dict, keys) -> str:
    """딕셔너리에서 keys 순서대로 비어있지 않은 '문자열' 값을 찾아 돌려준다(없으면 "")."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _find_todo(todo_id: str) -> Optional[Todo]:
    """오늘 할 일에서 id 로 한 건을 찾는다(없으면 None)."""
    for t in list_todos():
        if t.id == todo_id:
            return t
    return None
