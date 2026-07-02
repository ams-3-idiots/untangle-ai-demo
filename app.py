"""untangle-ai — Co-Planner 메인 화면 (F1) + 브레인덤프(F2) + 쪼개기(F3) 흐름.

Streamlit 진입점. `uv run streamlit run app.py` 로 실행한다.
이 파일은 화면(UI)만 담당하고, 실제 로직은 features/* 를 호출한다.

F1 인수 기준:
- F1-1 자유 텍스트 입력          → st.chat_input
- F1-2 턴 진행·직전 맥락 유지     → coplanner.respond(active) 에 대화 전체 전달
- F1-3 대화 시작 전 의도 선택     → 대화 전 st.radio, 시작 후 모드 고정
- F1-4 대화 원본 저장·열람        → 생성 즉시 save_conversation, '대화 기록' 페이지에서 열람

F2 인수 기준(브레인덤프):
- F2-1 긴 자유 입력              → st.chat_input (F1-1 과 같은 통로)
- F2-2 할 일 후보 추출           → coplanner.route → brain_dump.extract (call_llm)
- F2-3 부담 없는 분량(≤5)        → brain_dump 가 5개로 제한
- F2-4 추출이 어려우면 재입력 안내 → 빈 결과일 때 proposal.note 를 답으로 표시
- F2-5 추가 여부는 사용자가 결정  → 아래 선택 패널에서 고른 것만 confirm 으로 반영 (GP-1)

F3 인수 기준(쪼개기):
- F3-1 큰 일(목표) 입력          → st.chat_input (F1-1 과 같은 통로)
- F3-2 이지선다로 구체화          → breakdown.start 가 만든 질문을 구체화 패널에서 하나씩 제시
- F3-3 구체화 불필요 시 건너뛰기   → 질문이 없거나 '바로 쪼개기' 선택 시 바로 분해
- F3-4 작은 단위(≤5)로 분해       → breakdown.decompose (call_llm)
- F3-5 '지금 할 첫 단계' 제시      → 결과 패널에서 first_step_id 항목을 강조
- F3-6 첫 단계 더 잘게 재쪼개기    → 결과 패널의 '더 잘게 쪼개기' → breakdown.resplit
- F3-7 확정 후 반영              → 결과 패널에서 고른 것만 confirm 으로 반영 (GP-1)

F4 인수 기준(한 줄 추가):
- F4-1 한 문장으로 단일 할 일 추가 → st.chat_input (F1-1 과 같은 통로)
- F4-2 속성(날짜·시간·우선순위·반복) 추출 → coplanner.route → single_add.parse (call_llm)
- F4-3 모호·부족 시 최소 확인      → 단서 없는 속성은 비운 채, 확정 패널에서만 검토·수정(되묻기 없음)
- F4-4 확정 후 반영              → 확정 패널의 '담기' → single_add.commit_edited (GP-1)
- F4-5 한 문장 = 한 할 일         → single_add 가 정확히 한 건만 만든다(다수 후보 아님)
"""
from __future__ import annotations

from datetime import date, time

import streamlit as st

import features
from features import ACTIVE_CONV, LLMConfigError, breakdown, confirm, coplanner, single_add
from features.coplanner import Conversation, Intent, Message
from features.todo import priority_label

st.set_page_config(page_title="untangle-ai", page_icon="🧶", layout="centered")
features.init_state()  # 메모리 저장소(session_state) 초기화


# ── 턴 처리 로직 (UI 이벤트 → features 호출) ──────────────────────
def _run_chat_turn(active: Conversation) -> None:
    """일반 대화 의도: 직전 맥락으로 다음 응답을 생성한다. (F1-2)

    오류·설정 안내는 error=True 로 남겨 화면엔 보이되 다음 턴 맥락엔 섞이지 않게 한다.
    """
    with st.spinner("Co-Planner가 생각 중…"):
        is_error = False
        try:
            reply = coplanner.respond(active)
            if not reply.strip():  # 빈 응답 방어(빈 말풍선·다음 턴 오염 방지)
                is_error = True
                reply = "⚠️ 빈 응답을 받았어요. 한 번만 더 말씀해 주시겠어요?"
        except LLMConfigError as exc:
            is_error = True
            reply = (
                f"⚠️ {exc}\n\n"
                "설정 방법은 README의 'API 키 설정'을 참고해주세요."
            )
        except Exception as exc:  # 호출 실패에도 대화가 끊기지 않게
            is_error = True
            reply = (
                "⚠️ 지금은 응답을 만들지 못했어요. 잠시 후 다시 시도해주세요. "
                f"({type(exc).__name__})"
            )
    active.messages.append(Message("assistant", reply, error=is_error))


