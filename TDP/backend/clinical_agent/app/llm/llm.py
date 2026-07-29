import os
import time
import inspect

import httpx
import openai
from dotenv import load_dotenv

load_dotenv()

_TOKEN_CACHE = {"access_token": None, "expires_at": 0.0}


def _env(name, default=None):
    value = os.getenv(name)
    return value if value else default


async def _get_access_token():
    cached_token = _TOKEN_CACHE["access_token"]
    expires_at = _TOKEN_CACHE["expires_at"]
    if cached_token and time.time() < expires_at:
        return cached_token

    auth_url = _env("UHG_AUTH_URL", "https://api.uhg.com/oauth2/token")
    scope = _env("UHG_SCOPE", "https://api.uhg.com/.default")
    client_id = _env("UHG_CLIENT_ID")
    client_secret = _env("UHG_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError(
            "UHG_CLIENT_ID and UHG_CLIENT_SECRET must be set in .env or environment variables"
        )

    body = {
        "grant_type": "client_credentials",
        "scope": scope,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient() as client:
        response = await client.post(auth_url, headers=headers, data=body, timeout=60)
        response.raise_for_status()
        payload = response.json()

    access_token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    _TOKEN_CACHE["access_token"] = access_token
    _TOKEN_CACHE["expires_at"] = time.time() + max(expires_in - 60, 0)
    return access_token


async def call_llm(prompt, *, temperature=0, response_format=None):
    access_token = await _get_access_token()
    shared_quota_endpoint = _env(
        "UHG_SHARED_QUOTA_ENDPOINT",
        "https://api.uhg.com/api/cloud/api-management/ai-gateway/1.0",
    )
    api_version = _env("UHG_AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    deployment_name = _env("UHG_AZURE_OPENAI_DEPLOYMENT", "gpt-4o_2024-11-20")
    project_id = _env("UHG_PROJECT_ID", "")

    client = openai.AsyncAzureOpenAI(
        azure_endpoint=shared_quota_endpoint,
        api_version=api_version,
        azure_ad_token=access_token,
        default_headers={"projectId": project_id},
    )

    try:
        kwargs = {
            "model": deployment_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        response = await client.chat.completions.create(**kwargs)

        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("LLM returned an empty response")
        return content
    finally:
        # Ensure the underlying httpx async client is closed before loop shutdown.
        close_method = getattr(client, "aclose", None) or getattr(client, "close", None)
        if callable(close_method):
            maybe_awaitable = close_method()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable