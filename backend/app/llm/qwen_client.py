"""OpenAI-compatible local Qwen client."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from backend.app.config import settings


class QwenClient:
    """Minimal chat-completions client for `mlx_lm.server`."""

    _lock = threading.Lock()

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        timeout_seconds: int = 0,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.timeout_seconds = timeout_seconds or settings.llm_timeout_seconds

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        enable_thinking: bool = False,
    ) -> Optional[str]:
        """Send one serialized chat request.

        A process-wide lock limits local Qwen concurrency to one request.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with self._lock:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, TimeoutError, json.JSONDecodeError):
            return None
