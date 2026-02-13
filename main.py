"""
Nigerian HR Bot - Production Ready
100% WhatsApp-based HR system
"""
from fastapi import FastAPI, Form
from fastapi.responses import PlainTextResponse
from typing import Optional, Dict, List
from datetime import datetime, date
from decimal import Decimal
import re
import os

from payroll_engine import NigerianPayrollEngine, EmployeeSalaryStructure

app = FastAPI(title="Nigerian HR Bot")
payroll_engine = NigerianPayrollEngine()

# Default leave allocation (Nigerian standard)
DEFAULT_ANNUAL_LEAVE_DAYS = 21

# Simple in-memory storage
class DB:
    companies = {}
    employees = {}
    conversations = {}

def get_state(phone: str) -> Dict:
    return DB.conversations.get(phone, {'state': 'MENU', 'data': {}})

def set_state(phone: str, state: str, data: Dict = None):
    current = get_state(phone)
    current['state'] = state
    if data:
        current['data'].update(data)
    DB.conversations[phone] = current

def reset_state(phone: str):
    if phone in DB.conversations:
        del DB.conversations[phone]

def parse_number(text: str) -> Optional[float]:
    try:
        return float(text.replace(',', '').replace('₦', '').strip())
    except Exception:
        return None

def fmt(amount) -> str:
    return f"₦{Decimal(str(amount)):,.2f}"

def validate_email(email: str) -> bool:
    """Basic email format validation."""
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))

def normalize_phone(phone_str: str) -> str:
    """Strip non-digits and return cleaned phone number."""
    return re.sub(r'\D', '', phone_str)

def validate_phone(phone_str: str) -> bool:
    """Validate phone number has reasonable length (7-15 digits)."""
    digits = normalize_phone(phone_str)
    return 7 <= len(digits) <= 15

def find_employee_by_phone(phone: str) -> Optional[Dict]:
    """Reverse lookup: find an employee by their phone number."""
    normalized = normalize_phone(phone)
    for emp in DB.employees.values():
        if normalize_phone(emp.get('phone', '')) == normalized:
            return emp
    return None

def check_duplicate_employee(name: str, company_phone: str) -> bool:
    """Check if an employee with the same name already exists for this company."""
    name_lower = name.strip().lower()
    for emp in DB.employees.values():
        if (emp.get('company_phone') == company_phone and
                emp['name'].strip().lower() == name_lower):
            return True
    return False

def build_payslip_for_employee(emp: Dict) -> str:
    """Calculate payroll and return a WhatsApp-formatted payslip for one employee."""
    salary = EmployeeSalaryStructure(
        employee_id=emp['id'],
        employee_name=emp['name'],
        basic_salary=Decimal(str(emp['basic'])),
        housing_allowance=Decimal(str(emp.get('housing', 0))),
        transport_allowance=Decimal(str(emp.get('transport', 0))),
        other_allowances=Decimal(str(emp.get('other', 0)))
    )

    result = payroll_engine.calculate_payroll(
        salary,
        date.today().replace(day=1),
        date.today()
    )

    month = date.today().strftime('%B %Y')
    return (
        f"📄 *PAYSLIP - {month}*\n"
        f"*{result.employee_name}* ({result.employee_id})\n\n"
        f"*EARNINGS*\n"
        f"Basic: {fmt(result.basic_salary)}\n"
        f"Housing: {fmt(result.housing_allowance)}\n"
        f"Transport: {fmt(result.transport_allowance)}\n"
        f"Other: {fmt(result.other_allowances)}\n"
        f"{'─'*25}\n"
        f"*Gross: {fmt(result.gross_salary)}*\n\n"
        f"*DEDUCTIONS*\n"
        f"Pension (8%): {fmt(result.pension_employee)}\n"
        f"NHF (2.5%): {fmt(result.nhf)}\n"
        f"PAYE Tax: {fmt(result.paye)}\n"
        f"{'─'*25}\n"
        f"*Total Deductions: {fmt(result.total_deductions)}*\n\n"
        f"{'━'*25}\n"
        f"*NET PAY: {fmt(result.net_salary)}*\n"
        f"{'━'*25}"
    )

# Main menu
def show_menu() -> str:
    return """🇳🇬 *Nigerian HR Bot*

*FOR EMPLOYERS:*
📝 REGISTER - Setup company
👥 ADD EMPLOYEE - Add team
💰 PAYROLL - Calculate salaries
📋 LIST - View employees

*FOR EMPLOYEES:*
📄 PAYSLIP - View yours
🏖️ LEAVE - Check balance

*OTHER:*
❓ HELP - All commands"""

