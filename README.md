# Nigerian HR Bot

A WhatsApp-based HR and payroll system built for Nigerian businesses. Handles payroll calculations with full PAYE, PenCom, and NHF compliance.

## Features

**For Employers:**
- Company registration via WhatsApp
- Add employees with salary structure (basic, housing, transport, other allowances)
- Run payroll with automatic PAYE tax, pension, and NHF calculations
- View employee list and individual payslips

**For Employees:**
- View your own payslip by texting PAYSLIP from your registered phone
- Check annual leave balance (21 days standard)

**Payroll Engine:**
- 2026 PAYE progressive tax brackets
- Pension contributions (8% employee / 10% employer) on basic + housing + transport
- NHF at 2.5% of basic salary
- Rent relief (20% of gross, capped at ₦500k/year)
- Prorated salary support for mid-month joiners

## WhatsApp Commands

| Command | Description |
|---------|-------------|
| `REGISTER` | Setup your company |
| `ADD EMPLOYEE` | Add a team member |
| `PAYROLL` | Calculate salaries for all employees |
| `PAYSLIP` | View payslip (employer picks employee, employee sees own) |
| `LEAVE` | Check leave balance |
| `LIST` | View all employees |
| `HELP` | Show menu |

After running `PAYROLL`, reply with a number (e.g. `1`) to view that employee's detailed payslip.

## Setup

### Prerequisites
- Python 3.10+
- A Twilio account with WhatsApp sandbox or approved number

### Install

```bash
git clone https://github.com/oma0011/nigerian-hr-bot.git
cd nigerian-hr-bot
pip install -r requirements.txt
```

### Configure

```bash
cp env.example .env
# Edit .env with your Twilio credentials
```

### Run

```bash
uvicorn main:app --port 8000
```

### Test with curl

```bash
# Register a company
curl -X POST localhost:8000/whatsapp/webhook \
  -d "From=whatsapp:+2348012345678" -d "Body=REGISTER"

# Run payroll
curl -X POST localhost:8000/whatsapp/webhook \
  -d "From=whatsapp:+2348012345678" -d "Body=PAYROLL"
```

## Deployment

Includes a `Procfile` for deployment to Railway, Render, or Heroku:

```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set your Twilio webhook URL to `https://your-domain.com/whatsapp/webhook`.

## Project Structure

```
├── main.py              # FastAPI app, WhatsApp webhook, conversation state machine
├── payroll_engine.py    # Payroll calculations (PAYE, pension, NHF)
├── requirements.txt     # Python dependencies
├── Procfile             # PaaS deployment config
└── env.example          # Environment variable template
```

## License

MIT
