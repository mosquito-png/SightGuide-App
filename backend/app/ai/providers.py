import asyncio
import logging
import os
import re
from typing import Protocol

import httpx
import openai
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.errors import UpstreamServiceError

logger = logging.getLogger(__name__)


class LanguageModel(Protocol):
    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        ...


class DeterministicLanguageModel:
    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        if image_base64:
            return f"Analyzed image frame. {prompt}"
        return prompt


_shared_client: httpx.AsyncClient | None = None
_shared_openai_client: AsyncOpenAI | None = None


def get_shared_ai_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=settings.ai_timeout_seconds,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0),
        )
    return _shared_client


def get_shared_openai_client(api_key: str, timeout: float | None = None) -> AsyncOpenAI:
    global _shared_openai_client
    req_timeout = timeout if timeout is not None else settings.ai_timeout_seconds
    if _shared_openai_client is None or _shared_openai_client.api_key != api_key:
        _shared_openai_client = AsyncOpenAI(
            api_key=api_key,
            timeout=req_timeout,
            max_retries=settings.max_retries,
        )
    return _shared_openai_client


def _get_demo_response(prompt: str, error_detail: str | None = None) -> str:
    clean_err = error_detail.replace('"', "'").replace("\n", " ").strip() if error_detail else ""
    summary = f"AI Error: {clean_err}" if clean_err else "Demo Mode: Add your GEMINI_API_KEY or OPENAI_API_KEY to the .env file to enable live AI vision."
    if "{" in prompt and "}" in prompt:
        return (
            '{\n'
            f'  "summary": "{summary}",\n'
            '  "priority": "normal",\n'
            '  "obstacles": [\n'
            '    {\n'
            f'      "label": "{summary[:60]}",\n'
            '      "location_clock": "12 o\'clock",\n'
            '      "distance": "nearby",\n'
            '      "hazard_level": "low"\n'
            '    }\n'
            '  ]\n'
            '}'
        )
    return summary


