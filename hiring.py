"""
Sawa — Hiring pipeline: job posting, applications, candidate management
"""
import secrets
from datetime import date

from db import (
    AsyncSession, Job, Candidate, Interview, Employee, User, ConversationState,
    get_company_by_phone, get_user, get_jobs, get_job_by_code, get_candidates_for_job,
    get_candidate_by_id, get_employee_count,
    set_conversation_state, reset_conversation_state, log_action, new_id,
)
from auth import check_role, encrypt_phone
from utils import fmt, sanitize_input


def _generate_job_code() -> str:
    """Generate a short job code like SAW-A3F2."""
    return f"SAW-{secrets.token_hex(2).upper()}"


# ── POST JOB Flow ───────────────────────────────────────────────────────────


async def start_post_job(session: AsyncSession, phone: str) -> str:
    company = await get_company_by_phone(session, phone)
    if not company:
        return "\u26a0\ufe0f Please REGISTER your company first"

    user = await get_user(session, phone)
    if not check_role(user, "POST_JOB"):
        return "\u26a0\ufe0f Only owners and admins can post jobs."

    await set_conversation_state(session, phone, 'JOB_TITLE', {'company_id': company.id})
    return "\U0001f4e2 *Post a Job*\n\nJob title?"


async def show_candidates_menu(session: AsyncSession, phone: str) -> str:
    company = await get_company_by_phone(session, phone)
    if not company:
        return "\u26a0\ufe0f Please REGISTER your company first"

    user = await get_user(session, phone)
    if not check_role(user, "CANDIDATES"):
        return "\u26a0\ufe0f Only owners and admins can view candidates."

    jobs = await get_jobs(session, company.id)
    if not jobs:
        return "\u26a0\ufe0f No open jobs. Type: POST JOB"

    response = "\U0001f465 *Your Open Jobs*\n\n"
    job_list = []
    for i, job in enumerate(jobs, 1):
        candidates = await get_candidates_for_job(session, job.id)
        response += f"*{i}.* {job.title} ({job.job_code}) - {len(candidates)} applicant(s)\n"
        job_list.append({'job_id': job.id, 'job_code': job.job_code, 'title': job.title})

    await set_conversation_state(session, phone, 'CAND_SELECT_JOB', {'company_id': company.id, 'jobs': job_list})
    response += f"\nReply 1-{len(jobs)} to view candidates"
    return response


async def start_apply(session: AsyncSession, phone: str, job_code: str) -> str:
    job = await get_job_by_code(session, job_code.upper())
    if not job:
        return f"\u274c Job code *{job_code}* not found. Check the code and try again."
    if job.status != "open":
        return "\u26a0\ufe0f This position is no longer accepting applications."

    await set_conversation_state(session, phone, 'APPLY_NAME', {
        'job_id': job.id,
        'job_code': job.job_code,
        'company_id': job.company_id,
        'job_title': job.title,
    })
    return f"\U0001f4e9 *Apply for: {job.title}*\n\nYour full name?"


# ── Hiring State Machine ───────────────────────────────────────────────────


