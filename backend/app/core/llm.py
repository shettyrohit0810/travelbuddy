"""LLM provider resolution.

Every supported backend speaks the OpenAI wire format, so they differ only by base_url,
model, and which optional endpoints they implement. Capabilities live in this table
rather than being inferred from a provider name -- an `is_groq`-style check silently
assumes "not Groq means OpenAI", which breaks the moment a third provider appears.
"""
from typing import Optional

from openai import OpenAI

from app.core.config import settings

PROVIDERS = {
    "openai": {
        "base_url": None, "model": "gpt-4o-mini",
        "supports_parse": True, "supports_embeddings": True,
    },
    # Model ids move: Groq retired llama-3.3-70b-versatile, and a stale id fails at
    # request time with "model does not exist", not at config time. Verify against
    # GET /models when a provider starts erroring rather than guessing a replacement.
    "groq": {
        "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b",
        "supports_parse": False, "supports_embeddings": False,
    },
    "xai": {
        "base_url": "https://api.x.ai/v1", "model": "grok-3",
        "supports_parse": False, "supports_embeddings": False,
    },
}


class NoProviderConfigured(RuntimeError):
    """No LLM key is set. Raised rather than silently degrading, so an unconfigured
    deployment is visibly unconfigured instead of quietly skipping model-backed work."""


def _api_key() -> Optional[str]:
    return settings.XAI_API_KEY if settings.LLM_PROVIDER == "xai" else settings.OPENAI_API_KEY


def provider_supports(capability: str) -> bool:
    provider = settings.LLM_PROVIDER
    return bool(provider and PROVIDERS[provider].get(capability, False))


def get_client() -> OpenAI:
    provider = settings.LLM_PROVIDER
    if provider is None:
        raise NoProviderConfigured("set OPENAI_API_KEY or XAI_API_KEY")
    config = PROVIDERS[provider]
    if config["base_url"]:
        return OpenAI(api_key=_api_key(), base_url=config["base_url"])
    return OpenAI(api_key=_api_key())


def get_model_name() -> str:
    provider = settings.LLM_PROVIDER
    if provider is None:
        raise NoProviderConfigured("set OPENAI_API_KEY or XAI_API_KEY")
    return PROVIDERS[provider]["model"]