class GeminiLanguageModel:
    """Primary Gemini provider adapter supporting text and multimodal vision."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._explicit_key = api_key
        self._explicit_model = model

    @property
    def api_key(self) -> str:
        if self._explicit_key is not None:
            return self._explicit_key
        return settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "").strip()

    @property
    def model(self) -> str:
        if self._explicit_model:
            return self._explicit_model
        env_model = os.getenv("GEMINI_MODEL", "").strip() or settings.gemini_model or ""
        return env_model or "gemini-flash-latest"

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        api_key = self.api_key
        if not api_key:
            raise UpstreamServiceError("Gemini API key is not configured")

        parts: list[dict[str, object]] = [{"text": prompt}]

        if image_base64:
            mime_type = "image/jpeg"
            clean_data = image_base64.strip()
            # Parse data URI scheme if present (e.g. data:image/jpeg;base64,...)
            data_uri_match = re.match(r"^data:(image/[a-zA-Z0-9+.-]+);base64,(.+)$", clean_data, re.DOTALL)
            if data_uri_match:
                mime_type = data_uri_match.group(1)
                clean_data = data_uri_match.group(2).strip()

            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": clean_data,
                }
            })

        raw_model = (self.model or "gemini-3.6-flash").removeprefix("models/").strip()
        candidate_models = [raw_model] if raw_model else []
        for fallback in ["gemini-3.6-flash", "gemini-flash-latest", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        generation_config: dict[str, object] = {
            "temperature": 0.2,
            "maxOutputTokens": 1500,
        }
        if "{" in prompt and "}" in prompt:
            generation_config["responseMimeType"] = "application/json"

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }

        last_error_msg = ""
        client = get_shared_ai_client()

        req_headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": api_key,
        }
        req_params = None if api_key.startswith("AQ.") else {"key": api_key}

        for candidate in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate}:generateContent"
            try:
                response = await client.post(url, headers=req_headers, params=req_params, json=payload)
                response.raise_for_status()
                body = response.json()
                text = body["candidates"][0]["content"]["parts"][0]["text"].strip()
                if not text:
                    raise UpstreamServiceError("Gemini returned an empty candidate text")
                return text
            except httpx.HTTPStatusError as error:
                try:
                    err_data = error.response.json()
                    last_error_msg = err_data.get("error", {}).get("message", error.response.text)
                except Exception:
                    last_error_msg = error.response.text or str(error)

                # If 401 or 403, API key is invalid or unauthorized
                if error.response.status_code in {401, 403}:
                    raise UpstreamServiceError(f"Gemini authentication failed ({error.response.status_code}): {last_error_msg}") from error

                # If 404 (model not found), 400 (deprecated/unsupported), 429 (rate limited), or 503 (high demand), try next candidate
                if error.response.status_code in {400, 404, 429, 500, 502, 503, 504}:
                    continue
                raise UpstreamServiceError(f"Gemini error ({error.response.status_code}): {last_error_msg}") from error
            except (KeyError, IndexError, TypeError, AttributeError) as error:
                raise UpstreamServiceError("Gemini returned an invalid response structure") from error
            except (httpx.HTTPError, ValueError) as error:
                last_error_msg = str(error)
                continue

        raise UpstreamServiceError(f"Gemini request failed across models: {last_error_msg}")


class OpenAILanguageModel:
    """Fallback OpenAI provider adapter supporting text and multimodal vision (GPT-4o / GPT-4o-mini)."""

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float | None = None) -> None:
        self._explicit_key = api_key
        self._explicit_model = model
        self._explicit_timeout = timeout

    @property
    def api_key(self) -> str:
        if self._explicit_key is not None:
            return self._explicit_key
        return settings.openai_api_key or os.getenv("OPENAI_API_KEY", "").strip()

    @property
    def model(self) -> str:
        if self._explicit_model:
            return self._explicit_model
        return os.getenv("OPENAI_MODEL", "").strip() or settings.openai_model or "gpt-4o-mini"

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        api_key = self.api_key
        if not api_key:
            raise UpstreamServiceError("OpenAI API key is not configured")

        messages: list[dict[str, object]] = []

        if image_base64:
            clean_data = image_base64.strip()
            if not clean_data.startswith("data:"):
                data_url = f"data:image/jpeg;base64,{clean_data}"
            else:
                data_url = clean_data

            content_parts: list[dict[str, object]] = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url,
                        "detail": "auto",
                    },
                },
            ]
            messages.append({"role": "user", "content": content_parts})
        else:
            messages.append({"role": "user", "content": prompt})

        client = get_shared_openai_client(api_key, timeout=self._explicit_timeout)

        request_kwargs: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1500,
        }

        if "{" in prompt and "}" in prompt:
            request_kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await client.chat.completions.create(**request_kwargs)
            if not response.choices or not response.choices[0].message.content:
                raise UpstreamServiceError("OpenAI returned an empty response")
            return response.choices[0].message.content.strip()
        except openai.APIError as error:
            error_msg = getattr(error, "message", None) or str(error)
            raise UpstreamServiceError(f"OpenAI error ({type(error).__name__}): {error_msg}") from error
        except Exception as error:
            raise UpstreamServiceError(f"OpenAI request failed: {error}") from error


class FallbackLanguageModel:
    """Primary Gemini provider with automatic, transparent OpenAI fallback."""

    def __init__(
        self,
        primary: LanguageModel | None = None,
        fallback: LanguageModel | None = None,
        timeout: float | None = None,
    ) -> None:
        self.primary = primary or GeminiLanguageModel()
        self.fallback = fallback or OpenAILanguageModel()
        self.timeout = timeout

    async def complete(self, prompt: str, image_base64: str | None = None) -> str:
        timeout = self.timeout if self.timeout is not None else settings.ai_timeout_seconds
        primary_error: Exception | None = None

        # 1. Attempt Primary Provider (Gemini)
        try:
            res = await asyncio.wait_for(
                self.primary.complete(prompt, image_base64),
                timeout=timeout,
            )
            if res and res.strip():
                logger.info("AI response generated via primary provider: Gemini")
                return res.strip()
            primary_error = UpstreamServiceError("Gemini returned an empty response")
        except asyncio.TimeoutError:
            primary_error = UpstreamServiceError(f"Gemini request timed out after {timeout}s")
        except Exception as error:
            primary_error = error

        # 2. Trigger Fallback Provider (OpenAI)
        primary_err_desc = str(primary_error) or type(primary_error).__name__
        logger.warning(
            "Primary AI provider (Gemini) failed: %s. Automatically falling back to OpenAI.",
            primary_err_desc,
        )

        try:
            res = await asyncio.wait_for(
                self.fallback.complete(prompt, image_base64),
                timeout=timeout,
            )
            if res and res.strip():
                logger.info("AI response generated via fallback provider: OpenAI")
                return res.strip()
            raise UpstreamServiceError("OpenAI returned an empty response")
        except asyncio.TimeoutError as timeout_err:
            fallback_error = UpstreamServiceError(f"OpenAI fallback timed out after {timeout}s")
            logger.error("Fallback AI provider (OpenAI) also failed: %s", fallback_error)
            if settings.environment == "development":
                return _get_demo_response(prompt, f"OpenAI timed out ({timeout}s)")
            raise fallback_error from timeout_err
        except Exception as fallback_error:
            logger.error("Fallback AI provider (OpenAI) also failed: %s", fallback_error)
            if settings.environment == "development":
                combined = f"Gemini: {primary_err_desc} | OpenAI: {fallback_error}"
                return _get_demo_response(prompt, combined)
            raise UpstreamServiceError(
                f"Both AI providers failed (Gemini: {primary_err_desc}; OpenAI: {fallback_error})"
            ) from fallback_error


_default_model: LanguageModel | None = None


def get_default_language_model() -> LanguageModel:
    global _default_model
    if _default_model is None:
        _default_model = FallbackLanguageModel()
    return _default_model
