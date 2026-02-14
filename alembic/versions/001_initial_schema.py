"""Initial schema — all Sawa tables

Revision ID: 001
Revises: None
Create Date: 2026-02-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Companies
    op.create_table(
        'companies',
        sa.Column('id', sa.String(12), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('email', sa.String(254), nullable=False),
        sa.Column('phone', sa.String(30), unique=True, nullable=False),
        sa.Column('settings_json', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Users
    op.create_table(
        'users',
        sa.Column('id', sa.String(12), primary_key=True),
        sa.Column('company_id', sa.String(12), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('phone', sa.String(30), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='owner'),
        sa.Column('pin_hash', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('company_id', 'phone', name='uq_user_company_phone'),
    )

    # Employees
    op.create_table(
        'employees',
        sa.Column('id', sa.String(12), primary_key=True),
        sa.Column('company_id', sa.String(12), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('employee_code', sa.String(20), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('phone_encrypted', sa.String(500), nullable=True),
        sa.Column('position', sa.String(200), nullable=True),
        sa.Column('salary_structure', postgresql.JSONB(), server_default='{}'),
        sa.Column('leave_balance', sa.Integer(), server_default='21'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('company_id', 'employee_code', name='uq_emp_company_code'),
    )
    op.create_index('ix_employees_company', 'employees', ['company_id'])

    # Payroll runs
    op.create_table(
        'payroll_runs',
        sa.Column('id', sa.String(12), primary_key=True),
        sa.Column('company_id', sa.String(12), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('period', sa.String(20), nullable=False),
        sa.Column('results', postgresql.JSONB(), nullable=False),
        sa.Column('run_by', sa.String(30), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_payroll_company', 'payroll_runs', ['company_id'])

    # Audit log
    op.create_table(
        'audit_log',
        sa.Column('id', sa.String(12), primary_key=True),
        sa.Column('company_id', sa.String(12), nullable=True),
        sa.Column('user_phone', sa.String(30), nullable=False),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('details', postgresql.JSONB(), server_default='{}'),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_audit_company', 'audit_log', ['company_id'])

    # Conversation states
    op.create_table(
        'conversation_states',
        sa.Column('id', sa.String(12), primary_key=True),
        sa.Column('phone', sa.String(30), unique=True, nullable=False),
        sa.Column('state', sa.String(50), server_default='MENU'),
        sa.Column('data', postgresql.JSONB(), server_default='{}'),
        sa.Column('pin_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Jobs
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(12), primary_key=True),
        sa.Column('company_id', sa.String(12), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('job_code', sa.String(20), unique=True, nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('requirements', sa.Text(), nullable=True),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('salary_range', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_jobs_company', 'jobs', ['company_id'])

    # Candidates
    op.create_table(
        'candidates',
        sa.Column('id', sa.String(12), primary_key=True),
        sa.Column('job_id', sa.String(12), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', sa.String(12), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('phone', sa.String(30), nullable=False),
        sa.Column('experience', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), server_default='applied'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_candidates_company', 'candidates', ['company_id'])
    op.create_index('ix_candidates_job', 'candidates', ['job_id'])

    # Interviews
    op.create_table(
        'interviews',
        sa.Column('id', sa.String(12), primary_key=True),
        sa.Column('candidate_id', sa.String(12), sa.ForeignKey('candidates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', sa.String(12), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('location', sa.String(300), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), server_default='scheduled'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_interviews_company', 'interviews', ['company_id'])


def downgrade() -> None:
    op.drop_table('interviews')
    op.drop_table('candidates')
    op.drop_table('jobs')
    op.drop_table('conversation_states')
    op.drop_table('audit_log')
    op.drop_table('payroll_runs')
    op.drop_table('employees')
    op.drop_table('users')
    op.drop_table('companies')
