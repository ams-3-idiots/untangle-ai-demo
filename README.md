# untangle-ai

뒤섞인 생각을 '지금 할 첫 단계'로 바꿔 주는 Co-Planner 데모.

### uv 설치

아직 uv가 없다면 한 번만 설치.

- **Windows (PowerShell)**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **macOS / Linux**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

설치 후 새 터미널에서 `uv --version` 이 출력되면 정상.

## 실행 방법

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
1. 프로젝트 루트에 `.streamlit/secrets.toml` 파일을 생성.
2. 발급받은 키를 적는다. **둘 중 하나만 넣어도 되고**, 넣은 쪽을 자동으로 사용.
   ```toml
   # 아래 중 가진 키만 채워도 된다.
   OPENAI_API_KEY = "sk-..."
   ANTHROPIC_API_KEY = "sk-ant-..."

   # (선택) provider 를 강제로 고르고 싶을 때: "openai" 또는 "anthropic"
   # 지정하지 않으면 키가 있는 쪽(Anthropic 우선)을 자동으로 쓴다.
   # LLM_PROVIDER = "anthropic"

   # (선택) 모델 이름을 바꾸고 싶을 때
   # OPENAI_MODEL = "gpt-4o-mini"
   # ANTHROPIC_MODEL = "claude-sonnet-4-6"
   ```
