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


def show_menu() -> str:
    return """\U0001f1f3\U0001f1ec *Sawa HR*

*FOR EMPLOYERS:*
\U0001f4dd REGISTER - Setup company
\U0001f465 ADD EMPLOYEE - Add team
\U0001f4b0 PAYROLL - Calculate salaries
\U0001f4cb LIST - View employees

*HIRING:*
\U0001f4e2 POST JOB - Create job listing
\U0001f465 CANDIDATES - View applicants

*FOR EMPLOYEES:*
\U0001f4c4 PAYSLIP - View yours
\U0001f3d6\ufe0f LEAVE - Check balance

*FOR CANDIDATES:*
\U0001f4e9 APPLY <code> - Apply to a job

*OTHER:*
\u2753 HELP - All commands"""


async def handle_message(session: AsyncSession, phone: str, original_text: str) -> str:
    """Main message router. Returns response text."""
    text = sanitize_input(original_text)
    command = text.upper().strip()

    # ── Tier 1: Exact command match ──
    if command in ('MENU', 'START', 'HELP'):
        await reset_conversation_state(session, phone)
        return show_menu()

    if command == 'CANCEL':
        await reset_conversation_state(session, phone)
        return "Cancelled. Type HELP for menu."

    if command == 'REGISTER':
        await set_conversation_state(session, phone, 'REG_NAME')
        return "\U0001f3e2 *Company Registration*\n\nCompany name?"

    if command == 'ADD EMPLOYEE':
        company = await get_company_by_phone(session, phone)
        if not company:
            return "\u26a0\ufe0f Please REGISTER your company first"
        user = await get_user(session, phone)
        if not check_role(user, "ADD_EMPLOYEE"):
            return "\u26a0\ufe0f Only owners and admins can add employees."
        await set_conversation_state(session, phone, 'EMP_NAME', {'company_id': company.id})
        return "\u2795 *Add Employee*\n\nEmployee's full name?"

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
                            return f"\u2795 Adding *{entities['name']}* as *{entities['position']}*\n\n\U0001f4b0 BASIC SALARY (monthly)?\n\nExample: 200000"
                        await set_conversation_state(session, phone, 'EMP_POSITION', prefill)
                        await log_action(session, company.id, phone, "ADD_EMPLOYEE_START_AI", entities)
                        return f"\u2795 Adding *{entities['name']}*\n\nPosition/Job title?"

        # Recurse with the mapped command
        return await handle_message(session, phone, mapped_cmd)

    return show_menu()


# ── State Machine ───────────────────────────────────────────────────────────


async def handle_state(session: AsyncSession, phone: str, text: str, conv: ConversationState) -> str:
    s = conv.state
    d = dict(conv.data or {})

    # ── REGISTRATION ──
    if s == 'REG_NAME':
        await set_conversation_state(session, phone, 'REG_EMAIL', {'name': text})
        return f"Great! *{text}*\n\nCompany email?"

    if s == 'REG_EMAIL':
        if not validate_email(text):
            return "\u274c Invalid email format. Please enter a valid email (e.g. hr@company.com)"
        await set_conversation_state(session, phone, 'REG_PIN', {'email': text})
        return "\U0001f512 Set a 4-digit PIN for secure operations:"

    if s == 'REG_PIN':
        if not (text.isdigit() and len(text) == 4):
            return "\u274c PIN must be exactly 4 digits."

        if not d.get('name') or not d.get('email'):
            await reset_conversation_state(session, phone)
            return "\u26a0\ufe0f Session expired. Please type REGISTER to start again."

        pin_hashed = hash_pin(text)

        # Check if already registered
        existing = await get_company_by_phone(session, phone)
        if existing:
            await reset_conversation_state(session, phone)
            return "\u2705 You're already registered! Type HELP for commands."

        # Create company
        company = Company(name=d['name'], email=d['email'], phone=phone)
        session.add(company)
        await session.flush()

        # Create owner user
        user = User(company_id=company.id, phone=phone, role="owner", pin_hash=pin_hashed)
        session.add(user)

        await log_action(session, company.id, phone, "REGISTER", {"company": d['name']})
        await reset_conversation_state(session, phone)

        return f"\u2705 *Registered!*\n\nWelcome, {d['name']}!\nPIN set successfully.\n\nType:\n\u2022 ADD EMPLOYEE\n\u2022 PAYROLL\n\u2022 HELP"

    # ── EMPLOYEE ADD ──
    if s == 'EMP_NAME':
        company_id = d.get('company_id')
        if await check_duplicate_employee(session, company_id, text):
            return f"\u26a0\ufe0f An employee named *{text}* already exists. Send the name again or enter a different name."
        await set_conversation_state(session, phone, 'EMP_PHONE', {'name': text})
        return "Phone number?"

    if s == 'EMP_PHONE':
        if not validate_phone(text):
            return "\u274c Invalid phone number. Please enter a valid number (7-15 digits)."
        cleaned_phone = normalize_phone(text)
        await set_conversation_state(session, phone, 'EMP_POSITION', {'phone': cleaned_phone})
        return "Position/Job title?"

    if s == 'EMP_POSITION':
        await set_conversation_state(session, phone, 'EMP_BASIC', {'position': text})
        return "\U0001f4b0 BASIC SALARY (monthly)?\n\nExample: 200000"

    if s == 'EMP_BASIC':
        basic = parse_number(text)
        if not basic:
            return "\u274c Invalid. Example: 200000"
        await set_conversation_state(session, phone, 'EMP_HOUSING', {'basic': basic})
        return f"Basic: {fmt(basic)}\n\nHOUSING allowance?\n(Enter 0 if none)"

    if s == 'EMP_HOUSING':
        housing = parse_number(text)
        if housing is None:
            return "\u274c Invalid"
        await set_conversation_state(session, phone, 'EMP_TRANSPORT', {'housing': housing})
        return f"Housing: {fmt(housing)}\n\nTRANSPORT allowance?\n(Enter 0 if none)"

    if s == 'EMP_TRANSPORT':
        transport = parse_number(text)
        if transport is None:
            return "\u274c Invalid"
        await set_conversation_state(session, phone, 'EMP_OTHER', {'transport': transport})
        return f"Transport: {fmt(transport)}\n\nOTHER allowances?\n(Enter 0 if none)"

    if s == 'EMP_OTHER':
        other = parse_number(text)
        if other is None:
            return "\u274c Invalid"

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
        return f"""\u2705 *Employee Added!*

{d['name']} ({emp_code})
Position: {d.get('position', 'N/A')}
Gross: {fmt(total)}

*Next:*
\u2022 ADD EMPLOYEE
\u2022 PAYROLL
\u2022 LIST"""

    return show_menu()


