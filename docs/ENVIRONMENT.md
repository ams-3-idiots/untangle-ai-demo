# Environment

이 문서는 **개발 환경**과 **프로젝트 파일 구성**을 정리한다.
사람과 AI 에이전트가 같은 구조 위에서 일관되게 작업하도록, 무엇이 어디에 있는지와 지켜야 할 레이어 규칙을 명시한다.

## 1. 기술 스택

| 항목 | 내용 |
| --- | --- |
| 패키지·런타임 관리 | **uv** (의존성·가상환경·파이썬 버전 일괄 관리) |
| 언어 | **Python 3.9+** (`.python-version` = 3.9) |
| 웹/UI 프레임워크 | **Streamlit** (`>=1.30`) |
| LLM | **OpenAI** (`openai>=1.0`) / **Claude** (`anthropic>=0.30`) |
| 데이터 저장 | 별도 DB 없음 — `st.session_state`(메모리)에 보관 |

의존성의 정확한 버전은 `pyproject.toml`(요구 버전)과 `uv.lock`(고정 버전)에 있다. **`uv.lock`이 정본**이다.

## 2. 사전 준비 — uv 설치

uv가 없으면 한 번만 설치한다. (설치 가이드: https://docs.astral.sh/uv/)

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

파이썬은 따로 설치하지 않아도 된다. uv가 `.python-version`을 보고 맞춰 준다.

## 3. 자주 쓰는 명령

| 목적 | 명령 |
| --- | --- |
| 의존성 설치(가상환경 생성) | `uv sync` |
| 데모 서버 실행 | `uv run streamlit run app.py` |
| 다른 포트로 실행 | `uv run streamlit run app.py --server.port 8502` |
| 의존성 추가 | `uv add <패키지>` (→ `pyproject.toml`·`uv.lock` 자동 갱신) |
| 임의 스크립트 실행 | `uv run python <파일>` |

> 의존성을 바꿨다면 `pyproject.toml`과 `uv.lock`을 **같은 커밋**에 포함한다. (WORKFLOW.md 참고)

## 4. 프로젝트 파일 구성

```
untangle-ai/
├─ app.py              # Streamlit 진입점 — Co-Planner 메인 화면(F1). UI만 담당.
├─ features/           # ── 로직 레이어 (UI 없음) ──
│  ├─ __init__.py      #   session_state 키 정의, init_state(), call_llm() 단일 통로
│  ├─ coplanner.py     #   F1 대화 턴 관리 + 의도(intent) 라우팅 진입점
│  ├─ brain_dump.py    #   F2 브레인덤프(할 일 후보 추출)
│  ├─ breakdown.py     #   F3 쪼개기(구체화→분해)
│  ├─ single_add.py    #   F4 단일 할 일 자연어 추가
│  ├─ suggest.py       #   F5 상황 기반 '지금 할 일' 제안
│  ├─ confirm.py       #   사용자 확정·보관 공통 모듈(GP-1: 확정 전 미반영)
│  └─ todo.py          #   당일 할 일 CRUD·완료 토글 (FEATURES.md §6)
├─ pages/              # ── 화면 레이어 (Streamlit 멀티페이지) ──
│  ├─ todo.py          #   '오늘 할 일' 화면 (features.todo 호출)
│  └─ history.py       #   '대화 기록' 화면 (저장된 대화 열람, F1-4)
├─ docs/               # 프로젝트 문서 — 작업 전 필독 (AGENTS.md 참조)
├─ .streamlit/         # Streamlit 설정·비밀키 (secrets.toml은 커밋 금지)
├─ pyproject.toml      # 프로젝트 메타·의존성 요구 버전
├─ uv.lock             # 고정된 의존성 버전(정본)
└─ .python-version     # 파이썬 버전 고정(3.9)
```

## 5. 레이어 규칙 (협업 시 반드시 준수)

코드를 일관되게 유지하기 위한 핵심 규칙. 새 코드를 둘 위치가 헷갈리면 이 규칙으로 판단한다.

- **화면과 로직을 분리한다.**
  - `app.py`·`pages/*` → **UI만.** 위젯 렌더링과 사용자 입력 수집만 하고, 판단·가공은 `features/*`를 호출한다.
  - `features/*` → **로직만.** Streamlit 위젯을 그리지 않는다. (입출력은 함수 인자·반환값으로)
- **상태는 `st.session_state`에 모은다.** 키는 `features/__init__.py`에 정의된 상수를 쓰고, 진입 시 `init_state()`로 초기화한다. 별도 DB는 없다.
- **모든 LLM 호출은 `features.call_llm()` 한 통로로** 한다. 기능별로 OpenAI/Claude SDK를 직접 부르지 않는다. (provider 교체·키 관리를 한 곳에서)
- **AI 출력은 `confirm` 모듈을 거쳐 사용자 확정 후에만 데이터에 반영한다.** (전역 원칙 GP-1)
- **기능 ↔ 요구사항 매핑:** 각 모듈 상단 docstring에 담당 F-번호가 적혀 있다. 기능을 수정할 때는 `docs/FEATURES.md`의 해당 F-번호·인수 기준(AC)을 정본으로 삼는다.

## 6. 비밀키 · 환경 변수

- OpenAI/Claude **API 키는 코드·커밋에 절대 넣지 않는다.** (WORKFLOW.md W-5)
- 키는 `st.secrets`로 주입한다 → 루트에 `.streamlit/secrets.toml` 생성.
  ```toml
  OPENAI_API_KEY = "sk-..."
  ANTHROPIC_API_KEY = "sk-ant-..."
  ```
- 코드에서는 `st.secrets["OPENAI_API_KEY"]`처럼 읽는다. (현재 `call_llm`은 미구현 — 연동 시 이 통로에서 키를 읽도록 구현)
- `.streamlit/secrets.toml`, `.env`는 **반드시 `.gitignore`에 둔다.** 빠져 있으면 임의 진행하지 말고 알린다.

## 7. AI 에이전트 작업 체크 포인트

- 작업 시작 전 `docs/`를 먼저 읽는다. (`AGENTS.md` 필수 절차)
- 새 로직은 `features/`에, 새 화면은 `app.py`/`pages/`에 둔다. (위 레이어 규칙)
- 의존성 추가는 `uv add`로 하고 `uv.lock`을 함께 커밋한다.
- 변경 후 `uv run streamlit run app.py`로 앱이 뜨는지 스모크 확인한다. (테스트 프레임워크 없음)
