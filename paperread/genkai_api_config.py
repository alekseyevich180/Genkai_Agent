"""Shared API configuration for vendored external projects.

This module loads the Genkai Agent API settings from ``agents/Agent/.env`` and
provides a small compatibility layer for older OpenAI SDK call sites.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / "agents" / "Agent" / ".env"
load_dotenv(ENV_PATH, override=False)


def _strip_provider_for_openai_client(model: str) -> str:
    base_url = os.environ.get("LLM_BASE_URL", "")
    if model.startswith("github/"):
        return model[len("github/") :]
    if "api.openai.com" in base_url and model.startswith("openai/"):
        return model[len("openai/") :]
    return model


def get_api_key() -> str:
    return os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")


def get_base_url() -> str:
    return os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL", "")


def get_model(default: str = "gpt-4o-mini") -> str:
    raw = os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL") or default
    return _strip_provider_for_openai_client(raw)


def make_client() -> OpenAI:
    kwargs = {"api_key": get_api_key()}
    base_url = get_base_url()
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def install_openai_compat(openai_module) -> None:
    """Install OpenAI SDK v0-style shims backed by the configured v1+ client."""
    openai_module.api_key = get_api_key()
    if get_base_url():
        openai_module.base_url = get_base_url()

    class _ChatCompletion:
        @staticmethod
        def create(**kwargs):
            client = make_client()
            if not kwargs.get("model"):
                kwargs["model"] = get_model()
            else:
                kwargs["model"] = _strip_provider_for_openai_client(kwargs["model"])
            response = client.chat.completions.create(**kwargs)
            choices = []
            for choice in response.choices:
                content = choice.message.content or ""
                choices.append(SimpleNamespace(message={"content": content}))
            return SimpleNamespace(choices=choices)

    class _Completion:
        @staticmethod
        def create(**kwargs):
            client = make_client()
            prompt = kwargs.pop("prompt", "")
            if isinstance(prompt, list):
                prompt = "\n".join(str(item) for item in prompt)
            model = _strip_provider_for_openai_client(kwargs.pop("model", get_model()))
            stop = kwargs.pop("stop", None)
            allowed = {
                "temperature",
                "max_tokens",
                "top_p",
                "frequency_penalty",
                "presence_penalty",
            }
            chat_kwargs = {key: value for key, value in kwargs.items() if key in allowed}
            if stop is not None:
                chat_kwargs["stop"] = stop
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": str(prompt)}],
                **chat_kwargs,
            )
            text = response.choices[0].message.content or ""
            logprobs = SimpleNamespace(token_logprobs=None, tokens=None)
            return SimpleNamespace(choices=[SimpleNamespace(text=text, logprobs=logprobs)])

    openai_module.ChatCompletion = _ChatCompletion
    openai_module.Completion = _Completion
