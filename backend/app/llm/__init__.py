"""LLM engine: provider abstraction with automatic fallback.

Supported providers
-------------------
* OpenAI (chat completions)
* Groq   (OpenAI-compatible endpoint)
* Anthropic (messages API)
* Mock   — deterministic, offline provider used when no API key is
  configured (``LLM_PROVIDER=auto`` fallback) or explicitly requested
  (``LLM_PROVIDER=mock``). It produces fully parseable, schema-conformant
  JSON so the entire multi-agent pipeline runs end-to-end without network
  access — ideal for demos and CI.
"""