def _run_brain_dump_turn(active: Conversation, user_text: str) -> None:
    """브레인덤프 의도: 입력에서 할 일 후보를 뽑아 확정 대기로 올린다. (F2-2~F2-4)

    후보가 있으면 stage 로 대기시키고(GP-1), 아래 선택 패널이 렌더된다(F2-5).
    후보가 없으면(F2-4) 재입력 안내를 assistant 메시지로 보여준다.
    """
    with st.spinner("생각을 할 일로 정리하는 중…"):
        try:
            proposal = coplanner.route(active.intent, user_text)  # → brain_dump.extract
        except LLMConfigError as exc:
            active.messages.append(Message(
                "assistant",
                f"⚠️ {exc}\n\n설정 방법은 README의 'API 키 설정'을 참고해주세요.",
                error=True,
            ))
            return
        except Exception as exc:  # 호출 실패에도 대화가 끊기지 않게
            active.messages.append(Message(
                "assistant",
                "⚠️ 지금은 할 일을 뽑지 못했어요. 잠시 후 다시 시도해주세요. "
                f"({type(exc).__name__})",
                error=True,
            ))
            return

    if proposal.drafts:
        confirm.stage(proposal)  # 확정 전 대기 — 아직 데이터 미반영 (GP-1)
        active.messages.append(Message(
            "assistant",
            "이런 할 일들이 보여요 — 아래에서 오늘 할 일에 담을 걸 골라주세요.",
        ))
    else:
        # F2-4: 추출이 어려운(추상적·비실행적) 입력엔 빈 결과 + 재입력 안내
        confirm.clear_pending()  # 직전에 남은 제안이 있으면 정리한다
        active.messages.append(Message(
            "assistant",
            proposal.note or "조금만 더 구체적으로 적어줄래요?",
        ))


def _render_brain_dump_panel(active: Conversation) -> None:
    """확정 대기 중인 브레인덤프 후보를 선택·확정 UI로 보여준다. (F2-5, GP-1)

    - 후보는 체크박스로 보여주고 기본 선택 상태로 둔다(담기 쉽게).
    - '담기'는 선택한 것만 오늘 할 일에 반영하고 나머지는 보관한다(F6-3).
    - '안 할게요'는 아무것도 반영하지 않고 후보를 보관한 뒤 패널을 닫는다.
    """
    proposal = confirm.get_pending()
    if proposal is None or proposal.source != "brain_dump" or not proposal.drafts:
        return

    st.divider()
    st.markdown("**뽑아낸 할 일 후보** — 오늘 할 일에 담을 것만 골라주세요.")
    for draft in proposal.drafts:
        label = draft.title if not draft.memo else f"{draft.title} · {draft.memo}"
        st.checkbox(label, value=True, key=f"pick_{draft.id}")

    col_add, col_skip = st.columns(2)
    if col_add.button("✅ 선택한 할 일 담기", use_container_width=True):
        selected = [d.id for d in proposal.drafts if st.session_state.get(f"pick_{d.id}", True)]
        confirm.confirm(selected)  # 선택만 반영, 나머지는 보관 (F2-5, F6-3)
        count = len(selected)
        active.messages.append(Message(
            "assistant",
            f"{count}개를 '오늘 할 일'에 담았어요. 사이드바의 '오늘 할 일'에서 확인할 수 있어요."
            if count else "이번엔 아무것도 담지 않았어요. 언제든 다시 정리해도 좋아요.",
        ))
        st.rerun()
    if col_skip.button("이번엔 안 할게요", use_container_width=True):
        confirm.confirm([])  # 반영 없이 후보를 전부 보관한다(유실 없음, F6-3)
        active.messages.append(Message(
            "assistant",
            "알겠어요, 지금은 그대로 둘게요. 필요할 때 다시 꺼내볼 수 있어요.",
        ))
        st.rerun()


