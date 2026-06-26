"""로컬/외부 LLM 백엔드.

설정(config.yaml 의 llm.enabled)이 켜져 있으면 프롬프트를 자동 실행한다.
실패하면 None 을 반환해 기존 'Claude 붙여넣기' 방식으로 fallback 한다.

지원 provider:
  - openai  : OpenAI 호환 API  (POST {base_url}/v1/chat/completions)
              ← vLLM·LM Studio·사내 게이트웨이·OpenAI 등
  - ollama  : 로컬/원격 Ollama (POST {base_url}/api/generate)

보안(공개 저장소!):
  내부 엔드포인트·모델·API 키는 config/repo 에 적지 않는다.
  llm.api_key_file 이 가리키는 .env 형식 파일(예: key.txt, .gitignore 처리)에서 읽는다.
    LLM_ENDPOINT=...   LLM_MODEL=...   LLM_API_KEY=...   LLM_TIMEOUT_MS=...
  키만 환경변수(api_key_env)로 줘도 된다.
추가 패키지 불필요 — 표준 라이브러리(urllib)만 사용.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from kv.config import ROOT, load_config


def _llm_cfg() -> dict:
    return load_config().get("llm", {}) or {}


def _secrets() -> dict:
    """api_key_file(.env 형식)을 파싱. 없으면 빈 dict."""
    name = _llm_cfg().get("api_key_file")
    if not name:
        return {}
    p = Path(name)
    candidates = [p, ROOT.parent / name, ROOT / name]
    for c in candidates:
        try:
            if c.is_file():
                out: dict = {}
                for line in c.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
                return out
        except Exception:
            continue
    return {}


def _provider() -> str:
    return (_llm_cfg().get("provider") or "openai").lower()


def _base_url() -> str:
    return (_secrets().get("LLM_ENDPOINT") or _llm_cfg().get("base_url") or "").strip()


def _model() -> str:
    return (_secrets().get("LLM_MODEL") or _llm_cfg().get("model") or "").strip()


def _timeout() -> int:
    ms = _secrets().get("LLM_TIMEOUT_MS")
    if ms and str(ms).isdigit():
        return max(5, int(ms) // 1000)
    return int(_llm_cfg().get("timeout", 120))


def _api_key() -> str:
    env_name = _llm_cfg().get("api_key_env", "KV_LLM_API_KEY")
    return (os.environ.get(env_name) or _secrets().get("LLM_API_KEY") or "").strip()


def llm_enabled() -> bool:
    return bool(_llm_cfg().get("enabled", False))


def has_key() -> bool:
    return bool(_api_key())


def _chat_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def llm_available() -> bool:
    """설정 on + (provider별) 연결 가능 여부."""
    if not llm_enabled():
        return False
    if _provider() == "openai":
        return bool(_base_url()) and bool(_api_key())
    # ollama: 서버 핑
    base = (_base_url() or "http://localhost:11434").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict | None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def generate(prompt: str, *, system: str | None = None) -> str | None:
    """LLM 으로 프롬프트 실행. 실패 시 None."""
    if not llm_enabled():
        return None
    model = _model()
    timeout = _timeout()
    system = system or _llm_cfg().get("system")

    if _provider() == "openai":
        base = _base_url()
        if not base:
            return None
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        headers = {}
        key = _api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = _post_json(
            _chat_url(base),
            {"model": model, "messages": messages, "stream": False},
            headers,
            timeout,
        )
        if not body:
            return None
        try:
            return (body["choices"][0]["message"]["content"] or "").strip() or None
        except (KeyError, IndexError, TypeError):
            return None

    # ollama
    base = (_base_url() or "http://localhost:11434").rstrip("/")
    payload: dict = {"model": model or "qwen2.5", "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system
    body = _post_json(f"{base}/api/generate", payload, {}, timeout)
    if not body:
        return None
    return (body.get("response") or "").strip() or None
