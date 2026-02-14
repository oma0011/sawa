# Sawa — AI-Powered WhatsApp HR Platform

A secure, multi-tenant WhatsApp HR platform for Nigerian businesses. Handles company registration, employee management, payroll with full PAYE/PenCom/NHF compliance, hiring pipelines, and AI-powered natural language interaction.

## Features

**For Employers (Owner/Admin):**
- Company registration with PIN-secured access
- Add employees with full salary structures
- Run payroll with automatic PAYE tax, pension, and NHF calculations
- View employee list and individual payslips
- Post jobs and manage recruitment pipeline
- View candidates, schedule interviews, send offers, hire

**For Employees:**
- View your own payslip by texting PAYSLIP
- Check annual leave balance (21 days standard)

**For Candidates:**
- Apply to jobs via WhatsApp with a job code

**Security:**
- Twilio webhook signature validation
- PIN authentication for sensitive operations (10-min TTL)
- Role-based access control (owner/admin/employee)
- Phone numbers encrypted at rest (Fernet)
- Rate limiting (30 req/min)
- Audit logging for all actions
- Input sanitization (500 char limit, control char stripping)

**AI Layer (Claude API):**
- Natural language intent detection ("show me salaries" → PAYROLL)
- Entity extraction ("add John as accountant" → pre-fills name + position)
- Nigerian HR knowledge chat (labor law, minimum wage, etc.)
- Graceful fallback — exact commands always work without API key

**Infrastructure:**
- PostgreSQL with async SQLAlchemy + Alembic migrations
- Multi-tenant data isolation (all queries scoped by company_id)
- Structured JSON logging
- Connection pooling (10 + 20 overflow)
- WhatsApp 4096 char limit handling

## WhatsApp Commands

| Command | Description |
|---------|-------------|
| `REGISTER` | Setup your company (sets PIN) |
| `ADD EMPLOYEE` | Add a team member |
| `PAYROLL` | Calculate salaries (PIN required) |
| `PAYSLIP` | View payslip (PIN for employer, self-service for employee) |
| `LEAVE` | Check leave balance |
| `LIST` | View all employees |
| `POST JOB` | Create a job listing |
| `CANDIDATES` | View/manage applicants |
| `APPLY <code>` | Apply to a job (e.g. `APPLY SAW-A3F2`) |
| `HELP` | Show menu |
| `CANCEL` | Cancel current operation |

Or just type naturally: "how much do I get paid?", "add John as accountant", "what's minimum wage?"

## Setup

### Prerequisites
- Python 3.10+
- PostgreSQL
- A Twilio account with WhatsApp sandbox or approved number

### Install

```bash
git clone https://github.com/oma0011/sawa.git
cd sawa
pip install -r requirements.txt
```

### Configure

```bash
cp env.example .env
# Edit .env with your credentials
```

### Database

```bash
# Create database
createdb sawa

# Run migrations
alembic upgrade head
```

### Run

```bash
uvicorn main:app --port 8000
```

### Test with curl

```bash
# Register
curl -X POST localhost:8000/whatsapp/webhook \
  -d "From=whatsapp:+2348012345678" -d "Body=REGISTER"

# Follow prompts (company name → email → PIN)

# Add employee
curl -X POST localhost:8000/whatsapp/webhook \
  -d "From=whatsapp:+2348012345678" -d "Body=ADD EMPLOYEE"

# Run payroll
curl -X POST localhost:8000/whatsapp/webhook \
  -d "From=whatsapp:+2348012345678" -d "Body=PAYROLL"
```

## Deployment

Includes a `Procfile` for Railway, Render, or Heroku:

```
release: alembic upgrade head
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set your Twilio webhook URL to `https://your-domain.com/whatsapp/webhook`.

## Project Structure

```
├── main.py              # FastAPI app — thin webhook handler (~80 lines)
├── config.py            # Pydantic-settings env var loading
├── auth.py              # Twilio validation, PIN auth, RBAC, encryption
├── db.py                # SQLAlchemy async models + query helpers
├── conversation.py      # State machine logic (registration, employees, payroll)
├── hiring.py            # Recruitment pipeline (jobs, candidates, interviews)
├── ai.py                # Claude API intent detection + HR chat
├── payroll_engine.py    # Nigerian payroll calculations (PAYE, pension, NHF)
├── utils.py             # twiml_response, fmt, validators, sanitizers
├── alembic/             # Database migrations
├── alembic.ini
├── requirements.txt
├── Procfile
└── env.example
```

## License

MIT
