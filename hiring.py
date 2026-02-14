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
from utils import fmt, parse_number, sanitize_input

# Yes/no phrase matching
YES_PHRASES = {'yes', 'yeah', 'yep', 'sure', 'go ahead', 'looks good', 'confirm', 'ok', 'okay', 'yea', 'y', 'do it', 'post it', 'lgtm'}
NO_PHRASES = {'no', 'nah', 'nope', 'cancel', 'stop', 'don\'t', 'abort', 'n'}
SKIP_PHRASES = {'skip', 'none', 'n/a', 'na', 'rather not', 'no salary', 'not specified', '-', 'pass'}


def _is_yes(text: str) -> bool:
    return text.lower().strip() in YES_PHRASES


def _is_no(text: str) -> bool:
    return text.lower().strip() in NO_PHRASES


def _is_skip(text: str) -> bool:
    return text.lower().strip() in SKIP_PHRASES


def _generate_job_code() -> str:
    """Generate a short job code like SAW-A3F2."""
    return f"SAW-{secrets.token_hex(2).upper()}"


# ── POST JOB Flow ───────────────────────────────────────────────────────────


async def start_post_job(session: AsyncSession, phone: str) -> str:
    company = await get_company_by_phone(session, phone)
    if not company:
        return "Hmm, you haven't registered yet. Just say *register* to get started! \U0001f60a"

    user = await get_user(session, phone)
    if not check_role(user, "POST_JOB"):
        return "Only owners and admins can post jobs. Check with your admin! \U0001f512"

    await set_conversation_state(session, phone, 'JOB_TITLE', {'company_id': company.id})
    return "\U0001f4e2 *Post a Job*\n\nWhat's the job title?"


async def show_candidates_menu(session: AsyncSession, phone: str) -> str:
    company = await get_company_by_phone(session, phone)
    if not company:
        return "Hmm, you haven't registered yet. Just say *register* to get started! \U0001f60a"

    user = await get_user(session, phone)
    if not check_role(user, "CANDIDATES"):
        return "Only owners and admins can view candidates. Check with your admin! \U0001f512"

    jobs = await get_jobs(session, company.id)
    if not jobs:
        return "No open jobs yet! Say *post job* to create one. \U0001f4e2"

    response = "\U0001f465 *Your Open Jobs*\n\n"
    job_list = []
    for i, job in enumerate(jobs, 1):
        candidates = await get_candidates_for_job(session, job.id)
        response += f"*{i}.* {job.title} ({job.job_code}) \u2014 {len(candidates)} applicant(s)\n"
        job_list.append({'job_id': job.id, 'job_code': job.job_code, 'title': job.title})

    await set_conversation_state(session, phone, 'CAND_SELECT_JOB', {'company_id': company.id, 'jobs': job_list})
    response += f"\nReply 1-{len(jobs)} to view candidates"
    return response


async def start_apply(session: AsyncSession, phone: str, job_code: str) -> str:
    job = await get_job_by_code(session, job_code.upper())
    if not job:
        return f"Couldn't find job code *{job_code}*. Double-check and try again! \U0001f50d"
    if job.status != "open":
        return "This position is no longer accepting applications. \U0001f614"

    await set_conversation_state(session, phone, 'APPLY_NAME', {
        'job_id': job.id,
        'job_code': job.job_code,
        'company_id': job.company_id,
        'job_title': job.title,
    })
    return f"\U0001f4e9 *Apply for: {job.title}*\n\nWhat's your full name?"


# ── Hiring State Machine ───────────────────────────────────────────────────


