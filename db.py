"""
Sawa — SQLAlchemy async models and query helpers
All queries scoped by company_id for tenant isolation.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey, Text, Numeric,
    UniqueConstraint, Index, JSON,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import select, update, delete
from sqlalchemy.orm.attributes import flag_modified

from config import settings

# Engine & session factory
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Models ──────────────────────────────────────────────────────────────────


class Company(Base):
    __tablename__ = "companies"

    id = Column(String(12), primary_key=True, default=new_id)
    name = Column(String(200), nullable=False)
    email = Column(String(254), nullable=False)
    phone = Column(String(30), unique=True, nullable=False)
    settings_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    users = relationship("User", back_populates="company", cascade="all, delete-orphan")
    employees = relationship("Employee", back_populates="company", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(String(12), primary_key=True, default=new_id)
    company_id = Column(String(12), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    phone = Column(String(30), nullable=False)
    role = Column(String(20), nullable=False, default="owner")  # owner, admin, employee
    pin_hash = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    company = relationship("Company", back_populates="users")

    __table_args__ = (
        UniqueConstraint("company_id", "phone", name="uq_user_company_phone"),
    )


class Employee(Base):
    __tablename__ = "employees"

    id = Column(String(12), primary_key=True, default=new_id)
    company_id = Column(String(12), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_code = Column(String(20), nullable=False)
    name = Column(String(200), nullable=False)
    phone_encrypted = Column(String(500), nullable=True)  # Fernet-encrypted
    position = Column(String(200), nullable=True)
    salary_structure = Column(JSONB, nullable=False, default=dict)
    leave_balance = Column(Integer, default=21)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    company = relationship("Company", back_populates="employees")

    __table_args__ = (
        UniqueConstraint("company_id", "employee_code", name="uq_emp_company_code"),
        Index("ix_employees_company", "company_id"),
    )


class PayrollRun(Base):
    __tablename__ = "payroll_runs"

    id = Column(String(12), primary_key=True, default=new_id)
    company_id = Column(String(12), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    period = Column(String(20), nullable=False)
    results = Column(JSONB, nullable=False)
    run_by = Column(String(30), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_payroll_company", "company_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String(12), primary_key=True, default=new_id)
    company_id = Column(String(12), nullable=True)
    user_phone = Column(String(30), nullable=False)
    action = Column(String(100), nullable=False)
    details = Column(JSONB, default=dict)
    timestamp = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_audit_company", "company_id"),
    )


class ConversationState(Base):
    __tablename__ = "conversation_states"

    id = Column(String(12), primary_key=True, default=new_id)
    phone = Column(String(30), unique=True, nullable=False)
    state = Column(String(50), default="MENU")
    data = Column(JSONB, default=dict)
    pin_verified_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ── Hiring Models ───────────────────────────────────────────────────────────


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(12), primary_key=True, default=new_id)
    company_id = Column(String(12), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    job_code = Column(String(20), unique=True, nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    requirements = Column(Text, nullable=True)
    location = Column(String(200), nullable=True)
    salary_range = Column(String(100), nullable=True)
    status = Column(String(20), default="open")  # open, paused, closed
    created_at = Column(DateTime(timezone=True), default=utcnow)

    candidates = relationship("Candidate", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_jobs_company", "company_id"),
    )


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(String(12), primary_key=True, default=new_id)
    job_id = Column(String(12), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(String(12), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    phone = Column(String(30), nullable=False)
    experience = Column(Text, nullable=True)
    status = Column(String(20), default="applied")  # applied, screening, interview, offer, hired, rejected
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="candidates")

    __table_args__ = (
        Index("ix_candidates_company", "company_id"),
        Index("ix_candidates_job", "job_id"),
    )


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(String(12), primary_key=True, default=new_id)
    candidate_id = Column(String(12), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(String(12), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    location = Column(String(300), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(20), default="scheduled")  # scheduled, completed, cancelled
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_interviews_company", "company_id"),
    )


# ── Query Helpers (always company-scoped) ───────────────────────────────────


async def get_company_by_phone(session: AsyncSession, phone: str) -> Company | None:
    result = await session.execute(
        select(Company).where(Company.phone == phone)
    )
    return result.scalar_one_or_none()


async def get_user(session: AsyncSession, phone: str) -> User | None:
    result = await session.execute(
        select(User).where(User.phone == phone)
    )
    return result.scalar_one_or_none()


async def get_employees(session: AsyncSession, company_id: str, active_only: bool = True):
    q = select(Employee).where(Employee.company_id == company_id)
    if active_only:
        q = q.where(Employee.is_active == True)
    q = q.order_by(Employee.created_at)
    result = await session.execute(q)
    return result.scalars().all()


async def get_employee_by_code(session: AsyncSession, company_id: str, code: str) -> Employee | None:
    result = await session.execute(
        select(Employee).where(Employee.company_id == company_id, Employee.employee_code == code)
    )
    return result.scalar_one_or_none()


async def find_employee_by_phone(session: AsyncSession, phone_encrypted: str) -> Employee | None:
    """Find employee by encrypted phone value."""
    result = await session.execute(
        select(Employee).where(Employee.phone_encrypted == phone_encrypted, Employee.is_active == True)
    )
    return result.scalar_one_or_none()


async def get_employee_count(session: AsyncSession, company_id: str) -> int:
    from sqlalchemy import func
    result = await session.execute(
        select(func.count(Employee.id)).where(
            Employee.company_id == company_id, Employee.is_active == True
        )
    )
    return result.scalar_one()


async def check_duplicate_employee(session: AsyncSession, company_id: str, name: str) -> bool:
    from sqlalchemy import func
    result = await session.execute(
        select(Employee.id).where(
            Employee.company_id == company_id,
            func.lower(Employee.name) == name.strip().lower(),
            Employee.is_active == True
        )
    )
    return result.scalar_one_or_none() is not None


async def get_conversation_state(session: AsyncSession, phone: str) -> ConversationState | None:
    result = await session.execute(
        select(ConversationState).where(ConversationState.phone == phone)
    )
    return result.scalar_one_or_none()


async def set_conversation_state(
    session: AsyncSession, phone: str, state: str, data: dict | None = None
):
    conv = await get_conversation_state(session, phone)
    if conv is None:
        conv = ConversationState(phone=phone, state=state, data=data or {})
        session.add(conv)
    else:
        conv.state = state
        if data is not None:
            merged = dict(conv.data or {})
            merged.update(data)
            conv.data = merged
            flag_modified(conv, "data")
        conv.updated_at = utcnow()
    await session.flush()
    return conv


async def reset_conversation_state(session: AsyncSession, phone: str):
    conv = await get_conversation_state(session, phone)
    if conv:
        conv.state = "MENU"
        conv.data = {}
        flag_modified(conv, "data")
        conv.pin_verified_at = None
        conv.updated_at = utcnow()
        await session.flush()


async def log_action(
    session: AsyncSession, company_id: str | None, phone: str, action: str, details: dict | None = None
):
    entry = AuditLog(
        company_id=company_id,
        user_phone=phone,
        action=action,
        details=details or {},
    )
    session.add(entry)
    await session.flush()


# ── Hiring query helpers ────────────────────────────────────────────────────


async def get_job_by_code(session: AsyncSession, job_code: str) -> Job | None:
    result = await session.execute(
        select(Job).where(Job.job_code == job_code)
    )
    return result.scalar_one_or_none()


async def get_jobs(session: AsyncSession, company_id: str, status: str = "open"):
    q = select(Job).where(Job.company_id == company_id, Job.status == status)
    q = q.order_by(Job.created_at.desc())
    result = await session.execute(q)
    return result.scalars().all()


async def get_candidates_for_job(session: AsyncSession, job_id: str):
    q = select(Candidate).where(Candidate.job_id == job_id).order_by(Candidate.created_at)
    result = await session.execute(q)
    return result.scalars().all()


async def get_candidate_by_id(session: AsyncSession, candidate_id: str) -> Candidate | None:
    result = await session.execute(
        select(Candidate).where(Candidate.id == candidate_id)
    )
    return result.scalar_one_or_none()
