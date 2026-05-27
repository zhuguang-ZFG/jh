"""Auto-generate concrete fix code for failure patterns.

Uses LLM to produce actionable code fixes from error descriptions,
stored alongside failure patterns for immediate context injection.
"""
import json
import logging
import re
from typing import Optional, Tuple

from .llm_bridge import chat

logger = logging.getLogger("evo.fix_generator")


async def generate_fix(
    error_type: str,
    description: str,
    file_context: str = "",
    domain: str = "",
) -> Tuple[str, str]:
    """Generate a concrete fix for a failure pattern.

    Returns (fix_code, fix_type) where:
    - fix_code: the actual code/text fix (or empty if generation failed)
    - fix_type: "code" | "config" | "command" | "pattern" | ""
    """
    system = (
        "You are a code fix generator. Given an error description, "
        "produce a CONCRETE, COPY-PASTEABLE fix. "
        "Return JSON with exactly these keys:\n"
        '  "fix_code": the fix (code snippet, config change, or command),\n'
        '  "fix_type": one of "code", "config", "command", "pattern"\n'
        "Rules:\n"
        "- fix_code must be directly usable (no explanations inside code)\n"
        "- If the fix is a code change, show the corrected code (not a diff)\n"
        "- If the fix is a command, show the exact command\n"
        "- Keep fix_code under 500 chars\n"
        "- No markdown fences in fix_code\n"
        "- Return ONLY the JSON object, nothing else"
    )

    prompt_parts = [f"Error type: {error_type}", f"Description: {description[:300]}"]
    if file_context:
        prompt_parts.append(f"File/context: {file_context[:200]}")
    if domain:
        prompt_parts.append(f"Domain/language: {domain}")
    prompt_parts.append("Generate the fix:")
    prompt = "\n".join(prompt_parts)

    try:
        response = await chat(prompt, system=system, temperature=0.2, max_backends=3)
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        return "", ""

    if not response or response.startswith("Error:"):
        logger.warning(f"LLM returned error: {response[:100]}")
        return "", ""

    return _parse_fix_response(response)


def _parse_fix_response(response: str) -> Tuple[str, str]:
    """Parse LLM response to extract fix_code and fix_type."""
    # Try direct JSON parse
    try:
        data = json.loads(response.strip())
        fix_code = str(data.get("fix_code", "")).strip()
        fix_type = str(data.get("fix_type", "")).strip()
        if fix_code and fix_type in ("code", "config", "command", "pattern"):
            return fix_code[:500], fix_type
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code block
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1).strip())
            fix_code = str(data.get("fix_code", "")).strip()
            fix_type = str(data.get("fix_type", "")).strip()
            if fix_code and fix_type in ("code", "config", "command", "pattern"):
                return fix_code[:500], fix_type
        except json.JSONDecodeError:
            pass

    # Fallback: treat entire response as fix_code with type "pattern"
    cleaned = response.strip()
    # Strip markdown fences if present
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    if cleaned and len(cleaned) > 10:
        return cleaned[:500], "pattern"

    return "", ""
