"""
Sawa — Claude AI intent detection and HR knowledge chat
"""
import json
import asyncio
from config import settings

_client = None

INTENT_SYSTEM_PROMPT = """You are the intent classifier for Sawa, a Nigerian HR WhatsApp platform.
Given a user message, respond with ONLY valid JSON (no markdown):
{"intent": "INTENT_NAME", "entities": {}, "clarification": ""}

Valid intents: REGISTER, ADD_EMPLOYEE, PAYROLL, PAYSLIP, LEAVE, LIST, POST_JOB, VIEW_CANDIDATES, APPLY, HELP, HR_QUESTION, UNKNOWN

Entity extraction examples:
- "add John as accountant" -> {"intent": "ADD_EMPLOYEE", "entities": {"name": "John", "position": "accountant"}}
- "how much do I get paid?" -> {"intent": "PAYSLIP", "entities": {}}
- "show me salaries" -> {"intent": "PAYROLL", "entities": {}}
- "post a job for developer" -> {"intent": "POST_JOB", "entities": {"title": "developer"}}
- "what is minimum wage in Nigeria?" -> {"intent": "HR_QUESTION", "entities": {}}
- "candidates for SAW-A3F2" -> {"intent": "VIEW_CANDIDATES", "entities": {"job_code": "SAW-A3F2"}}

If the message is a general Nigerian HR/labor law question, use HR_QUESTION.
If you genuinely cannot determine intent, use UNKNOWN."""

HR_SYSTEM_PROMPT = """You are Sawa, a Nigerian HR assistant on WhatsApp.
Answer the user's HR question concisely (max 280 chars) using Nigerian labor law context.
Be helpful, accurate, and professional. If unsure, say so.
Focus on: Labour Act, PAYE, pension (PenCom), NHF, NSITF, leave entitlements, minimum wage."""


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


async def detect_intent(message: str) -> dict:
    """Use Claude to detect user intent from natural language.
    Returns {"intent": str, "entities": dict, "clarification": str}
    Falls back to UNKNOWN on any error.
    """
    if not settings.anthropic_api_key:
        return {"intent": "UNKNOWN", "entities": {}, "clarification": ""}

    try:
        client = _get_client()
        response = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=200,
                    system=INTENT_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": message}],
                )
            ),
            timeout=5.0,
        )
        text = response.content[0].text.strip()
        return json.loads(text)
    except Exception:
        return {"intent": "UNKNOWN", "entities": {}, "clarification": ""}


async def hr_chat(question: str) -> str:
    """Answer a general HR question using Claude."""
    if not settings.anthropic_api_key:
        return "AI features require configuration. Please use menu commands."

    try:
        client = _get_client()
        response = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=300,
                    system=HR_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": question}],
                )
            ),
            timeout=5.0,
        )
        text = response.content[0].text.strip()
        return text[:300]
    except Exception:
        return "Sorry, I couldn't process that. Try a specific command like HELP."