# ── 쪼개기 흐름 (F3) ──────────────────────────────────────────────
def _append_llm_error(active: Conversation, exc: Exception, *, doing: str) -> None:
    """LLM 설정/호출 오류를 대화에 안내 메시지로 남긴다(앱은 멈추지 않는다).

    error=True 로 남겨 화면엔 보이되 다음 턴 LLM 맥락에는 섞이지 않게 한다.
    """
    if isinstance(exc, LLMConfigError):
        text = f"⚠️ {exc}\n\n설정 방법은 README의 'API 키 설정'을 참고해주세요."
    else:
        text = f"⚠️ 지금은 {doing} 못했어요. 잠시 후 다시 시도해주세요. ({type(exc).__name__})"
    active.messages.append(Message("assistant", text, error=True))


def _decompose_and_stage(active: Conversation, session: breakdown.BreakdownSession) -> None:
    """구체화가 끝난 세션을 작은 단위로 분해해 확정 대기로 올린다. (F3-4, F3-5, F3-7)"""
    with st.spinner("작은 단위로 쪼개는 중…"):
        try:
            proposal = breakdown.decompose(session.goal, session.answers)
        except Exception as exc:  # LLMConfigError 포함
            _append_llm_error(active, exc, doing="할 일을 쪼개지")
            return

    if proposal.drafts:
        confirm.stage(proposal)  # 확정 전 대기 — 아직 데이터 미반영 (GP-1, F3-7)
        active.messages.append(Message(
            "assistant",
            "이렇게 나눠봤어요. '지금 할 첫 단계'부터 가볍게 시작해요 — 아래에서 담을 것을 골라주세요.",
        ))
    else:
        # 분해가 어려운(너무 막연한) 입력엔 빈 결과 + 재입력 안내
        confirm.clear_pending()
        active.messages.append(Message(
            "assistant",
            proposal.note or "이 일을 조금 더 구체적으로 적어줄래요?",
        ))


def _run_breakdown_turn(active: Conversation, user_text: str) -> None:
    """쪼개기 의도의 자유 입력 턴. (F3-1~F3-3)

    - 구체화 진행 중이면 입력을 현재 질문의 답으로 받아 다음으로 넘어간다.
    - 그 외에는 새 목표로 보고 구체화 필요 여부를 판단한다(필요 없으면 바로 분해).
    """
    session = breakdown.get_session()

    # 구체화 진행 중: 사용자가 패널 대신 직접 답을 적은 경우 → 현재 질문의 답으로 기록
    if session is not None and breakdown.is_clarifying(session):
        breakdown.answer(session, user_text)
        if breakdown.is_clarifying(session):
            active.messages.append(Message("assistant", "좋아요, 이어서 하나만 더 골라볼게요."))
        else:
            _decompose_and_stage(active, session)  # 마지막 답 → 바로 분해
        return

    # 새 목표 입력 → 구체화 필요 여부 판단 (이전 제안이 남았으면 정리)
    confirm.clear_pending()
    with st.spinner("이 일을 어떻게 쪼갤지 살펴보는 중…"):
        try:
            session = breakdown.start(user_text)
        except Exception as exc:  # LLMConfigError 포함
            breakdown.clear_session()
            _append_llm_error(active, exc, doing="쪼개기를 시작하지")
            return

    breakdown.set_session(session)
    if breakdown.is_clarifying(session):
        active.messages.append(Message(
            "assistant",
            "이 큰 일을 잘 쪼개기 위해 몇 가지만 골라볼게요. 아래에서 선택해주세요.",
        ))
    else:
        _decompose_and_stage(active, session)  # F3-3: 구체화 불필요 → 바로 분해


def _render_breakdown_clarify_panel(active: Conversation) -> None:
    """구체화 질문을 한 번에 하나씩 이지선다로 보여준다. (F3-2, F3-3)"""
    session = breakdown.get_session()
    if session is None or not breakdown.is_clarifying(session):
        return

    q = breakdown.current_question(session)
    idx, total = session.cursor, len(session.questions)

    st.divider()
    st.markdown(f"**구체화 질문 {idx + 1} / {total}**")
    # index=None: 기본 선택 없이 사용자가 직접 고르게 한다. key 에 cursor 를 넣어 질문마다 초기화.
    st.radio(q.question, q.options, index=None, key=f"bd_q_{idx}")

    c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
    if c1.button("이 선택으로 계속", use_container_width=True):
        choice = st.session_state.get(f"bd_q_{idx}")
        if not choice:
            st.warning("하나만 골라주세요. (또는 '이 질문 건너뛰기')")
        else:
            breakdown.answer(session, choice)
            if not breakdown.is_clarifying(session):
                _decompose_and_stage(active, session)
            st.rerun()
    if c2.button("이 질문 건너뛰기", use_container_width=True):
        breakdown.skip_current(session)
        if not breakdown.is_clarifying(session):
            _decompose_and_stage(active, session)
        st.rerun()
    if c3.button("바로 쪼개기", use_container_width=True):  # F3-3
        breakdown.skip_all(session)
        _decompose_and_stage(active, session)
        st.rerun()


