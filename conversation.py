"""
Sawa — Conversation state machine
Extracted from original main.py, now backed by PostgreSQL.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from db import (
    AsyncSession, Company, User, Employee, PayrollRun, ConversationState,
    get_company_by_phone, get_user, get_employees, get_employee_by_code,
    find_employee_by_phone, get_employee_count, check_duplicate_employee,
    get_conversation_state, set_conversation_state, reset_conversation_state,
    log_action, new_id,
)
from auth import (
    hash_pin, verify_pin, is_pin_verified, encrypt_phone, decrypt_phone,
    check_role, PIN_REQUIRED_ACTIONS,
)
from utils import parse_number, fmt, validate_email, normalize_phone, validate_phone, sanitize_input
from payroll_engine import NigerianPayrollEngine, EmployeeSalaryStructure

payroll_engine = NigerianPayrollEngine()

DEFAULT_ANNUAL_LEAVE_DAYS = 21
PAGE_SIZE = 5  # employees per page for WhatsApp readability

# Numbered menu shortcuts → mapped to command strings
MENU_SHORTCUTS = {
    '1': 'REGISTER',
    '2': 'ADD EMPLOYEE',
    '3': 'PAYROLL',
    '4': 'LIST',
    '5': 'POST JOB',
    '6': 'CANDIDATES',
    '7': 'PAYSLIP',
    '8': 'LEAVE',
}


def show_menu() -> str:
    return """Hey there! \U0001f44b Welcome to *Sawa HR* \U0001f1f3\U0001f1ec

Here's what I can help with:

\U0001f3e2 *Company Setup*
1. Register your company
2. Add an employee
3. Run payroll
4. View your team

\U0001f4bc *Hiring*
5. Post a job opening
6. View candidates

\U0001f464 *Self-Service*
7. View my payslip
8. Check leave balance

