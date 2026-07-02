# Environment

이 문서는 **개발 환경** 요구 사항에 대해 적혀있다.

## 1. 기술 스택

| 항목 | 내용 |
| --- | --- |
| 패키지·런타임 관리 | **uv** (의존성·가상환경·파이썬 버전 일괄 관리) |
| 언어 | **Python 3.9+** (`.python-version` = 3.9) |
| 웹/UI 프레임워크 | **Streamlit** (`>=1.30`) |
| LLM | **OpenAI** (`openai>=1.0`) / **Claude** (`anthropic>=0.30`) |
| 데이터 저장 | 별도 DB 없음 — `st.session_state`(메모리)에 보관 |