# Route messages
@app.post("/whatsapp/webhook")
async def whatsapp_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: Optional[str] = Form(None),
):
    phone = From.replace("whatsapp:", "")
    original_text = Body.strip()
    command = original_text.upper()

    # Main commands
    if command in ['MENU', 'START', 'HELP']:
        reset_state(phone)
        return {"message": show_menu()}

    if command == 'REGISTER':
        set_state(phone, 'REG_NAME')
        return {"message": "🏢 *Company Registration*\n\nCompany name?"}

    if command == 'ADD EMPLOYEE':
        if not DB.companies.get(phone):
            return {"message": "⚠️ Please REGISTER your company first"}
        set_state(phone, 'EMP_NAME')
        return {"message": "➕ *Add Employee*\n\nEmployee's full name?"}

    if command == 'PAYROLL':
        return handle_payroll(phone)

    if command == 'LIST':
        return {"message": list_employees(phone)}

    if command == 'PAYSLIP':
        return {"message": handle_payslip(phone)}

    if command == 'LEAVE':
        return {"message": handle_leave(phone)}

    # Check if it's a numeric reply (for PAYROLL_VIEW state)
    if command.isdigit():
        state = get_state(phone)
        if state['state'] == 'PAYROLL_VIEW':
            return {"message": handle_payroll_detail(phone, int(command), state)}

    # State machine - pass original text to preserve casing
    state = get_state(phone)
    response = handle_state(phone, original_text, state)
    return {"message": response}

def handle_state(phone: str, text: str, state: Dict) -> str:
    s = state['state']
    d = state['data']

    # REGISTRATION FLOW
    if s == 'REG_NAME':
        set_state(phone, 'REG_EMAIL', {'name': text})
        return f"Great! *{text}*\n\nCompany email?"

    if s == 'REG_EMAIL':
        if not validate_email(text):
            return "❌ Invalid email format. Please enter a valid email (e.g. hr@company.com)"
        d['email'] = text
        DB.companies[phone] = {**d, 'phone': phone, 'created': datetime.now().isoformat()}
        reset_state(phone)
        return f"✅ *Registered!*\n\nWelcome, {d['name']}!\n\nType:\n• ADD EMPLOYEE\n• PAYROLL\n• HELP"

    # EMPLOYEE ADD FLOW
    if s == 'EMP_NAME':
        if check_duplicate_employee(text, phone):
            return f"⚠️ An employee named *{text}* already exists. Send the name again to confirm, or enter a different name."
        set_state(phone, 'EMP_PHONE', {'name': text})
        return "Phone number?"

    if s == 'EMP_PHONE':
        if not validate_phone(text):
            return "❌ Invalid phone number. Please enter a valid number (7-15 digits)."
        cleaned_phone = normalize_phone(text)
        set_state(phone, 'EMP_POSITION', {**d, 'phone': cleaned_phone})
        return "Position/Job title?"

    if s == 'EMP_POSITION':
        set_state(phone, 'EMP_BASIC', {**d, 'position': text})
        return "💰 BASIC SALARY (monthly)?\n\nExample: 200000"

    if s == 'EMP_BASIC':
        basic = parse_number(text)
        if not basic:
            return "❌ Invalid. Example: 200000"
        set_state(phone, 'EMP_HOUSING', {**d, 'basic': basic})
        return f"Basic: {fmt(basic)}\n\nHOUSING allowance?\n(Enter 0 if none)"

    if s == 'EMP_HOUSING':
        housing = parse_number(text)
        if housing is None:
            return "❌ Invalid"
        set_state(phone, 'EMP_TRANSPORT', {**d, 'housing': housing})
        return f"Housing: {fmt(housing)}\n\nTRANSPORT allowance?\n(Enter 0 if none)"

    if s == 'EMP_TRANSPORT':
        transport = parse_number(text)
        if transport is None:
            return "❌ Invalid"
        set_state(phone, 'EMP_OTHER', {**d, 'transport': transport})
        return f"Transport: {fmt(transport)}\n\nOTHER allowances?\n(Enter 0 if none)"

    if s == 'EMP_OTHER':
        other = parse_number(text)
        if other is None:
            return "❌ Invalid"

        # Save employee
        emp_id = f"EMP{len(DB.employees)+1:04d}"
        emp_data = {
            **d,
            'other': other,
            'id': emp_id,
            'company_phone': phone,
            'leave_balance': DEFAULT_ANNUAL_LEAVE_DAYS,
            'created': datetime.now().isoformat()
        }
        DB.employees[emp_id] = emp_data

        reset_state(phone)

        total = d['basic'] + d['housing'] + d['transport'] + other
        return f"""✅ *Employee Added!*

{d['name']} ({emp_id})
Position: {d['position']}
Gross: {fmt(total)}

*Next:*
• ADD EMPLOYEE
• PAYROLL
• LIST"""

    return show_menu()

