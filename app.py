"""untangle-ai — Co-Planner 메인 화면 (F1) + 브레인덤프 흐름 (F2).

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
"""
from __future__ import annotations

import streamlit as st

import features
from features import ACTIVE_CONV, LLMConfigError, confirm, coplanner
from features.coplanner import Conversation, Intent, Message

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
        confirm.clear_pending()  # 이전 대화의 확정 대기 제안을 정리한다
        st.rerun()

# ── F1-2: 지금까지의 대화(직전 맥락) 표시 ─────────────────────────
if active is not None:
    for msg in active.messages:
        st.chat_message(msg.role).write(msg.content)

# ── F2-5: 브레인덤프 후보 선택·확정 패널(확정 대기가 있을 때만) ────
if active is not None:
    _render_brain_dump_panel(active)

# ── F1-1 / F2-1: 자유 텍스트 입력으로 턴 진행 ─────────────────────
user_text = st.chat_input(intent.hint)
if user_text:
    # 첫 입력이면 새 대화를 만들어 원본을 즉시 보관한다. (F1-4)
    if active is None:
        active = Conversation(intent=intent)
        coplanner.save_conversation(active)
        st.session_state[ACTIVE_CONV] = active

    active.messages.append(Message("user", user_text))  # F1-1 / F2-1

    # 의도별로 처리 경로를 나눈다: 브레인덤프는 후보 추출, 그 외는 대화 응답.
    if active.intent is Intent.BRAIN_DUMP:
        _run_brain_dump_turn(active, user_text)  # F2-2~F2-4
    else:
        _run_chat_turn(active)  # F1-2
    st.rerun()

# 안내: 자세한 할 일/대화 기록은 사이드바의 페이지에서
st.divider()
st.caption("← 사이드바에서 '오늘 할 일'과 '대화 기록'을 볼 수 있어요. 대화는 자동 저장돼요.")