async def handle_hiring_state(session: AsyncSession, phone: str, text: str, conv: ConversationState) -> str:
    s = conv.state
    d = dict(conv.data or {})

    # ── POST JOB ──
    if s == 'JOB_TITLE':
        await set_conversation_state(session, phone, 'JOB_DESC', {'title': text})
        return f"*{text}* \u2014 nice! \u2705\n\nGive a brief description of the role:"

    if s == 'JOB_DESC':
        await set_conversation_state(session, phone, 'JOB_REQS', {'description': text})
        return "What are the requirements? _(e.g. 3 years experience, BSc)_"

    if s == 'JOB_REQS':
        await set_conversation_state(session, phone, 'JOB_LOCATION', {'requirements': text})
        return "Where is the role based? _(e.g. Lagos, Remote, Hybrid)_"

    if s == 'JOB_LOCATION':
        await set_conversation_state(session, phone, 'JOB_SALARY', {'location': text})
        return "Any salary range to show? _(e.g. 300k-500k, or say *skip* to leave it out)_"

    if s == 'JOB_SALARY':
        salary_range = None if _is_skip(text) else text
        if salary_range:
            await set_conversation_state(session, phone, 'JOB_CONFIRM', {'salary_range': salary_range})
        else:
            await set_conversation_state(session, phone, 'JOB_CONFIRM', {'salary_range': ''})

        d_updated = dict((await get_conversation_state(session, phone)).data or {})
        return (
            f"\U0001f4cb *Here's your job posting:*\n\n"
            f"Title: *{d_updated.get('title')}*\n"
            f"Description: {d_updated.get('description', 'N/A')}\n"
            f"Requirements: {d_updated.get('requirements', 'N/A')}\n"
            f"Location: {d_updated.get('location', 'N/A')}\n"
            f"Salary: {d_updated.get('salary_range') or 'Not specified'}\n\n"
            f"Looks good? Say *yes* to post or *cancel* to discard."
        )

    if s == 'JOB_CONFIRM':
        if _is_no(text):
            await reset_conversation_state(session, phone)
            return "No worries, job posting discarded. \U0001f44d"

        if not _is_yes(text):
            return "Just say *yes* to post the job, or *cancel* to discard."

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
            f"Job posted! \U0001f389\n\n"
            f"Code: *{job_code}*\n"
            f"Title: {d.get('title')}\n\n"
            f"Candidates can apply by texting:\n"
            f"*APPLY {job_code}*"
        )

    # ── APPLY ──
    if s == 'APPLY_NAME':
        name = text.strip()
        if len(text.split()) > 3:
            from conversation import _smart_extract
            extracted, _ = await _smart_extract(text, 'name')
            if extracted:
                name = str(extracted)
        await set_conversation_state(session, phone, 'APPLY_EXPERIENCE', {'name': name})
        return f"Nice to meet you, *{name}*! \U0001f44b\n\nTell us briefly about your experience:"

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
            f"Application submitted! \U0001f389\n\n"
            f"Position: *{d.get('job_title')}*\n"
            f"Name: *{d.get('name')}*\n\n"
            f"The employer will reach out if you're shortlisted. Good luck! \U0001f340"
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
                    return f"No candidates yet for *{selected['title']}*. They'll show up here once people apply! \U0001f4e9"

                cand_list = []
                response = f"\U0001f465 *Candidates for {selected['title']}*\n\n"
                for i, c in enumerate(candidates, 1):
                    response += f"*{i}.* {c.name} \u2014 _{c.status.upper()}_\n"
                    cand_list.append({'id': c.id, 'name': c.name, 'status': c.status})

                await set_conversation_state(session, phone, 'CAND_SELECT', {
                    'candidates': cand_list,
                    'job_id': selected['job_id'],
                    'job_title': selected['title'],
                })
                response += f"\nReply 1-{len(candidates)} to manage a candidate"
                return response

        return "That's not a valid option. Pick a number from the list above."

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
                    f"*{selected['name']}* \u2014 _{selected['status'].upper()}_\n\n"
                    f"What would you like to do?\n\n"
                    f"*1.* Advance to next stage \u2b06\ufe0f\n"
                    f"*2.* Reject \u274c\n"
                    f"*3.* Schedule interview \U0001f4c5\n"
                    f"*4.* Send offer \U0001f4e8\n"
                    f"*5.* Hire (add to team) \U0001f389\n"
                    f"*6.* Back"
                )
        return "That's not a valid option. Pick a number from the list above."

    if s == 'CAND_ACTION':
        candidate_id = d.get('candidate_id')
        candidate = await get_candidate_by_id(session, candidate_id)
        if not candidate:
            await reset_conversation_state(session, phone)
            return "Couldn't find that candidate. They may have been removed."

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
                return f"*{candidate.name}* moved to *{candidate.status.upper()}* \u2b06\ufe0f"
            await reset_conversation_state(session, phone)
            return f"*{candidate.name}* is already at the final stage."

        if text == '2':  # Reject
            candidate.status = 'rejected'
            await session.flush()
            await log_action(session, company_id, phone, "REJECT_CANDIDATE", {"name": candidate.name})
            await reset_conversation_state(session, phone)
            return f"*{candidate.name}* has been rejected. \u274c"

        if text == '3':  # Schedule interview
            await set_conversation_state(session, phone, 'CAND_INTERVIEW_DATE', {
                'candidate_id': candidate_id,
            })
            return f"Let's schedule an interview for *{candidate.name}* \U0001f4c5\n\nWhen and where? _(e.g. Feb 20, 2pm at Lagos office)_"

        if text == '4':  # Send offer
            candidate.status = 'offer'
            await session.flush()
            await log_action(session, company_id, phone, "SEND_OFFER", {"name": candidate.name})
            await reset_conversation_state(session, phone)
            return (
                f"Offer sent to *{candidate.name}*! \U0001f4e8\n\n"
                f"They'll be notified to respond.\n"
                f"_(WhatsApp notification would be sent)_"
            )

        if text == '5':  # Hire → create employee
            await set_conversation_state(session, phone, 'CAND_HIRE_SALARY', {
                'candidate_id': candidate_id,
                'candidate_name': candidate.name,
                'candidate_phone': candidate.phone,
            })
            return f"Great choice! Let's bring *{candidate.name}* onboard \U0001f389\n\nWhat will their monthly basic salary be? _(e.g. 200k)_"

        if text == '6':  # Back
            from conversation import show_menu
            await reset_conversation_state(session, phone)
            return show_menu()

        return "Pick a number from 1-6."

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
        return f"Interview scheduled! \U0001f4c5\n\n*Details:* {text}\n\nThe candidate will be notified."

    if s == 'CAND_HIRE_SALARY':
        basic = parse_number(text)
        if not basic:
            # Try AI extraction for conversational input
            from conversation import _smart_extract
            extracted, _ = await _smart_extract(text, 'salary', validator=lambda t: parse_number(t))
            if extracted:
                basic = extracted
            else:
                return "I didn't catch that as a number. Try *200000* or *200k* \U0001f4b0"

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
            f"*{candidate_name}* is officially on the team! \U0001f389\n\n"
            f"Employee Code: *{emp_code}*\n"
            f"Basic Salary: {fmt(basic)}\n\n"
            f"Say *add employee* to update their full salary structure."
        )

    # Fallback
    await reset_conversation_state(session, phone)
    from conversation import show_menu
    return show_menu()