def handle_payroll(phone: str) -> Dict:
    emps = [e for e in DB.employees.values() if e.get('company_phone') == phone]

    if not emps:
        return {"message": "⚠️ No employees. Type: ADD EMPLOYEE"}

    results = []
    total_net = Decimal('0')

    for emp in emps:
        salary = EmployeeSalaryStructure(
            employee_id=emp['id'],
            employee_name=emp['name'],
            basic_salary=Decimal(str(emp['basic'])),
            housing_allowance=Decimal(str(emp.get('housing', 0))),
            transport_allowance=Decimal(str(emp.get('transport', 0))),
            other_allowances=Decimal(str(emp.get('other', 0)))
        )

        result = payroll_engine.calculate_payroll(
            salary,
            date.today().replace(day=1),
            date.today()
        )

        results.append(result)
        total_net += result.net_salary

    # Store results in conversation state for numeric reply lookup
    payroll_data = [
        {'emp_id': r.employee_id, 'emp_name': r.employee_name}
        for r in results
    ]
    set_state(phone, 'PAYROLL_VIEW', {'payroll_results': payroll_data})

    month = date.today().strftime('%B %Y')
    response = f"💰 *PAYROLL - {month}*\n\n{len(emps)} Employees\n\n"

    for i, r in enumerate(results, 1):
        response += f"*{i}. {r.employee_name}*\n"
        response += f"Gross: {fmt(r.gross_salary)}\n"
        response += f"Deductions: {fmt(r.total_deductions)}\n"
        response += f"*Net: {fmt(r.net_salary)}*\n\n"

    response += f"{'━'*30}\n*TOTAL NET: {fmt(total_net)}*\n{'━'*30}\n\n"
    response += f"Reply 1-{len(results)} to view payslip"

    return {"message": response}

def handle_payroll_detail(phone: str, index: int, state: Dict) -> str:
    """Handle numeric reply after PAYROLL to show individual payslip."""
    payroll_results = state['data'].get('payroll_results', [])

    if index < 1 or index > len(payroll_results):
        return f"❌ Invalid. Reply 1-{len(payroll_results)}"

    emp_ref = payroll_results[index - 1]
    emp = DB.employees.get(emp_ref['emp_id'])

    if not emp:
        return "❌ Employee not found"

    return build_payslip_for_employee(emp)

def handle_payslip(phone: str) -> str:
    """Handle PAYSLIP command - employee self-service via phone lookup."""
    # First check if this phone is an employer with employees
    emps = [e for e in DB.employees.values() if e.get('company_phone') == phone]
    if emps:
        # Employer: show list and let them pick
        if len(emps) == 1:
            return build_payslip_for_employee(emps[0])
        payroll_data = [{'emp_id': e['id'], 'emp_name': e['name']} for e in emps]
        set_state(phone, 'PAYROLL_VIEW', {'payroll_results': payroll_data})
        response = "📄 *Select Employee*\n\n"
        for i, emp in enumerate(emps, 1):
            response += f"*{i}.* {emp['name']}\n"
        response += f"\nReply 1-{len(emps)}"
        return response

    # Employee self-service: look up by phone number
    emp = find_employee_by_phone(phone)
    if emp:
        return build_payslip_for_employee(emp)

    return "⚠️ No employee record found for your phone number.\n\nAsk your employer to add you via ADD EMPLOYEE."

def handle_leave(phone: str) -> str:
    """Handle LEAVE command - show leave balance."""
    # Check if employee (by phone lookup)
    emp = find_employee_by_phone(phone)
    if emp:
        balance = emp.get('leave_balance', DEFAULT_ANNUAL_LEAVE_DAYS)
        return (
            f"🏖️ *Leave Balance*\n\n"
            f"*{emp['name']}*\n\n"
            f"Annual Leave: *{balance} days*\n"
            f"Year: {date.today().year}\n\n"
            f"Contact your HR admin to request leave."
        )

    # Check if employer - show all employees' leave
    emps = [e for e in DB.employees.values() if e.get('company_phone') == phone]
    if emps:
        response = f"🏖️ *Leave Balances*\n\n"
        for emp in emps:
            balance = emp.get('leave_balance', DEFAULT_ANNUAL_LEAVE_DAYS)
            response += f"*{emp['name']}*: {balance} days\n"
        return response

    return "⚠️ No employee record found.\n\nAsk your employer to add you via ADD EMPLOYEE."

def list_employees(phone: str) -> str:
    emps = [e for e in DB.employees.values() if e.get('company_phone') == phone]

    if not emps:
        return "📭 No employees\n\nType: ADD EMPLOYEE"

    response = f"*👥 Your Team ({len(emps)})*\n\n"

    for i, emp in enumerate(emps, 1):
        total = emp['basic'] + emp.get('housing', 0) + emp.get('transport', 0) + emp.get('other', 0)
        response += f"*{i}. {emp['name']}*\n"
        response += f"   {emp['position']}\n"
        response += f"   {fmt(total)}\n\n"

    return response

@app.get("/")
async def root():
    return {"status": "Nigerian HR Bot is running!", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