# ── PIN Flows ───────────────────────────────────────────────────────────────


async def handle_pin_verify(session: AsyncSession, phone: str, text: str, conv: ConversationState) -> str:
    """Handle PIN entry for protected operations."""
    d = dict(conv.data or {})
    user = await get_user(session, phone)

    if not user or not user.pin_hash:
        await reset_conversation_state(session, phone)
        return "\u26a0\ufe0f No PIN set. Please REGISTER first."

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
        return "\u274c Wrong PIN. Try again or type CANCEL."


async def handle_pin_set(session: AsyncSession, phone: str, text: str, conv: ConversationState) -> str:
    """Set PIN for first time (during registration is handled in REG_PIN)."""
    if not (text.isdigit() and len(text) == 4):
        return "\u274c PIN must be exactly 4 digits."

    user = await get_user(session, phone)
    if user:
        user.pin_hash = hash_pin(text)
        await session.flush()
        await reset_conversation_state(session, phone)
        return "\u2705 PIN set! You can now use protected commands."

    await reset_conversation_state(session, phone)
    return "\u26a0\ufe0f User not found. Please REGISTER first."


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
        return "\u26a0\ufe0f Please REGISTER your company first"

    user = await get_user(session, phone)
    if not check_role(user, "PAYROLL"):
        return "\u26a0\ufe0f Only owners and admins can run payroll."

    # PIN check
    pin_prompt = await require_pin(session, phone, "PAYROLL")
    if pin_prompt:
        return pin_prompt

    emps = await get_employees(session, company.id)
    if not emps:
        return "\u26a0\ufe0f No employees. Type: ADD EMPLOYEE"

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
    response += f"Reply 1-{len(results)} to view payslip"

    return response


async def handle_payroll_detail(session: AsyncSession, phone: str, index: int, conv: ConversationState) -> str:
    d = dict(conv.data or {})
    payroll_results = d.get('payroll_results', [])

    if index < 1 or index > len(payroll_results):
        return f"\u274c Invalid. Reply 1-{len(payroll_results)}"

    emp_ref = payroll_results[index - 1]
    company_id = d.get('company_id')
    emp = await get_employee_by_code(session, company_id, emp_ref['emp_code'])

    if not emp:
        return "\u274c Employee not found"

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
                return "\u26a0\ufe0f No employees."

            if len(emps) == 1:
                await log_action(session, company.id, phone, "VIEW_PAYSLIP", {"employee": emps[0].employee_code})
                return _build_payslip_text(emps[0])

            payroll_data = [{'emp_code': e.employee_code, 'emp_name': e.name} for e in emps]
            await set_conversation_state(session, phone, 'PAYROLL_VIEW', {'payroll_results': payroll_data, 'company_id': company.id})
            response = "\U0001f4c4 *Select Employee*\n\n"
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

    return "\u26a0\ufe0f No employee record found for your phone number.\n\nAsk your employer to add you via ADD EMPLOYEE."


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

    return "\u26a0\ufe0f No employee record found.\n\nAsk your employer to add you via ADD EMPLOYEE."


async def list_employees(session: AsyncSession, phone: str) -> str:
    company = await get_company_by_phone(session, phone)
    if not company:
        return "\u26a0\ufe0f Please REGISTER your company first"

    user = await get_user(session, phone)
    if not check_role(user, "LIST"):
        return "\u26a0\ufe0f Only owners and admins can view the employee list."

    emps = await get_employees(session, company.id)
    if not emps:
        return "\U0001f4ed No employees\n\nType: ADD EMPLOYEE"

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