def _render_breakdown_result_panel(active: Conversation) -> None:
    """분해 결과를 보여주고 담기·재쪼개기·취소를 처리한다. (F3-5, F3-6, F3-7, GP-1)"""
    proposal = confirm.get_pending()
    if proposal is None or proposal.source != "breakdown" or not proposal.drafts:
        return

    st.divider()
    if proposal.note:
        st.caption(proposal.note)
    st.markdown("**쪼갠 할 일** — 오늘 할 일에 담을 것을 골라주세요.")

    first = None
    for draft in proposal.drafts:
        is_first = draft.id == proposal.first_step_id
        label = draft.title if not draft.memo else f"{draft.title} · {draft.memo}"
        if is_first:
            first = draft
            label = f"👉 지금 할 첫 단계 — {label}"  # F3-5
        st.checkbox(label, value=True, key=f"pick_{draft.id}")

    # F3-6: '지금 할 첫 단계'가 여전히 크면 그 단계를 더 잘게 다시 쪼갠다.
    if first is not None and st.button(
        "🔬 '지금 할 첫 단계'가 아직 커요 — 더 잘게 쪼개기", use_container_width=True
    ):
        _resplit_first_step(active, first)

    col_add, col_skip = st.columns(2)
    if col_add.button("✅ 선택한 할 일 담기", use_container_width=True):
        selected = [d.id for d in proposal.drafts if st.session_state.get(f"pick_{d.id}", True)]
        confirm.confirm(selected)  # 선택만 반영, 나머지는 보관 (F3-7, F6-3)
        breakdown.clear_session()
        count = len(selected)
        active.messages.append(Message(
            "assistant",
            f"{count}개를 '오늘 할 일'에 담았어요. 사이드바의 '오늘 할 일'에서 확인할 수 있어요."
            if count else "이번엔 아무것도 담지 않았어요. 언제든 다시 쪼개봐도 좋아요.",
        ))
        st.rerun()
    if col_skip.button("이번엔 안 할게요", use_container_width=True):
        confirm.confirm([])  # 반영 없이 후보를 전부 보관한다(유실 없음, F6-3)
        breakdown.clear_session()
        active.messages.append(Message(
            "assistant",
            "알겠어요, 지금은 그대로 둘게요. 필요할 때 다시 꺼내볼 수 있어요.",
        ))
        st.rerun()


def _resplit_first_step(active: Conversation, first) -> None:
    """'지금 할 첫 단계'를 더 잘게 다시 쪼개 확정 대기 제안을 교체한다. (F3-6)"""
    current = confirm.get_pending()
    session = breakdown.get_session()
    goal = session.goal if session is not None else None
    with st.spinner("더 잘게 쪼개는 중…"):
        try:
            finer = breakdown.resplit(first.title, goal=goal)
        except Exception as exc:  # LLMConfigError 포함
            _append_llm_error(active, exc, doing="더 잘게 쪼개지")
            finer = None

    if finer is not None and finer.drafts:
        # 첫 단계만 하위 단계로 교체하고 나머지 단계는 그대로 둔다(유실 없음). (F3-6)
        if current is not None and current.source == "breakdown":
            merged = breakdown.splice_first_step(current, first.id, finer.drafts)
        else:
            merged = finer
        confirm.stage(merged)
        active.messages.append(Message(
            "assistant",
            f"'{first.title}'를 더 잘게 쪼갰어요. 나머지 단계는 그대로 두었어요 — 다시 골라주세요.",
        ))
    elif finer is not None:
        active.messages.append(Message(
            "assistant",
            "이 단계는 더 잘게 쪼개기 어려웠어요. 지금 크기로도 충분히 작아 보여요.",
        ))
    st.rerun()


