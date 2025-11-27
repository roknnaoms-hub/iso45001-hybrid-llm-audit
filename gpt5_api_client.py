# gpt5_api_client.py  (v0.6b)
# - example.py와 동일: Responses API + 필수 파라미터만 사용
# - temperature/response_format 미사용
# - base_url 미사용(기본 엔드포인트). 필요 시에만 스위치로 활성화 권장
# - 비JSON 응답 시 자동 래핑

import os, json, time, random, re
from typing import Optional, Dict, Any, List
from openai import OpenAI, APIStatusError, APIConnectionError, RateLimitError, APITimeoutError

MODEL   = os.getenv("OPENAI_MODEL", "gpt-5")
API_KEY = os.getenv("OPENAI_API_KEY")

RETRYABLE = (RateLimitError, APITimeoutError, APIStatusError, APIConnectionError)

def _stable_sleep(attempt: int):
    base = min(2 ** attempt, 16)
    time.sleep(base + random.random())

def _dump_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

def _wrap_free_text_as_json(raw_text: str) -> Dict[str, Any]:
    return {
        "findings": [
            {"title":"비정형 출력 처리","clause":"","reason":str(raw_text).strip(),"result":""}
        ]
    }

def _normalize_findings_order(obj: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(obj, dict) or "findings" not in obj or not isinstance(obj["findings"], list):
        return obj
    normalized: List[Dict[str, Any]] = []
    for item in obj["findings"]:
        if not isinstance(item, dict):
            normalized.append({"title":"비정형 finding","clause":"","reason":json.dumps(item, ensure_ascii=False),"result":""})
            continue
        normalized.append({
            "title": item.get("title",""),
            "clause": item.get("clause",""),
            "reason": item.get("reason",""),
            "result": item.get("result","")
        })
    obj["findings"] = normalized
    return obj

def _preserves_legacy_keys(obj: Dict[str, Any]) -> bool:
    return isinstance(obj, dict) and any(k in obj for k in {"org_focus","auditor_focus","defect_cases"})

def _extract_json_from_text(text: str):
    """설명+JSON 혼합 시 첫 번째 JSON 객체만 추출."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    cand = m.group(1).strip() if m else None
    if cand:
        try:
            return json.loads(cand)
        except Exception:
            pass
    m2 = re.search(r"\{[\s\S]*\}", text)
    if m2:
        cand2 = m2.group(0)
        try:
            return json.loads(cand2)
        except Exception:
            pass
    return None

def _build_client() -> OpenAI:
    # 기본 엔드포인트 사용(example.py와 동일)
    kwargs: Dict[str, Any] = {}
    if API_KEY:
        kwargs["api_key"] = API_KEY
    return OpenAI(**kwargs)

class GPT5Client:
    """example.py와 동일 호출 경로로 JSON 중심 사용."""
    def __init__(self, model: Optional[str] = None, temperature: float = 0.2, max_retries: int = 4):
        self.model = model or MODEL
        self.temperature = temperature  # NOTE: Responses + gpt-5 경로에선 미사용
        self.max_retries = max_retries
        self.client = _build_client()

    def _call_minimal(self, *, prompt: str) -> str:
        payload = {"model": self.model, "input": prompt}  # 필수만
        attempt = 0
        while True:
            try:
                resp = self.client.responses.create(**payload)
                return resp.output_text
            except (RateLimitError, APITimeoutError, APIConnectionError) as e:
                attempt += 1
                if attempt > self.max_retries:
                    return _dump_json(_wrap_free_text_as_json(f"API 호출 실패: 재시도 한도 초과 ({type(e).__name__})"))
                _stable_sleep(attempt)
            except APIStatusError as e:
                code = getattr(e, "status_code", None)
                msg = getattr(e, "message", str(e))
                if code and 400 <= code < 500:
                    return _dump_json(_wrap_free_text_as_json(f"API 호출 실패: HTTP {code} {msg}"))
                attempt += 1
                if attempt > self.max_retries:
                    return _dump_json(_wrap_free_text_as_json(f"API 호출 실패: 재시도 한도 초과 (HTTP {code})"))
                _stable_sleep(attempt)
            except Exception as e:
                return _dump_json(_wrap_free_text_as_json(f"예상치 못한 오류: {type(e).__name__}: {e}"))

    def chat(self, *, system: str, user: str, json_mode: bool = True) -> str:
        merged = f"[SYSTEM]\n{system}\n\n[USER]\n{user}"
        if json_mode:
            merged += (
                "\n\n[FORMAT]\n"
                "Return exactly ONE JSON object only. Keys: findings:[{title,clause,reason,result}]. "
                "No prose, no explanation, no markdown."
            )
        raw = self._call_minimal(prompt=merged)
        # 1차: 바로 파싱
        try:
            data = json.loads(raw)
        except Exception:
            # 2차: 텍스트에서 JSON만 추출
            data = _extract_json_from_text(raw)
            if data is None:
                return _dump_json(_wrap_free_text_as_json(raw))

        if _preserves_legacy_keys(data):
            return _dump_json(data)

        if "findings" not in data or not isinstance(data["findings"], list) or not data["findings"]:
            data = {"findings":[{"title":"자동 래핑 결과","clause":"","reason":json.dumps(data, ensure_ascii=False),"result":""}]}
        else:
            data = _normalize_findings_order(data)
        return _dump_json(data)

    def analyze(self, user_input: str, *, clause_hint: str = "") -> str:
        prompt = (
            "[TASK]\nYou are an ISO 45001 internal-audit assistant. Analyze the input and map to clauses.\n"
            f"[INPUT]\n{user_input}\n\n"
            "[FORMAT]\nReturn exactly ONE JSON object only. Keys: findings:[{title,clause,reason,result}]. "
            "No prose, no explanation, no markdown."
        )
        raw = self._call_minimal(prompt=prompt)

        try:
            data = json.loads(raw)
        except Exception:
            data = _extract_json_from_text(raw)
            if data is None:
                return _dump_json(_wrap_free_text_as_json(raw))

        if _preserves_legacy_keys(data):
            return _dump_json(data)

        if "findings" not in data or not isinstance(data["findings"], list) or not data["findings"]:
            data = {
                "findings":[{"title":"자동 래핑 결과","clause":clause_hint or "","reason":json.dumps(data, ensure_ascii=False),"result":""}]
            }
        else:
            data = _normalize_findings_order(data)
        return _dump_json(data)

if __name__ == "__main__":
    client = GPT5Client()
    demo = "Respond in one JSON object with keys findings:[{title,clause,reason,result}], reason before result."
    print(client.analyze(demo, clause_hint="demo"))