Just type what you need \u2014 I understand plain English too! \U0001f60a"""


async def _smart_extract(text: str, field_type: str, validator=None):
    """Try direct validation first, then AI extraction for conversational input.

    Returns (value, used_ai) or (None, False).
    """
    # 1. Try direct validator first (free, instant)
    if validator:
        direct = validator(text)
        if direct is not None and direct is not False:
            return (direct if not isinstance(direct, bool) else text, False)

    # 2. Only call AI if input has >1 word (looks conversational)
    if len(text.split()) <= 1:
        return (None, False)

    from ai import extract_field_value
    result = await extract_field_value(text, field_type)
    if not result or result.get("confidence") == "low":
        return (None, False)

    extracted = result["value"]

    # 3. Re-validate AI's extracted value
    if validator:
        validated = validator(str(extracted))
        if validated is None or validated is False:
            return (None, False)
        return (validated if not isinstance(validated, bool) else str(extracted), True)

    return (extracted, True)


async def handle_message(session: AsyncSession, phone: str, original_text: str) -> str:
    """Main message router. Returns response text."""
    text = sanitize_input(original_text)
    command = text.upper().strip()

    # ── Tier 1: Exact command match ──
    if command in ('MENU', 'START', 'HELP', 'HI', 'HELLO', 'HEY'):
        await reset_conversation_state(session, phone)
        return show_menu()

    if command == 'CANCEL':
        await reset_conversation_state(session, phone)
        return "No worries! Cancelled. \U0001f44d Type anything to start again."

    # ── Numbered menu shortcuts ──
    if command in MENU_SHORTCUTS:
        return await handle_message(session, phone, MENU_SHORTCUTS[command])

    if command == 'REGISTER':
        await set_conversation_state(session, phone, 'REG_NAME')
        return "\U0001f3e2 *Company Registration*\n\nWhat's your company name?"

    if command == 'ADD EMPLOYEE':
        company = await get_company_by_phone(session, phone)
        if not company:
            return "Hmm, you haven't registered yet. Just say *register* to get started! \U0001f60a"
        user = await get_user(session, phone)
        if not check_role(user, "ADD_EMPLOYEE"):
            return "Only owners and admins can add employees. Check with your admin! \U0001f512"
        await set_conversation_state(session, phone, 'EMP_NAME', {'company_id': company.id})
        return "\u2795 *Add Employee*\n\nWhat's the employee's full name?"

    if command == 'PAYROLL':
        return await handle_payroll(session, phone)

    if command == 'LIST':
        return await list_employees(session, phone)

    if command == 'PAYSLIP':
        return await handle_payslip(session, phone)

    if command == 'LEAVE':
        return await handle_leave(session, phone)

    if command == 'POST JOB':
        from hiring import start_post_job
        return await start_post_job(session, phone)

    if command == 'CANDIDATES':
        from hiring import show_candidates_menu
        return await show_candidates_menu(session, phone)

    if command.startswith('APPLY '):
        from hiring import start_apply
        job_code = command.split(' ', 1)[1].strip()
        return await start_apply(session, phone, job_code)

    # ── Tier 2: Active state flow ──
    conv = await get_conversation_state(session, phone)
    if conv and conv.state != 'MENU':
        # Handle numeric reply for PAYROLL_VIEW
        if conv.state == 'PAYROLL_VIEW' and command.isdigit():
            return await handle_payroll_detail(session, phone, int(command), conv)

        # PIN flow
        if conv.state == 'PIN_VERIFY':
            return await handle_pin_verify(session, phone, text, conv)

        if conv.state == 'PIN_SET':
            return await handle_pin_set(session, phone, text, conv)

        # Hiring states
        if conv.state.startswith('JOB_') or conv.state.startswith('APPLY_') or conv.state.startswith('CAND_'):
            from hiring import handle_hiring_state
            return await handle_hiring_state(session, phone, text, conv)

        return await handle_state(session, phone, text, conv)

    # ── Tier 3: AI intent detection ──
    from ai import detect_intent, hr_chat

    result = await detect_intent(text)
    intent = result.get("intent", "UNKNOWN")
    entities = result.get("entities", {})

    intent_map = {
        "REGISTER": "REGISTER",
        "ADD_EMPLOYEE": "ADD EMPLOYEE",
        "PAYROLL": "PAYROLL",
        "PAYSLIP": "PAYSLIP",
        "LEAVE": "LEAVE",
        "LIST": "LIST",
        "POST_JOB": "POST JOB",
        "VIEW_CANDIDATES": "CANDIDATES",
        "HELP": "HELP",
    }

    if intent == "HR_QUESTION":
        answer = await hr_chat(text)
        return f"\U0001f4a1 *HR Info*\n\n{answer}"

    if intent == "APPLY" and entities.get("job_code"):
        from hiring import start_apply
        return await start_apply(session, phone, entities["job_code"])

    if intent in intent_map:
        # If entities were extracted, pre-fill state
        mapped_cmd = intent_map[intent]
        if intent == "ADD_EMPLOYEE" and entities:
            company = await get_company_by_phone(session, phone)
            if company:
                user = await get_user(session, phone)
                if check_role(user, "ADD_EMPLOYEE"):
                    prefill = {'company_id': company.id}
                    if entities.get("name"):
                        prefill['name'] = entities['name']
                        if entities.get("position"):
                            prefill['position'] = entities['position']
                            await set_conversation_state(session, phone, 'EMP_BASIC', prefill)
                            await log_action(session, company.id, phone, "ADD_EMPLOYEE_START_AI", entities)
                            return f"\u2795 Adding *{entities['name']}* as *{entities['position']}*\n\nNow for the numbers! \U0001f4b0 What's their monthly basic salary? (e.g. 200k)"
                        await set_conversation_state(session, phone, 'EMP_POSITION', prefill)
                        await log_action(session, company.id, phone, "ADD_EMPLOYEE_START_AI", entities)
                        return f"\u2795 Adding *{entities['name']}*\n\nWhat position will they hold?"

        # Recurse with the mapped command
        return await handle_message(session, phone, mapped_cmd)

    return show_menu()


# ── State Machine ───────────────────────────────────────────────────────────


async def handle_state(session: AsyncSession, phone: str, text: str, conv: ConversationState) -> str:
    s = conv.state
    d = dict(conv.data or {})

    # ── REGISTRATION ──
    if s == 'REG_NAME':
        name = text.strip()
        # Try AI extraction if multi-word and looks conversational
        if len(text.split()) > 2:
            extracted, _ = await _smart_extract(text, 'name')
            if extracted:
                name = str(extracted)
        await set_conversation_state(session, phone, 'REG_EMAIL', {'name': name})
        return f"Nice one! *{name}* \u2014 great name. \U0001f44d\n\nWhat email should we use for the company?"

    if s == 'REG_EMAIL':
        # Try direct validation first
        email = text.strip()
        if validate_email(email):
            await set_conversation_state(session, phone, 'REG_PIN', {'email': email})
            return "Almost done! \U0001f512 Choose a 4-digit PIN to protect sensitive actions like payroll:"
        # Try AI extraction for conversational input
        extracted, _ = await _smart_extract(text, 'email', validator=lambda t: t if validate_email(t) else None)
        if extracted:
            await set_conversation_state(session, phone, 'REG_PIN', {'email': extracted})
            return "Almost done! \U0001f512 Choose a 4-digit PIN to protect sensitive actions like payroll:"
        return "Hmm, that doesn't look like a valid email. Try something like *hr@company.com* \U0001f4e7"

    if s == 'REG_PIN':
        if not (text.isdigit() and len(text) == 4):
            return "The PIN needs to be exactly 4 digits. Give it another go! \U0001f522"

        if not d.get('name') or not d.get('email'):
            await reset_conversation_state(session, phone)
            return "Oops, your session timed out. Just say *register* to start again! \U0001f504"

        pin_hashed = hash_pin(text)

        # Check if already registered
        existing = await get_company_by_phone(session, phone)
        if existing:
            await reset_conversation_state(session, phone)
            return "You're already registered! \u2705 Type *help* for what you can do."

        # Create company
        company = Company(name=d['name'], email=d['email'], phone=phone)
        session.add(company)
        await session.flush()

        # Create owner user
        user = User(company_id=company.id, phone=phone, role="owner", pin_hash=pin_hashed)
        session.add(user)

        await log_action(session, company.id, phone, "REGISTER", {"company": d['name']})
        await reset_conversation_state(session, phone)

        return f"Welcome aboard, *{d['name']}*! \U0001f389 Your company is all set up.\n\nPIN secured \U0001f512\n\nHere's what to do next:\n\u2022 Say *add employee* to build your team\n\u2022 Say *payroll* when you're ready to run salaries\n\u2022 Say *help* anytime"

    # ── EMPLOYEE ADD ──
    if s == 'EMP_NAME':
        company_id = d.get('company_id')
        name = text.strip()
        # Try AI extraction for conversational input
        if len(text.split()) > 2:
            extracted, _ = await _smart_extract(text, 'name')
            if extracted:
                name = str(extracted)
        if await check_duplicate_employee(session, company_id, name):
            return f"Looks like *{name}* is already on your team! Send the name again or try a different name."
        await set_conversation_state(session, phone, 'EMP_PHONE', {'name': name})
        return f"Got it \u2014 *{name}*! \u2705\n\nWhat's their phone number?"

    if s == 'EMP_PHONE':
        # Try direct validation
        if validate_phone(text):
            cleaned_phone = normalize_phone(text)
            await set_conversation_state(session, phone, 'EMP_POSITION', {'phone': cleaned_phone})
            name = d.get('name', 'they')
            return f"Phone saved \u2705\n\nWhat position will *{name}* hold?"
        # Try AI extraction
        extracted, _ = await _smart_extract(text, 'phone', validator=lambda t: normalize_phone(t) if validate_phone(t) else None)
        if extracted:
            await set_conversation_state(session, phone, 'EMP_POSITION', {'phone': extracted})
            name = d.get('name', 'they')
            return f"Phone saved \u2705\n\nWhat position will *{name}* hold?"
        return "I didn't catch that as a phone number. Try entering just the digits (7-15 digits). \U0001f4f1"

    if s == 'EMP_POSITION':
        position = text.strip()
        if len(text.split()) > 3:
            extracted, _ = await _smart_extract(text, 'position')
            if extracted:
                position = str(extracted)
        await set_conversation_state(session, phone, 'EMP_BASIC', {'position': position})
        name = d.get('name', 'this employee')
        return f"*{position}* \u2014 nice! \u2705\n\nNow for the numbers! \U0001f4b0 What's *{name}*'s monthly basic salary?\n_(e.g. 200000 or 200k)_"

    if s == 'EMP_BASIC':
        basic = parse_number(text)
        if not basic:
            # Try AI extraction for conversational input
            extracted, _ = await _smart_extract(text, 'salary', validator=lambda t: parse_number(t))
            if extracted:
                basic = extracted
            else:
                return "I didn't catch that as a number. Try *200000* or *200k* \U0001f4b0"
        await set_conversation_state(session, phone, 'EMP_HOUSING', {'basic': basic})
        return f"Basic salary: {fmt(basic)} \u2713\n\nAny housing allowance? _(Enter 0 if none)_"

    if s == 'EMP_HOUSING':
        housing = parse_number(text)
        if housing is None:
            extracted, _ = await _smart_extract(text, 'salary', validator=lambda t: parse_number(t))
            if extracted is not None:
                housing = extracted
            else:
                return "I didn't catch that as a number. Try *50000* or *50k* (or *0* for none)"
        await set_conversation_state(session, phone, 'EMP_TRANSPORT', {'housing': housing})
        return f"Housing: {fmt(housing)} \u2713\n\nTransport allowance? _(Enter 0 if none)_"

    if s == 'EMP_TRANSPORT':
        transport = parse_number(text)
        if transport is None:
            extracted, _ = await _smart_extract(text, 'salary', validator=lambda t: parse_number(t))
            if extracted is not None:
                transport = extracted
            else:
                return "I didn't catch that as a number. Try *30000* or *30k* (or *0* for none)"
        await set_conversation_state(session, phone, 'EMP_OTHER', {'transport': transport})
        return f"Transport: {fmt(transport)} \u2713\n\nAny other allowances? _(Enter 0 if none)_"

    if s == 'EMP_OTHER':
        other = parse_number(text)
        if other is None:
            extracted, _ = await _smart_extract(text, 'salary', validator=lambda t: parse_number(t))
            if extracted is not None:
                other = extracted
            else:
                return "I didn't catch that as a number. Try *20000* or *20k* (or *0* for none)"

        company_id = d.get('company_id')
        count = await get_employee_count(session, company_id)
        emp_code = f"EMP{count + 1:04d}"

        encrypted_phone = encrypt_phone(d.get('phone', '')) if d.get('phone') else None

        emp = Employee(
            company_id=company_id,
            employee_code=emp_code,
            name=d['name'],
            phone_encrypted=encrypted_phone,
            position=d.get('position', ''),
            salary_structure={
                'basic': d['basic'],
                'housing': d.get('housing', 0),
                'transport': d.get('transport', 0),
                'other': other,
            },
            leave_balance=DEFAULT_ANNUAL_LEAVE_DAYS,
        )
        session.add(emp)

        # Also create user record for employee self-service
        if d.get('phone'):
            emp_user = User(
                company_id=company_id,
                phone=d['phone'],
                role="employee",
            )
            session.add(emp_user)

        await log_action(session, company_id, phone, "ADD_EMPLOYEE", {"name": d['name'], "code": emp_code})
        await reset_conversation_state(session, phone)

        total = d['basic'] + d.get('housing', 0) + d.get('transport', 0) + other
        return f"""Done! *{d['name']}* has been added to your team! \U0001f389

