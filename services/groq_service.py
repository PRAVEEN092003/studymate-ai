import os
import time
import random
import logging
import requests
from typing import List, Dict, Any, Tuple

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
logger = logging.getLogger(__name__)


class GroqService:
    def __init__(self):
        self._default_key = os.getenv("GROQ_API_KEY", "").strip()
        self._default_model = "openai/gpt-oss-20b"
        self._default_timeout = 30
        self._default_max_tokens = 768
        self._default_max_retries = 2

    @property
    def model(self) -> str:
        """Fetch current model dynamically from environment or fallback to configured default."""
        return os.getenv("GROQ_MODEL", "").strip() or self._default_model

    @model.setter
    def model(self, value: str):
        self._default_model = value.strip() if value else "openai/gpt-oss-20b"

    @property
    def timeout(self) -> int:
        """Fetch timeout dynamically from environment or fallback to default."""
        try:
            return max(int(os.getenv("GROQ_TIMEOUT", str(self._default_timeout))), 5)
        except ValueError:
            return self._default_timeout

    @timeout.setter
    def timeout(self, value: int):
        self._default_timeout = max(int(value), 5)

    @property
    def max_tokens(self) -> int:
        """Fetch max tokens dynamically from environment or fallback to default."""
        try:
            return max(int(os.getenv("GROQ_MAX_TOKENS", str(self._default_max_tokens))), 100)
        except ValueError:
            return self._default_max_tokens

    @max_tokens.setter
    def max_tokens(self, value: int):
        self._default_max_tokens = max(int(value), 100)

    @property
    def max_retries(self) -> int:
        """Fetch max retries dynamically from environment or fallback to default."""
        try:
            return max(0, min(int(os.getenv("GROQ_MAX_RETRIES", str(self._default_max_retries))), 5))
        except ValueError:
            return self._default_max_retries

    @max_retries.setter
    def max_retries(self, value: int):
        self._default_max_retries = max(0, min(int(value), 5))

    @property
    def api_key(self) -> str:
        """Fetch current API key dynamically from environment or fallback to initialized key."""
        return os.getenv("GROQ_API_KEY", self._default_key).strip()

    @api_key.setter
    def api_key(self, value: str):
        self._default_key = value.strip() if value else ""

    def is_configured(self) -> bool:
        """Check if a non-placeholder Groq API key is configured."""
        key = self.api_key
        return bool(key and key != "your_groq_api_key_here")

    def _sanitize_error_message(self, message: str) -> str:
        """Strip sensitive credentials from error messages to prevent leakage."""
        current_key = self.api_key
        if current_key and current_key in message:
            message = message.replace(current_key, "[REDACTED_API_KEY]")
        env_key = os.getenv("GROQ_API_KEY", "").strip()
        if env_key and env_key in message:
            message = message.replace(env_key, "[REDACTED_API_KEY]")
        return message

    def call_chat_completion(
        self,
        messages: List[Dict[str, str]],
        custom_max_tokens: int = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Send chat completion request to Groq API with bounded retries, exponential backoff, and jitter.

        Returns:
            Tuple[bool, str, Dict]: (success, response_or_error_message, metadata)
        """
        if not self.is_configured():
            return (
                False,
                "Groq API key is not configured. Please set GROQ_API_KEY in your .env file.",
                {"status_code": 503, "error_type": "configuration_error"}
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": custom_max_tokens or self.max_tokens,
            "temperature": 0.7
        }

        attempts = 0
        backoff_delay = 1.0

        while attempts <= self.max_retries:
            try:
                response = requests.post(
                    GROQ_ENDPOINT,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout
                )

                # Successful generation
                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        msg = choices[0]["message"]
                        content = (msg.get("content") or "").strip()
                        if not content and "reasoning" in msg:
                            content = (msg.get("reasoning") or "").strip()
                        if content:
                            usage = data.get("usage", {})
                            return (
                                True,
                                content,
                                {
                                    "model": self.model,
                                    "usage": usage,
                                    "prompt_tokens": usage.get("prompt_tokens", 0),
                                    "completion_tokens": usage.get("completion_tokens", 0),
                                    "total_tokens": usage.get("total_tokens", 0),
                                    "status_code": 200
                                }
                            )
                    return (
                        False,
                        "Received an empty response from Groq.",
                        {"status_code": 502, "error_type": "empty_response"}
                    )

                # Inspect error payload for quota exhaustion or specific errors
                error_body = ""
                error_code = ""
                try:
                    err_json = response.json()
                    if "error" in err_json:
                        error_body = err_json["error"].get("message", "")
                        error_code = err_json["error"].get("code", "")
                except Exception:
                    pass

                # Check if quota is explicitly exhausted
                if "insufficient_quota" in error_code or "quota" in error_body.lower():
                    clean_msg = self._sanitize_error_message(
                        "Groq API quota exhausted. Please check your account limits or try again later."
                    )
                    return (
                        False,
                        clean_msg,
                        {"status_code": response.status_code, "error_type": "quota_exhausted"}
                    )

                # Handle Rate Limit (HTTP 429) with bounded retries, jitter & Retry-After
                if response.status_code == 429:
                    attempts += 1
                    if attempts > self.max_retries:
                        return (
                            False,
                            "Groq API rate limit reached. All retry attempts exhausted. Your message was preserved.",
                            {"status_code": 429, "error_type": "rate_limit_exceeded"}
                        )

                    # Inspect Retry-After header
                    retry_after_header = response.headers.get("Retry-After")
                    if retry_after_header:
                        try:
                            # Respect Retry-After capped at a reasonable max to avoid indefinite wait
                            sleep_duration = min(float(retry_after_header), 12.0)
                        except ValueError:
                            sleep_duration = backoff_delay
                    else:
                        # Exponential backoff with jitter
                        jitter = random.uniform(0.1, 0.6)
                        sleep_duration = backoff_delay + jitter

                    time.sleep(sleep_duration)
                    backoff_delay *= 2  # Exponential backoff
                    continue

                # Handle Authentication Error (HTTP 401)
                if response.status_code == 401:
                    logger.error("Groq API authentication failed (HTTP 401). Please check GROQ_API_KEY configuration.")
                    return (
                        False,
                        "Invalid Groq API key. Please check your server GROQ_API_KEY configuration.",
                        {"status_code": 401, "error_type": "authentication_error"}
                    )

                # Handle other API client or server errors
                error_msg = f"Groq API returned an error (HTTP {response.status_code})."
                if error_body:
                    error_msg = f"Groq API: {error_body}"
                error_msg = self._sanitize_error_message(error_msg)
                logger.warning("Groq API returned HTTP %s for model '%s': %s", response.status_code, self.model, error_msg)

                return (
                    False,
                    error_msg,
                    {"status_code": response.status_code, "error_type": "api_error"}
                )

            except requests.exceptions.Timeout:
                logger.warning("Groq API request timed out after %s seconds for model '%s'", self.timeout, self.model)
                return (
                    False,
                    f"Groq API request timed out after {self.timeout} seconds. Please try again.",
                    {"status_code": 504, "error_type": "timeout"}
                )
            except requests.exceptions.ConnectionError:
                logger.warning("Network connection error connecting to Groq API")
                return (
                    False,
                    "Unable to connect to Groq API. Please verify network connectivity.",
                    {"status_code": 503, "error_type": "network_error"}
                )
            except Exception as e:
                clean_err = self._sanitize_error_message(str(e))
                logger.error("Unexpected error in GroqService: %s", clean_err)
                return (
                    False,
                    f"Unexpected AI service error: {clean_err}",
                    {"status_code": 500, "error_type": "internal_error"}
                )

        return (
            False,
            "Groq request could not be completed after maximum retries.",
            {"status_code": 500, "error_type": "retry_exhausted"}
        )
