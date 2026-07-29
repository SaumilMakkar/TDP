"""
llm.py - Async wrapper for LLM calls used by clinical and other agents.

This module provides a unified async interface for LLM calls throughout the PBM system,
wrapping the synchronous call_llm_json from llm_client.py and providing fallback
behavior when the LLM is unavailable.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from .llm_client import call_llm_json, LLMConfigError

logger = logging.getLogger(__name__)


async def call_llm(
    user_prompt: str,
    system_prompt: str = None,
    response_format: Dict[str, Any] = None,
    temperature: float = 0.1
) -> Optional[str]:
    """Call LLM asynchronously with fallback to None on failure.
    
    This is the primary interface for clinical and other agents to call the LLM.
    It wraps the synchronous call_llm_json in asyncio to make it async-safe.
    
    Args:
        user_prompt: The user message/question for the LLM
        system_prompt: Optional system prompt (default: generic clinical reasoning)
        response_format: Optional response format specification (e.g., {"type": "json_object"})
        
    Returns:
        The LLM's response as a string (typically JSON), or None if the call fails
        
    Note:
        - On LLMConfigError or any other exception, returns None (soft failure)
        - The calling code should handle None and use rule-based fallback
        - response_format is accepted for API compatibility but not enforced here
          (enforcement happens on the LLM client side via Azure OpenAI API)
    """
    if system_prompt is None:
        system_prompt = (
            "You are a clinical decision support assistant for pharmacy benefit "
            "management. Provide concise, evidence-based assessments. "
            "Always respond with valid JSON unless explicitly told otherwise."
        )

    try:
        # Run the synchronous call_llm_json in an executor to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, call_llm_json, system_prompt, user_prompt
        )
        
        # call_llm_json returns a dict; convert to JSON string for compatibility
        if isinstance(result, dict):
            return json.dumps(result)
        return str(result)
        
    except LLMConfigError as exc:
        logger.debug(f"LLM configuration error: {exc}. Using rule-based fallback.")
        return None
    except Exception as exc:
        logger.debug(f"LLM call failed: {exc}. Using rule-based fallback.")
        return None


async def call_llm_json_async(
    user_prompt: str,
    system_prompt: str = None,
) -> Optional[Dict[str, Any]]:
    """Call LLM asynchronously and return parsed JSON dict.
    
    Convenience wrapper that directly returns the parsed dict instead of a string.
    
    Args:
        user_prompt: The user message/question for the LLM
        system_prompt: Optional system prompt
        
    Returns:
        The LLM's JSON response as a dict, or empty dict if the call fails
    """
    if system_prompt is None:
        system_prompt = (
            "You are a clinical decision support assistant for pharmacy benefit "
            "management. Provide concise, evidence-based assessments. "
            "Always respond with valid JSON."
        )

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, call_llm_json, system_prompt, user_prompt
        )
        return result if isinstance(result, dict) else {}
        
    except (LLMConfigError, Exception) as exc:
        logger.warning(f"LLM call failed: {exc}. Returning empty dict.")
        return {}
