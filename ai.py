"""
Sawa — Claude AI intent detection, HR knowledge chat, and NL field extraction
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

Nigerian English & Pidgin examples:
- "I wan register" -> {"intent": "REGISTER", "entities": {}}
- "I wan register my company" -> {"intent": "REGISTER", "entities": {}}
- "wetin be my salary" -> {"intent": "PAYSLIP", "entities": {}}
- "abeg show me my payslip" -> {"intent": "PAYSLIP", "entities": {}}
- "I wan add worker" -> {"intent": "ADD_EMPLOYEE", "entities": {}}
- "make we run payroll" -> {"intent": "PAYROLL", "entities": {}}
- "show me all my people" -> {"intent": "LIST", "entities": {}}
- "I need to hire someone" -> {"intent": "POST_JOB", "entities": {}}
- "how many leave days I get?" -> {"intent": "LEAVE", "entities": {}}

Natural language examples:
- "I'd like to set up my company" -> {"intent": "REGISTER", "entities": {}}
- "can you help me add a new team member?" -> {"intent": "ADD_EMPLOYEE", "entities": {}}
- "run this month's salaries" -> {"intent": "PAYROLL", "entities": {}}
- "what are my employees?" -> {"intent": "LIST", "entities": {}}
- "I want to post an opening" -> {"intent": "POST_JOB", "entities": {}}
- "who applied for the role?" -> {"intent": "VIEW_CANDIDATES", "entities": {}}

If the message is a general Nigerian HR/labor law question, use HR_QUESTION.
If you genuinely cannot determine intent, use UNKNOWN."""

HR_SYSTEM_PROMPT = """You are Sawa, a friendly HR assistant on WhatsApp who really knows their stuff.
You chat like a warm, knowledgeable colleague — approachable but professional.
Use light Nigerian English where it feels natural (e.g. "No wahala", "You're covered").

Answer the user's HR question concisely (max 280 chars) using Nigerian labor law context.
Be helpful, accurate, and warm. If unsure, say so honestly.
Focus on: Labour Act, PAYE, pension (PenCom), NHF, NSITF, leave entitlements, minimum wage."""

EXTRACT_SYSTEM_PROMPT = """You extract specific values from conversational messages.
Respond with ONLY valid JSON (no markdown): {"value": <extracted_value>, "confidence": "high"|"low"}

If you cannot find the requested value in the message, respond: {"value": null, "confidence": "low"}

Rules:
- For names: extract the full name, ignore filler words like "his name is", "she's called"
- For emails: extract the email address
- For phones: extract the phone number digits
- For salary/numbers: extract the numeric value (convert shorthand like 200k to 200000, 3.5m to 3500000)
- For positions/titles: extract the job title
- For yes/no: extract true for affirmative, false for negative
- Be strict: only extract if you're confident the value is there"""


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


async def extract_field_value(message: str, field_type: str) -> dict | None:
    """Extract a specific field value from conversational input using AI.

    Args:
        message: The user's message text
        field_type: One of 'name', 'email', 'phone', 'salary', 'position', 'yes_no'

    Returns:
        {"value": ..., "confidence": "high"|"low"} or None on failure/no API key
    """
    if not settings.anthropic_api_key:
        return None

    prompt = f"Extract the {field_type} from this message: \"{message}\""

    try:
        client = _get_client()
        response = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=100,
                    system=EXTRACT_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
            ),
            timeout=3.0,
        )
        text = response.content[0].text.strip()
        result = json.loads(text)
        if result.get("value") is not None:
            return result
        return None
    except Exception:
        return None
