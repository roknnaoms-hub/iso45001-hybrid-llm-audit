
# llm_backends.py — v0.7.3 (compat + healthcheck)
import os, json, requests, time
from typing import Any, Dict
from utils.audit_logic import normalize_findings_json

class BaseBackend:
    name = "base"
    def generate(self, system: str, user: str, **kw) -> Dict[str, Any]:
        raise NotImplementedError

class OpenAIBackend(BaseBackend):
    name = "openai"
    def __init__(self):
        from gpt5_api_client import GPT5Client
        self.client = GPT5Client()
    def generate(self, system: str, user: str, **kw) -> Dict[str, Any]:
        clause_hint = kw.get("clause_hint","")
        # 일부 빌드는 system 키워드를 받지 않음 → 안전 호환 호출
        try:
            raw = self.client.analyze(user, clause_hint=clause_hint, system=system)
        except TypeError:
            raw = self.client.analyze(user, clause_hint=clause_hint)
        return normalize_findings_json(raw)

class OllamaBackend(BaseBackend):
    name = "ollama"
    def __init__(self, base_url=None, model=None, timeout=30):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model    = model    or os.getenv("OLLAMA_MODEL", "llama3:8b-instruct")
        self.timeout  = timeout
    def generate(self, system: str, user: str, **kw) -> Dict[str, Any]:
        prompt = f"[SYSTEM]\n{system}\n\n[USER]\n{user}"
        r = requests.post(f"{self.base_url}/api/generate",
                          json={"model": self.model, "prompt": prompt, "stream": False},
                          timeout=self.timeout)
        r.raise_for_status()
        txt = r.json().get("response","")
        return normalize_findings_json(txt)

class LMStudioBackend(BaseBackend):
    name = "lmstudio"
    def __init__(self, base_url=None, model=None, timeout=15):
        env_url = base_url or os.getenv("LMSTUDIO_BASE_URL")
        # 기본 후보 엔드포인트
        candidates = [env_url] if env_url else [
            "http://127.0.0.1:1234/v1",
            "http://localhost:1234/v1",
            os.getenv("LMSTUDIO_FALLBACK_URL")
        ]
        self.endpoints = [u for u in candidates if u]
        self.model    = model or os.getenv("LMSTUDIO_MODEL", "openai/gpt-oss-20b")
        self.timeout  = timeout

    def _health_ok(self, base):
        try:
            r = requests.get(f"{base}/models", timeout=5)
            return r.ok
        except Exception:
            return False

    def generate(self, system: str, user: str, **kw) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role":"system","content":system},{"role":"user","content":user}],
            "temperature": 0.2
        }
        last_err = None
        for base in self.endpoints:
            try:
                if not self._health_ok(base):
                    last_err = RuntimeError(f"LM Studio health check failed: {base}/models")
                    continue
                r = requests.post(f"{base}/chat/completions", headers=headers, json=payload, timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
                txt  = data["choices"][0]["message"]["content"]
                return normalize_findings_json(txt)
            except Exception as e:
                last_err = e
                continue
        if last_err:
            raise last_err
        raise RuntimeError("No LM Studio endpoint reachable")

def get_backend(name: str|None=None, **kw) -> BaseBackend:
    name = (name or os.getenv("LLM_BACKEND","openai")).lower()
    if name == "ollama":
        return OllamaBackend(**kw)
    if name == "lmstudio":
        return LMStudioBackend(**kw)
    return OpenAIBackend()
