# ARCHITECTURE

## 아키텍처 개요

untangle-ai는 Streamlit 기반의 Co-Planner 데모 웹앱이다. 구조는 두 갈래로 단순하게 나눈다.

- **`pages/`** — 사용자가 보는 화면(페이지)을 구현한다. Streamlit UI만 담당하고, 직접 로직을 갖지 않는다.
- **`features/`** — 각 기능의 로직을 담는다. AI 호출, 할 일 처리, 편집·확정 등 화면 뒤의 모든 동작이 여기 있다.

의존 방향은 한 방향이다: **`pages` 가 `features` 를 호출**해 결과를 화면에 표시한다.
모든 AI 결과물은 사용자가 확정하기 전까지 실제 데이터에 반영하지 않는다. 이 확정 처리도 `features` 로직 안에서 이뤄진다.

데이터는 별도 DB 없이 **`st.session_state` 에 메모리로만 보관**한다.

```
┌─────────────────────────────┐
│  pages/   (Streamlit 화면)    │   사용자가 보는 페이지
└──────────────┬──────────────┘
               │ 호출
               ▼
┌─────────────────────────────┐
│  features/  (기능 로직)        │   AI 플로우 · 할 일 처리 · 확정
└─────────────────────────────┘
```

## 디렉토리 구조

```
untangle-ai/
├── app.py                  # Streamlit 진입점 = Co-Planner 메인 화면 (F1)
├── pyproject.toml          # uv 의존성·메타데이터
├── pages/                  # 화면(페이지) 구현
│   ├── todo.py        # 오늘 할 일 목록 화면 (F7)
│   └── history.py         # 저장된 대화 열람 화면 (F1-4)
└── features/               # 기능 로직
    ├── coplanner.py        # F1 대화 턴·의도 라우팅
    ├── brain_dump.py       # F2 생각 → 할 일 후보 추출
    ├── breakdown.py        # F3 구체화 질문 → 분해 → 첫 단계
    ├── single_add.py       # F4 한 문장 → 속성 추출
    ├── suggest.py          # F5 상황·에너지 → '지금 할 일' 제안
    ├── confirm.py          # F6 편집·확정·보관 (확정 전 미반영, GP-1)
    └── todo.py             # F7 할 일 관리 (CRUD·완료 토글·우선순위)
```
