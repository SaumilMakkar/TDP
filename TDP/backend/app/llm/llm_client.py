"""llm_client.py - UHG OAuth + Azure OpenAI client for dynamic weighting.

This module obtains an OAuth token from UHG, calls Azure OpenAI chat completions,
and returns a parsed JSON object expected by the orchestrator.

Required environment variables:
    UHG_CLIENT_ID
    UHG_CLIENT_SECRET
    UHG_PROJECT_ID

Optional environment variables (sane defaults are provided):
    UHG_OAUTH_TOKEN_URL
    UHG_SCOPE
    UHG_AZURE_OPENAI_ENDPOINT
    UHG_AZURE_OPENAI_API_VERSION
    UHG_AZURE_OPENAI_DEPLOYMENT
    UHG_AZURE_OPENAI_MODEL
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

try:
        import openai
except ImportError:  # pragma: no cover
        openai = None

logger = logging.getLogger("pbm.llm_client")


class LLMConfigError(Exception):
    """Raised when LLM configuration is unavailable or invalid."""
    pass


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise LLMConfigError(f"Missing required environment variable: {name}")
    return value


def _extract_json(text: str) -> dict:
    """Parse JSON object from plain content or fenced code block."""
    content = (text or "").strip()
    if not content:
        raise LLMConfigError("LLM returned empty content.")

    # Direct parse first.
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try fenced JSON block.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        parsed = json.loads(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    # Try first object-shaped region.
    obj = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if obj:
        parsed = json.loads(obj.group(0))
        if isinstance(parsed, dict):
            return parsed

    raise LLMConfigError("Could not parse JSON object from LLM response.")


def _fetch_uhg_access_token() -> str:
    auth_url = os.environ.get("UHG_OAUTH_TOKEN_URL", "https://api.uhg.com/oauth2/token")
    scope = os.environ.get("UHG_SCOPE", "https://api.uhg.com/.default")
    client_id = _require_env("UHG_CLIENT_ID")
    client_secret = _require_env("UHG_CLIENT_SECRET")

    body = {
        "grant_type": "client_credentials",
        "scope": scope,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(auth_url, headers=headers, data=body)
            resp.raise_for_status()
            token = resp.json().get("access_token")
    except httpx.HTTPError as exc:
        raise LLMConfigError(f"Failed to fetch OAuth token: {exc}") from exc

    if not token:
        raise LLMConfigError("OAuth response did not include access_token.")
    return token


def call_llm_json(system_prompt: str, user_prompt: str) -> dict:
    """
    Call Azure OpenAI (via UHG auth) and return parsed JSON.

    Expected response shape:
      {
        "weights": {"policy": float, "clinical": float, "financial": float, "past": float},
        "rationale": str
      }
    """
    if openai is None:
        raise LLMConfigError("Python package 'openai' is not installed.")

    access_token = _fetch_uhg_access_token()
    endpoint = os.environ.get("UHG_AZURE_OPENAI_ENDPOINT", "https://api.uhg.com/api/cloud/api-management/ai-gateway/1.0")
    api_version = os.environ.get("UHG_AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    deployment = os.environ.get("UHG_AZURE_OPENAI_DEPLOYMENT", "gpt-4o_2024-11-20")
    model = os.environ.get("UHG_AZURE_OPENAI_MODEL", "gpt-4o")
    project_id = _require_env("UHG_PROJECT_ID")

    try:
        client = openai.AzureOpenAI(
            azure_endpoint=endpoint,
            api_version=api_version,
            azure_deployment=deployment,
            azure_ad_token=access_token,
            default_headers={"projectId": project_id},
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content if response.choices else ""
        return _extract_json(content or "")
    except Exception as exc:
        logger.debug("LLM call failed: %s", exc)
        raise LLMConfigError(f"LLM call failed: {exc}") from exc