async def handle_hiring_state(session: AsyncSession, phone: str, text: str, conv: ConversationState) -> str:
    s = conv.state
    d = dict(conv.data or {})

    # ── POST JOB ──
    if s == 'JOB_TITLE':
        await set_conversation_state(session, phone, 'JOB_DESC', {'title': text})
        return f"Title: *{text}*\n\nJob description? (brief summary)"

    if s == 'JOB_DESC':
        await set_conversation_state(session, phone, 'JOB_REQS', {'description': text})
        return "Requirements? (e.g. 3 years experience, BSc)"

    if s == 'JOB_REQS':
        await set_conversation_state(session, phone, 'JOB_LOCATION', {'requirements': text})
        return "Location? (e.g. Lagos, Remote)"

    if s == 'JOB_LOCATION':
        await set_conversation_state(session, phone, 'JOB_SALARY', {'location': text})
        return "Salary range? (e.g. 300k-500k or type SKIP)"

    if s == 'JOB_SALARY':
        salary_range = None if text.upper() == 'SKIP' else text
        if salary_range:
            await set_conversation_state(session, phone, 'JOB_CONFIRM', {'salary_range': salary_range})
        else:
            await set_conversation_state(session, phone, 'JOB_CONFIRM', {'salary_range': ''})

        d_updated = dict((await get_conversation_state(session, phone)).data or {})
        return (
            f"\U0001f4cb *Confirm Job Posting*\n\n"
            f"Title: *{d_updated.get('title')}*\n"
            f"Description: {d_updated.get('description', 'N/A')}\n"
            f"Requirements: {d_updated.get('requirements', 'N/A')}\n"
            f"Location: {d_updated.get('location', 'N/A')}\n"
            f"Salary: {d_updated.get('salary_range') or 'Not specified'}\n\n"
            f"Reply *YES* to post or *CANCEL* to discard."
        )

    if s == 'JOB_CONFIRM':
        if text.upper() != 'YES':
            await reset_conversation_state(session, phone)
            return "Job posting cancelled."

        job_code = _generate_job_code()
        company_id = d.get('company_id')

        job = Job(
            company_id=company_id,
            job_code=job_code,
            title=d.get('title', ''),
            description=d.get('description'),
            requirements=d.get('requirements'),
            location=d.get('location'),
            salary_range=d.get('salary_range'),
            status='open',
        )
        session.add(job)

        await log_action(session, company_id, phone, "POST_JOB", {"job_code": job_code, "title": d.get('title')})
        await reset_conversation_state(session, phone)

        return (
            f"\u2705 *Job Posted!*\n\n"
            f"Code: *{job_code}*\n"
            f"Title: {d.get('title')}\n\n"
            f"Candidates apply by texting:\n"
            f"*APPLY {job_code}*"
        )

    # ── APPLY ──
    if s == 'APPLY_NAME':
        await set_conversation_state(session, phone, 'APPLY_EXPERIENCE', {'name': text})
        return f"Hi {text}! Brief summary of your experience?"

    if s == 'APPLY_EXPERIENCE':
        company_id = d.get('company_id')
        job_id = d.get('job_id')

        candidate = Candidate(
            job_id=job_id,
            company_id=company_id,
            name=d.get('name', ''),
            phone=phone,
            experience=text,
            status='applied',
        )
        session.add(candidate)

        await log_action(session, company_id, phone, "APPLY", {
            "job_code": d.get('job_code'), "name": d.get('name')
        })
        await reset_conversation_state(session, phone)

        return (
            f"\u2705 *Application Submitted!*\n\n"
            f"Position: {d.get('job_title')}\n"
            f"Name: {d.get('name')}\n\n"
            f"The employer will contact you if you're shortlisted."
        )

    # ── CANDIDATE MANAGEMENT ──
    if s == 'CAND_SELECT_JOB':
        jobs = d.get('jobs', [])
        if text.isdigit():
            idx = int(text)
            if 1 <= idx <= len(jobs):
                selected = jobs[idx - 1]
                candidates = await get_candidates_for_job(session, selected['job_id'])
                if not candidates:
                    await reset_conversation_state(session, phone)
                    return f"No candidates yet for *{selected['title']}*."

                cand_list = []
                response = f"\U0001f465 *Candidates for {selected['title']}*\n\n"
                for i, c in enumerate(candidates, 1):
                    response += f"*{i}.* {c.name} - {c.status.upper()}\n"
                    cand_list.append({'id': c.id, 'name': c.name, 'status': c.status})

                await set_conversation_state(session, phone, 'CAND_SELECT', {
                    'candidates': cand_list,
                    'job_id': selected['job_id'],
                    'job_title': selected['title'],
                })
                response += f"\nReply 1-{len(candidates)} to manage"
                return response

        return "\u274c Invalid selection."

    if s == 'CAND_SELECT':
        candidates = d.get('candidates', [])
        if text.isdigit():
            idx = int(text)
            if 1 <= idx <= len(candidates):
                selected = candidates[idx - 1]
                await set_conversation_state(session, phone, 'CAND_ACTION', {
                    'candidate_id': selected['id'],
                    'candidate_name': selected['name'],
                    'candidate_status': selected['status'],
                })
                return (
                    f"*{selected['name']}* - {selected['status'].upper()}\n\n"
                    f"Actions:\n"
                    f"*1.* Advance to next stage\n"
                    f"*2.* Reject\n"
                    f"*3.* Schedule interview\n"
                    f"*4.* Send offer\n"
                    f"*5.* Hire (create employee)\n"
                    f"*6.* Back"
                )
        return "\u274c Invalid selection."

    if s == 'CAND_ACTION':
        candidate_id = d.get('candidate_id')
        candidate = await get_candidate_by_id(session, candidate_id)
        if not candidate:
            await reset_conversation_state(session, phone)
            return "\u274c Candidate not found."

        company_id = d.get('company_id')

        if text == '1':  # Advance
            stages = ['applied', 'screening', 'interview', 'offer', 'hired']
            current_idx = stages.index(candidate.status) if candidate.status in stages else 0
            if current_idx < len(stages) - 1:
                candidate.status = stages[current_idx + 1]
                await session.flush()
                await log_action(session, company_id, phone, "ADVANCE_CANDIDATE", {
                    "name": candidate.name, "new_status": candidate.status
                })
                await reset_conversation_state(session, phone)
                return f"\u2705 *{candidate.name}* advanced to *{candidate.status.upper()}*"
            await reset_conversation_state(session, phone)
            return f"*{candidate.name}* is already at final stage."

        if text == '2':  # Reject
            candidate.status = 'rejected'
            await session.flush()
            await log_action(session, company_id, phone, "REJECT_CANDIDATE", {"name": candidate.name})
            await reset_conversation_state(session, phone)
            return f"\u274c *{candidate.name}* has been rejected."

        if text == '3':  # Schedule interview
            await set_conversation_state(session, phone, 'CAND_INTERVIEW_DATE', {
                'candidate_id': candidate_id,
            })
            return f"Schedule interview for *{candidate.name}*\n\nDate & time? (e.g. Feb 20, 2pm)"

        if text == '4':  # Send offer
            candidate.status = 'offer'
            await session.flush()
            await log_action(session, company_id, phone, "SEND_OFFER", {"name": candidate.name})
            await reset_conversation_state(session, phone)
            return (
                f"\U0001f4e8 *Offer sent to {candidate.name}*\n\n"
                f"Candidate can reply ACCEPT or DECLINE.\n"
                f"(Notification would be sent via WhatsApp)"
            )

        if text == '5':  # Hire → create employee
            await set_conversation_state(session, phone, 'CAND_HIRE_SALARY', {
                'candidate_id': candidate_id,
                'candidate_name': candidate.name,
                'candidate_phone': candidate.phone,
            })
            return f"Hiring *{candidate.name}*\n\n\U0001f4b0 BASIC SALARY (monthly)?"

        if text == '6':  # Back
            from conversation import show_menu
            await reset_conversation_state(session, phone)
            return show_menu()

        return "\u274c Reply 1-6"

    if s == 'CAND_INTERVIEW_DATE':
        candidate_id = d.get('candidate_id')
        company_id = d.get('company_id')

        interview = Interview(
            candidate_id=candidate_id,
            company_id=company_id,
            location=text,
            status='scheduled',
        )
        session.add(interview)

        # Update candidate status
        candidate = await get_candidate_by_id(session, candidate_id)
        if candidate:
            candidate.status = 'interview'
            await session.flush()

        await log_action(session, company_id, phone, "SCHEDULE_INTERVIEW", {
            "candidate_id": candidate_id, "details": text
        })
        await reset_conversation_state(session, phone)
        return f"\u2705 Interview scheduled: {text}\n\nCandidate will be notified."

    if s == 'CAND_HIRE_SALARY':
        from utils import parse_number
        basic = parse_number(text)
        if not basic:
            return "\u274c Invalid. Example: 200000"

        company_id = d.get('company_id')
        candidate_name = d.get('candidate_name')
        candidate_phone = d.get('candidate_phone', '')
        candidate_id = d.get('candidate_id')

        count = await get_employee_count(session, company_id)
        emp_code = f"EMP{count + 1:04d}"

        encrypted_phone = encrypt_phone(candidate_phone) if candidate_phone else None

        emp = Employee(
            company_id=company_id,
            employee_code=emp_code,
            name=candidate_name,
            phone_encrypted=encrypted_phone,
            position='',
            salary_structure={'basic': basic, 'housing': 0, 'transport': 0, 'other': 0},
            leave_balance=21,
        )
        session.add(emp)

        # Update candidate status
        candidate = await get_candidate_by_id(session, candidate_id)
        if candidate:
            candidate.status = 'hired'
            await session.flush()

        await log_action(session, company_id, phone, "HIRE_CANDIDATE", {
            "name": candidate_name, "emp_code": emp_code
        })
        await reset_conversation_state(session, phone)

        return (
            f"\u2705 *{candidate_name} Hired!*\n\n"
            f"Employee Code: {emp_code}\n"
            f"Basic Salary: {fmt(basic)}\n\n"
            f"Use ADD EMPLOYEE to update their full salary structure."
        )

    # Fallback
    await reset_conversation_state(session, phone)
    from conversation import show_menu
    return show_menu()