# ── 한 줄 추가 흐름 (F4) ──────────────────────────────────────────
def _run_single_add_turn(active: Conversation, user_text: str) -> None:
    """한 줄 추가 의도: 한 문장에서 할 일 하나를 추출해 확정 대기로 올린다. (F4-1~F4-5)

    - 후보가 있으면 stage 로 대기시키고(GP-1), 아래 확정 패널에서 검토·수정 후 담는다(F4-4).
    - 할 일로 볼 수 없는 입력(감정·질문 등)이면 재입력 안내를 보여준다(F4-1).
    - 최신 한 문장 기준이라, 직전에 남은 제안이 있으면 새 추출로 교체한다(F2 브레인덤프와 동일 방침).
    """
    confirm.clear_pending()  # 최신 한 문장 기준 — 직전 제안 정리
    with st.spinner("한 문장에서 할 일을 정리하는 중…"):
        try:
            proposal = coplanner.route(active.intent, user_text)  # → single_add.parse
        except Exception as exc:  # LLMConfigError 포함
            _append_llm_error(active, exc, doing="할 일을 정리하지")
            return

    if proposal.drafts:
        confirm.stage(proposal)  # 확정 전 대기 — 아직 데이터 미반영 (GP-1, F4-4)
        active.messages.append(Message(
            "assistant",
            "이렇게 이해했어요 — 아래에서 확인하고 필요하면 고친 뒤 담아주세요.",
        ))
    else:
        # F4-1: 할 일로 볼 수 없는 입력엔 빈 결과 + 재입력 안내
        confirm.clear_pending()
        active.messages.append(Message(
            "assistant",
            proposal.note or "한 문장으로 조금만 더 또렷하게 적어줄래요?",
        ))


def _render_single_add_panel(active: Conversation) -> None:
    """추출한 단일 할 일을 검토·수정해 담는 확정 패널. (F4-2~F4-5, GP-1)

    - 한 건만 다룬다(F4-5). 채워진 속성을 보여주되 전부 그 자리에서 수정 가능(F4-2·F4-3).
    - 되묻기 대화 없이 이 패널 하나로 확인한다(과도한 질문 금지, F4-3).
    - '담기'를 눌러야 오늘 할 일에 반영된다(F4-4, GP-1).
    """
    proposal = confirm.get_pending()
    if proposal is None or proposal.source != "single_add" or not proposal.drafts:
        return

    draft = proposal.drafts[0]  # F4-5: 한 문장 = 한 할 일
    st.divider()
    st.markdown("**이렇게 이해했어요** — 확인하고 필요한 것만 고쳐 담아주세요.")

    title = st.text_input("할 일", value=draft.title, key=f"sa_title_{draft.id}")

    labels = ["높음", "중간", "낮음", "없음"]
    cur = priority_label(draft.priority)
    prio = st.radio(
        "우선순위",
        labels,
        index=labels.index(cur) if cur in labels else 3,
        horizontal=True,
        key=f"sa_prio_{draft.id}",
    )

    # 날짜·시간은 '지정 안 함'을 표현할 수 있게 체크박스로 켜고 끈다(단서 없으면 꺼진 채로).
    # 위젯은 끄더라도 항상 마운트하고 disabled 로만 비활성화한다 — 조건부 렌더로 미표시하면
    # Streamlit 이 그 실행에서 위젯 key 를 session_state 에서 지워, 껐다 켤 때 사용자가 고친
    # 값이 원래 추출값으로 되돌아가는 함정을 피한다.
    c_date, c_time = st.columns(2)
    use_date = c_date.checkbox("📅 날짜", value=draft.due_date is not None, key=f"sa_usedate_{draft.id}")
    picked_date = c_date.date_input(
        "날짜", value=draft.due_date or date.today(),
        key=f"sa_date_{draft.id}", label_visibility="collapsed", disabled=not use_date,
    )
    due_date = picked_date if use_date else None

    use_time = c_time.checkbox("⏰ 시간", value=draft.due_time is not None, key=f"sa_usetime_{draft.id}")
    picked_time = c_time.time_input(
        "시간", value=draft.due_time or time(9, 0),
        key=f"sa_time_{draft.id}", label_visibility="collapsed", disabled=not use_time,
    )
    due_time = picked_time if use_time else None

    recurrence = st.text_input(
        "🔁 반복 (예: 매주 월요일 — 없으면 비워두세요)",
        value=draft.recurrence or "", key=f"sa_recur_{draft.id}",
    )
    memo = st.text_input("메모 (선택)", value=draft.memo, key=f"sa_memo_{draft.id}")

    col_add, col_skip = st.columns(2)
    if col_add.button("✅ 오늘 할 일에 담기", use_container_width=True, key=f"sa_add_{draft.id}"):
        if not title.strip():
            st.warning("할 일 제목을 적어주세요.")
        else:
            single_add.commit_edited(
                title=title,
                priority_label=prio,
                due_date=due_date,
                due_time=due_time,
                recurrence=recurrence,
                memo=memo,
            )  # 확정 후 반영 (F4-4, GP-1)
            active.messages.append(Message(
                "assistant",
                f"'{title.strip()}'를 '오늘 할 일'에 담았어요. 사이드바의 '오늘 할 일'에서 확인할 수 있어요.",
            ))
            st.rerun()
    if col_skip.button("이번엔 안 할게요", use_container_width=True, key=f"sa_skip_{draft.id}"):
        # 반영 없이 대기 제안만 정리한다. 원본 문장은 대화에 남아 유실되지 않는다(F1-4).
        confirm.clear_pending()
        active.messages.append(Message(
            "assistant",
            "알겠어요, 지금은 담지 않을게요. 필요할 때 한 문장으로 다시 적어주면 돼요.",
        ))
        st.rerun()


