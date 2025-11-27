
# ISO45001 Audit — v0.7.3 Patch (Windows-ready)

## 포함 변경 (A: 호환성 / B: 재현성 로그)
- **A. 호환성**
  - `llm_backends.py`: OpenAI 경로가 `system=` 키워드 유무 모두 지원. LM Studio는 `/v1/models` 헬스체크 + 기본 타임아웃 15s.
  - `utils/audit_logic.py`: Pydantic v2 대응 — 모든 `.dict()` → `.model_dump()`.
  - `app.py`: 결과 후처리 `.model_dump()` 사용.

- **B. 재현성 로그**
  - `utils/audit_logger.py` 추가. 실행 시 `logs/audit_YYYYMMDD.jsonl`에 감사 레코드 자동 축적.
  - 로그 항목: `audit_id, utc timestamp, backend/model, clause_hint, hash_evidence, hash_csv, findings_count, version, elapsed_time`

## 설치
1) 이 패치 파일을 **기존 프로젝트 루트**에 덮어쓰기
2) `.env` 확인
```
LLM_BACKEND=openai
OPENAI_MODEL=gpt-5
OPENAI_API_KEY=sk-...
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_MODEL=openai/gpt-oss-20b
```
3) 실행
```
streamlit run app.py
```

## 비고
- LM Studio 원격 접속 시 방화벽/바인딩(0.0.0.0) 설정 확인.
- 선택 의존: `pytesseract`, `PyPDF2`, `pillow`, `chardet` 설치 시 기능 확장.
- 문의: v0.7.4에선 비전(PPE) 모델 연동/리포트 PDF 자동화를 제안합니다.
