"""
SQLAlchemy ORM Models — mirrors the existing SQLite schema exactly.
Target: PostgreSQL (local dev first, then production).

Usage:
    from dashboard.models import Base, ClientsData, UserCredentials, ...
    from dashboard.db import engine, SessionLocal

Note: server_default is used everywhere so that raw SQL INSERTs
      (which bypass the ORM) still get correct column defaults.
"""

from datetime import datetime
from sqlalchemy import (
    BigInteger, Column, Float, ForeignKey,
    Index, Integer, SmallInteger, String, Text, UniqueConstraint,
    func, text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────
# api_keys
# ─────────────────────────────────────────
class ApiKey(Base):
    __tablename__ = 'api_keys'

    id         = Column(Integer, primary_key=True, autoincrement=True)
    key_hash   = Column(Text, unique=True, nullable=False)
    key_prefix = Column(Text, nullable=False)
    admin      = Column(Text, nullable=False)
    trader     = Column(Text, nullable=False)
    client     = Column(Text, server_default=text("''"))
    scope      = Column(Text, server_default=text("'full'"))
    created_at = Column(Text, nullable=False)
    last_used  = Column(Text)
    is_active  = Column(SmallInteger, server_default=text("1"))


# ─────────────────────────────────────────
# admin_passwords
# ─────────────────────────────────────────
class AdminPassword(Base):
    __tablename__ = 'admin_passwords'

    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    salt          = Column(Text, nullable=False)
    created_at    = Column(Text, nullable=False)
    updated_at    = Column(Text)


# ─────────────────────────────────────────
# user_credentials
# ─────────────────────────────────────────
class UserCredential(Base):
    __tablename__ = 'user_credentials'
    __table_args__ = (
        UniqueConstraint('username', 'user_type', name='uq_user_credentials_username_type'),
    )

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    username             = Column(Text, nullable=False)
    email                = Column(Text)
    password_hash        = Column(Text, nullable=False)
    salt                 = Column(Text, nullable=False)
    user_type            = Column(Text, nullable=False)
    parent_admin         = Column(Text)
    parent_trader        = Column(Text)
    is_active            = Column(SmallInteger, server_default=text("1"))
    must_change_password = Column(SmallInteger, server_default=text("1"))
    last_login           = Column(Text)
    created_at           = Column(Text, nullable=False)
    updated_at           = Column(Text)


# ─────────────────────────────────────────
# clients_data  (JSON columns stored as TEXT)
# ─────────────────────────────────────────
class ClientsData(Base):
    __tablename__ = 'clients_data'

    id               = Column(Integer, primary_key=True, autoincrement=True)
    client_id        = Column(Text, unique=True, nullable=False)
    deals            = Column(Text, server_default=text("'[]'"))
    positions        = Column(Text, server_default=text("'[]'"))
    account          = Column(Text, server_default=text("'{}'"))
    evaluations      = Column(Text, server_default=text("'[]'"))
    statistics       = Column(Text, server_default=text("'{}'"))
    dropdown_options = Column(Text, server_default=text("'{}'"))
    identity         = Column(Text, server_default=text("'{}'"))
    last_updated     = Column(Text, nullable=False)
    hedge_accounts   = Column(Text, server_default=text("'[]'"))
    prop_accounts    = Column(Text, server_default=text("'[]'"))
    vps_accounts     = Column(Text, server_default=text("'[]'"))
    payment_info     = Column(Text, server_default=text("'[]'"))
    payment_address  = Column(Text, server_default=text("'{}'"))


# ─────────────────────────────────────────
# audit_log
# ─────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = 'audit_log'

    id              = Column(Integer, primary_key=True, autoincrement=True)
    timestamp       = Column(Text, nullable=False)
    action          = Column(Text, nullable=False)
    user_type       = Column(Text, nullable=False)
    user_identifier = Column(Text, nullable=False)
    ip_address      = Column(Text)
    details         = Column(Text)
    success         = Column(SmallInteger, server_default=text("1"))


# ─────────────────────────────────────────
# data_history
# ─────────────────────────────────────────
class DataHistory(Base):
    __tablename__ = 'data_history'
    __table_args__ = (
        UniqueConstraint('client_id', 'version', name='uq_data_history_client_version'),
        Index('idx_data_history_client', 'client_id', 'version'),
    )

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    client_id          = Column(Text, nullable=False)
    version            = Column(Integer, nullable=False)
    action             = Column(Text, nullable=False)
    changed_by         = Column(Text)
    changed_by_type    = Column(Text)
    ip_address         = Column(Text)
    change_source      = Column(Text)
    change_description = Column(Text)
    deals              = Column(Text, server_default=text("'[]'"))
    positions          = Column(Text, server_default=text("'[]'"))
    account            = Column(Text, server_default=text("'{}'"))
    evaluations        = Column(Text, server_default=text("'[]'"))
    statistics         = Column(Text, server_default=text("'{}'"))
    dropdown_options   = Column(Text, server_default=text("'{}'"))
    identity           = Column(Text, server_default=text("'{}'"))
    created_at         = Column(Text, nullable=False)


# ─────────────────────────────────────────
# sessions
# ─────────────────────────────────────────
class Session(Base):
    __tablename__ = 'sessions'

    id              = Column(Integer, primary_key=True, autoincrement=True)
    session_token   = Column(Text, unique=True, nullable=False)
    user_type       = Column(Text, nullable=False)
    user_identifier = Column(Text, nullable=False)
    created_at      = Column(Text, nullable=False)
    expires_at      = Column(Text, nullable=False)
    ip_address      = Column(Text)


# ─────────────────────────────────────────
# cell_notes
# ─────────────────────────────────────────
class CellNote(Base):
    __tablename__ = 'cell_notes'
    __table_args__ = (
        UniqueConstraint('client_id', 'row_index', 'column_key', name='uq_cell_notes'),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    client_id    = Column(Text, nullable=False)
    row_index    = Column(Integer, nullable=False)
    column_key   = Column(Text, nullable=False)
    note_content = Column(Text)
    created_by   = Column(Text)
    updated_at   = Column(Text)


# ─────────────────────────────────────────
# daily_watermarks
# ─────────────────────────────────────────
class DailyWatermark(Base):
    __tablename__ = 'daily_watermarks'

    client_id           = Column(Text, primary_key=True, nullable=False)
    date                = Column(Text, primary_key=True, nullable=False)
    net_profit_complete = Column(Float, server_default=text("0.0"))
    source              = Column(Text, server_default=text("'auto'"))
    created_at          = Column(Text, server_default=func.now())


# ─────────────────────────────────────────
# waterlog_periods
# ─────────────────────────────────────────
class WaterlogPeriod(Base):
    __tablename__ = 'waterlog_periods'

    client_id   = Column(Text, primary_key=True, nullable=False)
    from_date   = Column(Text, primary_key=True, nullable=False)
    to_date     = Column(Text, nullable=False)
    period_low  = Column(Float)
    period_high = Column(Float)
    split_pct   = Column(Integer, server_default=text("50"))


# ─────────────────────────────────────────
# login_attempts
# ─────────────────────────────────────────
class LoginAttempt(Base):
    __tablename__ = 'login_attempts'

    id           = Column(Integer, primary_key=True, autoincrement=True)
    username     = Column(Text, nullable=False)
    user_type    = Column(Text, nullable=False)
    ip_address   = Column(Text)
    attempt_time = Column(Text, nullable=False)
    success      = Column(SmallInteger, server_default=text("0"))


# ─────────────────────────────────────────
# evaluations
# ─────────────────────────────────────────
class Evaluation(Base):
    __tablename__ = 'evaluations'

    id                = Column(Integer, primary_key=True, autoincrement=True)
    account_signature = Column(Text, nullable=False)
    phase_number      = Column(Integer, nullable=False)
    phase_type        = Column(Text, nullable=False)
    status            = Column(Text, server_default=text("'pending'"))
    start_date        = Column(Text)
    end_date          = Column(Text)
    reset_id          = Column(Text)
    parent_id         = Column(Integer, ForeignKey('evaluations.id'))
    meta_data         = Column(Text, server_default=text("'{}'"))
    created_at        = Column(Text, server_default=func.now())

    children = relationship('Evaluation', backref='parent', remote_side=[id])


# ─────────────────────────────────────────
# phase_definitions
# ─────────────────────────────────────────
class PhaseDefinition(Base):
    __tablename__ = 'phase_definitions'

    id             = Column(Integer, primary_key=True, autoincrement=True)
    phase_name     = Column(Text, nullable=False)
    phase_code     = Column(Text, unique=True, nullable=False)
    sequence_order = Column(Integer, nullable=False)
    ruleset        = Column(Text, server_default=text("'{}'"))
    next_phase_code = Column(Text)


# ─────────────────────────────────────────
# kyc_links
# ─────────────────────────────────────────
class KycLink(Base):
    __tablename__ = 'kyc_links'
    __table_args__ = (
        UniqueConstraint('primary_client', 'linked_client', name='uq_kyc_links'),
        Index('idx_kyc_primary', 'primary_client'),
        Index('idx_kyc_linked', 'linked_client'),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    primary_client = Column(Text, nullable=False)
    linked_client  = Column(Text, nullable=False)
    linked_by      = Column(Text, server_default=text("'super_admin'"))
    created_at     = Column(Text, server_default=func.now())


# ─────────────────────────────────────────
# quality_scan_results
# ─────────────────────────────────────────
class QualityScanResult(Base):
    __tablename__ = 'quality_scan_results'
    __table_args__ = (
        Index('idx_quality_scan_date', 'scan_date', 'client_id'),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    scan_date    = Column(Text, nullable=False)
    client_id    = Column(Text, nullable=False)
    trader       = Column(Text)
    admin        = Column(Text)
    total_issues = Column(Integer, server_default=text("0"))
    issues       = Column(Text, server_default=text("'[]'"))
    health_score = Column(Float, server_default=text("100.0"))
    created_at   = Column(Text, server_default=func.now())


# ─────────────────────────────────────────
# daily_checklists
# ─────────────────────────────────────────
class DailyChecklist(Base):
    __tablename__ = 'daily_checklists'
    __table_args__ = (
        UniqueConstraint('date', 'user_identifier', 'checklist_type', 'client_id',
                         name='uq_daily_checklists'),
        Index('idx_checklist_date', 'date', 'user_identifier'),
        Index('idx_checklist_client', 'date', 'client_id'),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    date            = Column(Text, nullable=False)
    user_identifier = Column(Text, nullable=False)
    user_type       = Column(Text, nullable=False)
    checklist_type  = Column(Text, nullable=False)
    client_id       = Column(Text, server_default=text("''"))
    items           = Column(Text, server_default=text("'[]'"))
    submitted_at    = Column(Text, nullable=False)
    ip_address      = Column(Text)


# ─────────────────────────────────────────
# system_settings
# ─────────────────────────────────────────
class SystemSetting(Base):
    __tablename__ = 'system_settings'

    key        = Column(Text, primary_key=True)
    value      = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    updated_by = Column(Text, server_default=text("''"))
