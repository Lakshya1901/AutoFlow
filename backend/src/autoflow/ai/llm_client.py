"""
AI Planner — LLM Client
Unified OpenAI-compatible client supporting all providers.
Provider is swapped via AI_PROVIDER environment variable.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from autoflow.core.config import AIProvider, get_settings
from autoflow.core.logging import get_logger

logger = get_logger(__name__)


class LLMResponse:
    """Structured response from the LLM."""

    def __init__(
        self,
        content: str,
        model: str,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self.content = content
        self.model = model
        self.provider = provider
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def parse_json(self) -> Any:
        """Parse the content as JSON. Strips markdown code fences if present."""
        content = self.content.strip()
        # Strip markdown code fences
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first line (```json or ```) and last line (```)
            content = "\n".join(lines[1:-1])
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM response as JSON", error=str(e), content=content[:200])
            raise ValueError(f"LLM response is not valid JSON: {e}") from e

    def __repr__(self) -> str:
        return (
            f"LLMResponse(provider={self.provider}, model={self.model}, "
            f"tokens={self.input_tokens}+{self.output_tokens})"
        )


class LLMClient:
    """
    Unified LLM client using OpenAI SDK for all providers.

    All modern LLM providers support the OpenAI API format, so we use
    the official openai Python SDK for all of them — just with different
    base_url and api_key values.

    Provider configuration:
    ┌─────────────┬──────────────────────────────────────────┬─────────────────────────┐
    │ Provider    │ base_url                                 │ api_key                 │
    ├─────────────┼──────────────────────────────────────────┼─────────────────────────┤
    │ Ollama      │ http://localhost:11434/v1                 │ "ollama" (any string)   │
    │ OpenAI      │ https://api.openai.com/v1                 │ sk-...                  │
    │ Anthropic   │ https://api.anthropic.com/v1              │ sk-ant-...              │
    │ Gemini      │ https://generativelanguage...openai       │ AIza...                 │
    │ Groq        │ https://api.groq.com/openai/v1            │ gsk_...                 │
    │ Custom      │ <CUSTOM_AI_BASE_URL>                      │ <CUSTOM_AI_API_KEY>     │
    └─────────────┴──────────────────────────────────────────┴─────────────────────────┘
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._provider = settings.ai_provider
        self._model = settings.resolved_ai_model

        self._client = AsyncOpenAI(
            base_url=settings.resolved_ai_base_url,
            api_key=settings.resolved_ai_api_key,
            timeout=httpx.Timeout(
                connect=10.0,
                read=settings.ai_timeout_seconds,
                write=10.0,
                pool=5.0,
            ),
            max_retries=0,  # We handle retries via tenacity
        )

        logger.info(
            "LLM client initialized",
            provider=self._provider,
            model=self._model,
            base_url=settings.resolved_ai_base_url,
        )

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
    )
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Literal["text", "json"] = "text",
    ) -> LLMResponse:
        """
        Send a completion request to the configured LLM provider.

        Args:
            messages: List of {"role": "system"|"user"|"assistant", "content": "..."}
            model: Override the configured model for this request
            temperature: Override temperature (0.0 - 2.0)
            max_tokens: Override max output tokens
            response_format: "text" or "json" (requests JSON output mode if supported)

        Returns:
            LLMResponse with content, model info, and token counts
        """
        settings = self._settings
        resolved_model = model or self._model

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.ai_temperature,
            "max_tokens": max_tokens or settings.ai_max_tokens,
        }

        # JSON mode — not all providers support response_format
        # Ollama, OpenAI, Groq support it; Anthropic uses prompting
        if response_format == "json" and self._provider in (
            AIProvider.OPENAI, AIProvider.GROQ, AIProvider.OLLAMA
        ):
            kwargs["response_format"] = {"type": "json_object"}

        logger.debug(
            "LLM request",
            provider=self._provider,
            model=resolved_model,
            message_count=len(messages),
            response_format=response_format,
        )

        try:
            response = await self._client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content or ""
            usage = response.usage

            result = LLMResponse(
                content=content,
                model=resolved_model,
                provider=self._provider,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            )

            logger.debug(
                "LLM response received",
                provider=self._provider,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

            return result

        except Exception as e:
            logger.error(
                "LLM request failed",
                provider=self._provider,
                model=resolved_model,
                error=str(e),
            )
            raise

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Any:
        """
        Convenience method for JSON-mode completions.
        Automatically parses and returns the JSON response.
        """
        response = await self.complete(messages, response_format="json", **kwargs)
        return response.parse_json()

    async def health_check(self) -> dict[str, Any]:
        """Check if the LLM provider is reachable and responding."""
        try:
            response = await self.complete(
                [{"role": "user", "content": "Reply with just the word: OK"}],
                max_tokens=10,
                temperature=0.0,
            )
            return {
                "status": "healthy",
                "provider": self._provider,
                "model": self._model,
                "response": response.content.strip(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": self._provider,
                "model": self._model,
                "error": str(e),
            }


# ─── Singleton ────────────────────────────────────────────────────────────────

_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get the global LLM client instance. Initialized lazily."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