# ── 화면 렌더링 ──────────────────────────────────────────────────
st.title("🧶 untangle-ai")
st.caption("뒤섞인 생각을 '지금 할 첫 단계'로 — Co-Planner")

active = st.session_state.get(ACTIVE_CONV)

# ── F1-3: 대화 시작 전 의도(intent) 선택 ──────────────────────────
if active is None:
    intent = st.radio(
        "무엇을 도와드릴까요?",
        options=list(Intent),
        format_func=lambda i: i.label,
        horizontal=True,
        key="intent_choice",
    )
    st.caption("의도를 고르고 아래에 자유롭게 입력하면 대화가 시작돼요.")
else:
    # 대화가 시작되면 모드를 고정한다. 바꾸려면 새 대화를 시작한다. (F1-3)
    intent = active.intent
    left, right = st.columns([0.72, 0.28])
    left.caption(f"현재 모드 · {intent.label}")
    if right.button("＋ 새 대화"):
        st.session_state[ACTIVE_CONV] = None
        confirm.clear_pending()   # 이전 대화의 확정 대기 제안을 정리한다
        breakdown.clear_session()  # 진행 중이던 쪼개기 세션도 정리한다 (F3)
        st.rerun()

# ── F1-2: 지금까지의 대화(직전 맥락) 표시 ─────────────────────────
if active is not None:
    for msg in active.messages:
        st.chat_message(msg.role).write(msg.content)

# ── F2-5 / F3: 확정 대기·구체화 패널(해당 상태가 있을 때만) ────────
if active is not None:
    _render_brain_dump_panel(active)          # F2-5
    _render_breakdown_clarify_panel(active)   # F3-2·F3-3 (구체화 질문)
    _render_breakdown_result_panel(active)    # F3-5·F3-6·F3-7 (분해 결과)
    _render_single_add_panel(active)          # F4-2~F4-5 (한 줄 추가 확정)

# ── F1-1 / F2-1: 자유 텍스트 입력으로 턴 진행 ─────────────────────
user_text = st.chat_input(intent.hint)
if user_text:
    # 첫 입력이면 새 대화를 만들어 원본을 즉시 보관한다. (F1-4)
    if active is None:
        active = Conversation(intent=intent)
        coplanner.save_conversation(active)
        st.session_state[ACTIVE_CONV] = active

    active.messages.append(Message("user", user_text))  # F1-1 / F2-1

    # 의도별로 처리 경로를 나눈다: 브레인덤프는 후보 추출, 쪼개기는 구체화·분해, 그 외는 대화 응답.
    if active.intent is Intent.BRAIN_DUMP:
        _run_brain_dump_turn(active, user_text)  # F2-2~F2-4
    elif active.intent is Intent.BREAKDOWN:
        _run_breakdown_turn(active, user_text)   # F3-1~F3-4
    elif active.intent is Intent.SINGLE_ADD:
        _run_single_add_turn(active, user_text)  # F4-1~F4-5
    else:
        _run_chat_turn(active)  # F1-2
    st.rerun()

# 안내: 자세한 할 일/대화 기록은 사이드바의 페이지에서
st.divider()
st.caption("← 사이드바에서 '오늘 할 일'과 '대화 기록'을 볼 수 있어요. 대화는 자동 저장돼요.")