*{d['name']}* ({emp_code})
Position: {d.get('position', 'N/A')}
Gross: {fmt(total)}

What's next?
\u2022 Say *add employee* to add another
\u2022 Say *payroll* to run salaries
\u2022 Say *list* to see your team"""

    return show_menu()


# ── PIN Flows ───────────────────────────────────────────────────────────────


async def handle_pin_verify(session: AsyncSession, phone: str, text: str, conv: ConversationState) -> str:
    """Handle PIN entry for protected operations."""
    d = dict(conv.data or {})
    user = await get_user(session, phone)

    if not user or not user.pin_hash:
        await reset_conversation_state(session, phone)
        return "No PIN set up yet. Say *register* to get started! \U0001f512"

    if verify_pin(text, user.pin_hash):
        # Mark verified
        conv.pin_verified_at = datetime.now(timezone.utc)
        await session.flush()

        # Resume the original action
        resume_action = d.get('resume_action', 'MENU')
        await log_action(session, user.company_id, phone, "PIN_VERIFIED", {"action": resume_action})
        return await handle_message(session, phone, resume_action)
    else:
        await log_action(session, getattr(user, 'company_id', None), phone, "PIN_FAILED", {})
        return "That PIN doesn't match. \U0001f512 Give it another try, or say *cancel* to go back."


async def handle_pin_set(session: AsyncSession, phone: str, text: str, conv: ConversationState) -> str:
    """Set PIN for first time (during registration is handled in REG_PIN)."""
    if not (text.isdigit() and len(text) == 4):
        return "The PIN needs to be exactly 4 digits. Try again! \U0001f522"

    user = await get_user(session, phone)
    if user:
        user.pin_hash = hash_pin(text)
        await session.flush()
        await reset_conversation_state(session, phone)
        return "PIN set! \u2705 You can now use protected commands."

    await reset_conversation_state(session, phone)
    return "Hmm, couldn't find your account. Say *register* to get started! \U0001f60a"


async def require_pin(session: AsyncSession, phone: str, action: str) -> str | None:
    """If PIN is required and not verified, prompt for it. Returns prompt string or None if OK."""
    if action not in PIN_REQUIRED_ACTIONS:
        return None

    user = await get_user(session, phone)
    if not user or not user.pin_hash:
        return None  # No PIN set, skip

    if await is_pin_verified(session, phone):
        return None  # Already verified

    await set_conversation_state(session, phone, 'PIN_VERIFY', {'resume_action': action})
    return "\U0001f512 Enter your 4-digit PIN:"


# ── Payroll ─────────────────────────────────────────────────────────────────


def _build_salary_structure(emp: Employee) -> EmployeeSalaryStructure:
    ss = emp.salary_structure or {}
    return EmployeeSalaryStructure(
        employee_id=emp.employee_code,
        employee_name=emp.name,
        basic_salary=Decimal(str(ss.get('basic', 0))),
        housing_allowance=Decimal(str(ss.get('housing', 0))),
        transport_allowance=Decimal(str(ss.get('transport', 0))),
        other_allowances=Decimal(str(ss.get('other', 0))),
    )


def _build_payslip_text(emp: Employee) -> str:
    salary = _build_salary_structure(emp)
    result = payroll_engine.calculate_payroll(salary, date.today().replace(day=1), date.today())
    month = date.today().strftime('%B %Y')
    return (
        f"\U0001f4c4 *PAYSLIP - {month}*\n"
        f"*{result.employee_name}* ({result.employee_id})\n\n"
        f"*EARNINGS*\n"
        f"Basic: {fmt(result.basic_salary)}\n"
        f"Housing: {fmt(result.housing_allowance)}\n"
        f"Transport: {fmt(result.transport_allowance)}\n"
        f"Other: {fmt(result.other_allowances)}\n"
        f"{'─' * 25}\n"
        f"*Gross: {fmt(result.gross_salary)}*\n\n"
        f"*DEDUCTIONS*\n"
        f"Pension (8%): {fmt(result.pension_employee)}\n"
        f"NHF (2.5%): {fmt(result.nhf)}\n"
        f"PAYE Tax: {fmt(result.paye)}\n"
        f"{'─' * 25}\n"
        f"*Total Deductions: {fmt(result.total_deductions)}*\n\n"
        f"{'━' * 25}\n"
        f"*NET PAY: {fmt(result.net_salary)}*\n"
        f"{'━' * 25}"
    )


async def handle_payroll(session: AsyncSession, phone: str) -> str:
    company = await get_company_by_phone(session, phone)
    if not company:
        return "Hmm, you haven't registered yet. Just say *register* to get started! \U0001f60a"

    user = await get_user(session, phone)
    if not check_role(user, "PAYROLL"):
        return "Only owners and admins can run payroll. Check with your admin! \U0001f512"

    # PIN check
    pin_prompt = await require_pin(session, phone, "PAYROLL")
    if pin_prompt:
        return pin_prompt

    emps = await get_employees(session, company.id)
    if not emps:
        return "No employees yet! Say *add employee* to get started. \U0001f465"

    results = []
    total_net = Decimal('0')

    for emp in emps:
        salary = _build_salary_structure(emp)
        result = payroll_engine.calculate_payroll(salary, date.today().replace(day=1), date.today())
        results.append(result)
        total_net += result.net_salary

    # Save payroll run
    period = date.today().strftime('%Y-%m')
    run = PayrollRun(
        company_id=company.id,
        period=period,
        results=[
            {'emp_code': r.employee_id, 'emp_name': r.employee_name,
             'gross': str(r.gross_salary), 'net': str(r.net_salary)}
            for r in results
        ],
        run_by=phone,
    )
    session.add(run)

    # Store in conversation for detail lookup
    payroll_data = [{'emp_code': r.employee_id, 'emp_name': r.employee_name} for r in results]
    await set_conversation_state(session, phone, 'PAYROLL_VIEW', {'payroll_results': payroll_data, 'company_id': company.id})

    await log_action(session, company.id, phone, "PAYROLL_RUN", {"period": period, "count": len(results)})

    month = date.today().strftime('%B %Y')
    response = f"\U0001f4b0 *PAYROLL - {month}*\n\n{len(emps)} Employees\n\n"

    for i, r in enumerate(results, 1):
        response += f"*{i}. {r.employee_name}*\n"
        response += f"Gross: {fmt(r.gross_salary)}\n"
        response += f"Deductions: {fmt(r.total_deductions)}\n"
        response += f"*Net: {fmt(r.net_salary)}*\n\n"

    response += f"{'━' * 30}\n*TOTAL NET: {fmt(total_net)}*\n{'━' * 30}\n\n"
    response += f"Reply 1-{len(results)} to view a payslip"

    return response


async def handle_payroll_detail(session: AsyncSession, phone: str, index: int, conv: ConversationState) -> str:
    d = dict(conv.data or {})
    payroll_results = d.get('payroll_results', [])

    if index < 1 or index > len(payroll_results):
        return f"Hmm, that's not a valid option. Reply 1-{len(payroll_results)}"

    emp_ref = payroll_results[index - 1]
    company_id = d.get('company_id')
    emp = await get_employee_by_code(session, company_id, emp_ref['emp_code'])

    if not emp:
        return "Couldn't find that employee. Try again?"

    return _build_payslip_text(emp)


async def handle_payslip(session: AsyncSession, phone: str) -> str:
    # Check if employer
    company = await get_company_by_phone(session, phone)
    if company:
        user = await get_user(session, phone)
        if user and user.role in ('owner', 'admin'):
            pin_prompt = await require_pin(session, phone, "PAYSLIP")
            if pin_prompt:
                return pin_prompt

            emps = await get_employees(session, company.id)
            if not emps:
                return "No employees yet! Say *add employee* to get started. \U0001f465"

            if len(emps) == 1:
                await log_action(session, company.id, phone, "VIEW_PAYSLIP", {"employee": emps[0].employee_code})
                return _build_payslip_text(emps[0])

            payroll_data = [{'emp_code': e.employee_code, 'emp_name': e.name} for e in emps]
            await set_conversation_state(session, phone, 'PAYROLL_VIEW', {'payroll_results': payroll_data, 'company_id': company.id})
            response = "\U0001f4c4 *Which employee's payslip?*\n\n"
            for i, emp in enumerate(emps, 1):
                response += f"*{i}.* {emp.name}\n"
            response += f"\nReply 1-{len(emps)}"
            return response

    # Employee self-service: lookup by phone
    user = await get_user(session, phone)
    if user and user.role == "employee":
        emps = await get_employees(session, user.company_id)
        # Find matching employee by decrypting phones
        for emp in emps:
            if emp.phone_encrypted:
                try:
                    decrypted = decrypt_phone(emp.phone_encrypted)
                    if normalize_phone(decrypted) == normalize_phone(phone):
                        await log_action(session, user.company_id, phone, "VIEW_OWN_PAYSLIP", {})
                        return _build_payslip_text(emp)
                except Exception:
                    continue

    return "No employee record found for your number. \U0001f914\n\nAsk your employer to add you via *add employee*."


async def handle_leave(session: AsyncSession, phone: str) -> str:
    # Employee self-service
    user = await get_user(session, phone)
    if user and user.role == "employee":
        emps = await get_employees(session, user.company_id)
        for emp in emps:
            if emp.phone_encrypted:
                try:
                    decrypted = decrypt_phone(emp.phone_encrypted)
                    if normalize_phone(decrypted) == normalize_phone(phone):
                        balance = emp.leave_balance or DEFAULT_ANNUAL_LEAVE_DAYS
                        return (
                            f"\U0001f3d6\ufe0f *Leave Balance*\n\n"
                            f"*{emp.name}*\n\n"
                            f"Annual Leave: *{balance} days*\n"
                            f"Year: {date.today().year}\n\n"
                            f"Contact your HR admin to request leave."
                        )
                except Exception:
                    continue

    # Employer view
    company = await get_company_by_phone(session, phone)
    if company:
        emps = await get_employees(session, company.id)
        if emps:
            response = f"\U0001f3d6\ufe0f *Leave Balances*\n\n"
            for emp in emps:
                balance = emp.leave_balance or DEFAULT_ANNUAL_LEAVE_DAYS
                response += f"*{emp.name}*: {balance} days\n"
            return response

    return "No employee record found for your number. \U0001f914\n\nAsk your employer to add you via *add employee*."


async def list_employees(session: AsyncSession, phone: str) -> str:
    company = await get_company_by_phone(session, phone)
    if not company:
        return "Hmm, you haven't registered yet. Just say *register* to get started! \U0001f60a"

    user = await get_user(session, phone)
    if not check_role(user, "LIST"):
        return "Only owners and admins can view the employee list. Check with your admin! \U0001f512"

    emps = await get_employees(session, company.id)
    if not emps:
        return "No employees yet! Say *add employee* to build your team. \U0001f465"

    # Paginate for WhatsApp readability
    response = f"*\U0001f465 Your Team ({len(emps)})*\n\n"
    for i, emp in enumerate(emps, 1):
        ss = emp.salary_structure or {}
        total = ss.get('basic', 0) + ss.get('housing', 0) + ss.get('transport', 0) + ss.get('other', 0)
        response += f"*{i}. {emp.name}*\n"
        response += f"   {emp.position or 'N/A'}\n"
        response += f"   {fmt(total)}\n\n"
        if i % PAGE_SIZE == 0 and i < len(emps):
            response += "---\n"

    return response
