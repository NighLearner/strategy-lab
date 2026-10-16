"""llm.py — Ollama HTTP client with JSON-schema output, timeouts, retries.

Principles:
- Never relies on tool-calling. Plain JSON-in / JSON-out.
- Invalid output is retried with error message, max 3 times.
- If Ollama is unreachable, returns None (caller continues without LLM).
- Provides fake client mode (--dry-llm) for tests.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional, Type

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """Raised when Ollama is not reachable."""


class LLMClient:
    """Ollama HTTP client."""

    def __init__(self, config) -> None:
        self.cfg = config
        self._available: Optional[bool] = None

    def available(self) -> bool:
        """Check if Ollama is reachable (cached for 60s)."""
        try:
            resp = requests.get(
                f"{self.cfg.host}/api/tags", timeout=5
            )
            self._available = resp.status_code == 200
        except Exception:
            self._available = False
        return bool(self._available)

    def chat(
        self,
        messages: list[dict],
        output_model: Type[BaseModel] | None = None,
        temperature: float | None = None,
    ) -> Optional[dict]:
        """Send a chat request to Ollama.

        If output_model is provided, adds the JSON schema to the request format
        and retries on validation failure (up to max_retries).

        Returns the parsed dict or None on failure.
        """
        if not self.cfg.enabled:
            logger.info("LLM disabled in config.")
            return None

        schema = output_model.model_json_schema() if output_model else None
        temp = temperature if temperature is not None else self.cfg.temperature

        for attempt in range(self.cfg.max_retries):
            try:
                payload: dict[str, Any] = {
                    "model": self.cfg.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temp},
                    "keep_alive": self.cfg.keep_alive,
                }
                if schema:
                    payload["format"] = schema

                resp = requests.post(
                    f"{self.cfg.host}/api/chat",
                    json=payload,
                    timeout=self.cfg.timeout_s,
                )
                if resp.status_code != 200:
                    logger.warning("Ollama HTTP %d: %s", resp.status_code, resp.text[:200])
                    time.sleep(2 ** attempt)
                    continue

                body = resp.json()
                content = body.get("message", {}).get("content", "")

                if output_model is None:
                    return {"content": content}

                # Validate against pydantic model
                try:
                    parsed = json.loads(content)
                    output_model.model_validate(parsed)
                    return parsed
                except Exception as val_err:
                    logger.warning(
                        "LLM output validation failed (attempt %d): %s", attempt + 1, val_err
                    )
                    # Feed the error back to the model
                    messages = messages + [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": f"Your output was invalid: {val_err}. Please fix and return only valid JSON.",
                        },
                    ]
                    time.sleep(1)
                    continue

            except requests.exceptions.Timeout:
                logger.warning("Ollama timeout (attempt %d/%d).", attempt + 1, self.cfg.max_retries)
                time.sleep(2 ** attempt)
            except requests.exceptions.ConnectionError:
                logger.warning("Ollama connection error — LLM unavailable.")
                return None
            except Exception as exc:
                logger.error("LLM call failed: %s", exc)
                time.sleep(2 ** attempt)

        logger.error("LLM: all %d attempts failed.", self.cfg.max_retries)
        return None


# ---------------------------------------------------------------------------
# Dry-run / fake client for tests
# ---------------------------------------------------------------------------

class FakeLLMClient:
    """Returns canned responses for testing without a real Ollama instance."""

    def __init__(self, response: dict | None = None) -> None:
        self._response = response or {}

    def available(self) -> bool:
        return True

    def chat(
        self,
        messages: list[dict],
        output_model: Type[BaseModel] | None = None,
        temperature: float | None = None,
    ) -> Optional[dict]:
        if output_model:
            # Validate the canned response against the model
            try:
                output_model.model_validate(self._response)
            except Exception as e:
                logger.warning("FakeLLMClient: canned response invalid for model: %s", e)
        return self._response


def build_llm_client(config, dry_run: bool = False) -> LLMClient | FakeLLMClient:
    """Build the appropriate LLM client."""
    if dry_run:
        logger.info("LLM: dry-run mode (fake client).")
        return FakeLLMClient()
    return LLMClient(config)
