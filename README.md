# untangle-ai 🧶

뒤섞인 생각을 '지금 할 첫 단계'로 바꿔 주는 Co-Planner 데모.
이 문서는 **팀원이 로컬에서 데모 페이지(Streamlit)를 띄우는 방법**을 설명한다.

> 프로젝트의 목적·기능 명세는 `docs/` 폴더를 참고한다. (`PROJECT.md`, `FEATURES.md` 등)

## 필요 환경

- **[uv](https://docs.astral.sh/uv/)** — 파이썬 버전·의존성 관리 도구 (필수)
- Python **3.9 이상** (`.python-version` 기준 3.9. uv가 자동으로 맞춰 준다)

별도로 파이썬을 미리 깔 필요는 없다. uv가 `pyproject.toml` / `uv.lock` 을 보고 알아서 설치한다.

### uv 설치

아직 uv가 없다면 한 번만 설치한다.

- **Windows (PowerShell)**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **macOS / Linux**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

설치 후 새 터미널에서 `uv --version` 이 출력되면 정상이다.

## 실행 방법

저장소를 받은 위치에서 아래 두 단계면 끝난다.

```bash
# 1) 의존성 설치 (.venv 가상환경을 만들고 uv.lock 대로 설치)
uv sync

# 2) 데모 서버 실행
uv run streamlit run app.py
```

실행되면 터미널에 주소가 뜨고 브라우저가 자동으로 열린다. (기본값 http://localhost:8501)
열리지 않으면 터미널에 표시된 **Local URL** 을 브라우저에 직접 붙여 넣는다.
서버를 멈추려면 터미널에서 `Ctrl + C`.

> 사이드바에서 **'오늘 할 일'**, **'대화 기록'** 페이지로 이동할 수 있다.

## API 키 설정 (AI 기능용)

> ⚠️ **현재 상태:** AI 호출 통로(`features/__init__.py` 의 `call_llm`)가 아직 **미구현**이다.
> 따라서 위 단계로 **화면(UI)은 정상적으로 뜨지만**, 브레인덤프·쪼개기 등 AI 기능을 실제로 실행하면
> `NotImplementedError`가 발생한다. AI 연동이 완료되기 전까지는 아래 키 설정 없이도 데모 화면 확인은 가능하다.

AI 기능이 구현되면 OpenAI / Claude API 키가 필요하다. 키는 **코드·커밋에 절대 넣지 않고**
`st.secrets`(`.streamlit/secrets.toml`)로 주입한다. (워크플로 규칙 W-5 참고)

1. 프로젝트 루트에 `.streamlit/secrets.toml` 파일을 만든다.
2. 발급받은 키를 적는다. (예시 — 실제 키 이름은 `call_llm` 구현 시 확정된다)
   ```toml
   OPENAI_API_KEY = "sk-..."
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```

이 파일은 **개인 키이므로 절대 커밋하지 않는다.**

## 자주 겪는 문제

- **`uv: command not found`** → uv가 설치되지 않았거나 PATH에 없다. 위 'uv 설치' 후 터미널을 새로 연다.
- **8501 포트가 이미 사용 중** → 다른 포트로 실행한다.
  ```bash
  uv run streamlit run app.py --server.port 8502
  ```
- **AI 기능 실행 시 `NotImplementedError`** → 정상이다. 위 'API 키 설정' 안내의 현재 상태 참고. (LLM 연동 미구현)

## 더 알아보기

| 문서 | 내용 |
| --- | --- |
| `docs/PROJECT.md` | 프로젝트 목적·핵심 사용자·핵심 가치 |
| `docs/FEATURES.md` | 기능별 요구사항(F-번호)·인수 기준 |
| `docs/ENVIRONMENT.md` | 기술 스택 |
| `docs/WORKFLOW.md` | 브랜치·커밋·PR 워크플로 |
