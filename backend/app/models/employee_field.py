"""Company-defined employee profile fields.

Every company has something the product does not: a union number, a locker,
a badge code, "the XXXX employee code". Before 2026-09 the only answer was to
overload Personnel # or keep a spreadsheet. A definition says what the field is
and who may see or change it; a value is one employee's entry.
"""


from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.timeutil import utcnow

FIELD_TYPES = ("text", "number", "date", "select", "boolean")

# Who may see a value, from narrowest to widest. Anyone who may see it and may
# edit the employee may change it; only employee_edit lets the employee change
# their own.
#   hr_only        people who edit employee records company-wide (admin, HR)
#   managers       + anyone who may read this employee's record (their managers,
#                  finance)
#   employee_view  + the employee, read-only
#   employee_edit  + the employee, who may also change it
VISIBILITIES = ("hr_only", "managers", "employee_view", "employee_edit")


class EmployeeFieldDefinition(Base):
    __tablename__ = "employee_field_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_employee_field_def_tenant_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # Stable machine name, used as the CSV column and the API key. Never
    # changes after creation, so imports and saved reports keep working when
    # the label is renamed.
    key = Column(String(50), nullable=False)
    label = Column(String(100), nullable=False)
    field_type = Column(String(20), nullable=False, default="text")
    options = Column(JSONB, nullable=True)  # list[str] for select
    is_required = Column(Boolean, nullable=False, default=False)
    is_unique = Column(Boolean, nullable=False, default=False)
    regex = Column(String(200), nullable=True)
    visibility = Column(String(20), nullable=False, default="hr_only")
    # Sensitive values never appear in lists, table columns, search or
    # reports for anyone below HR level; they are shown on the record only.
    is_sensitive = Column(Boolean, nullable=False, default=False)
    help_text = Column(String(300), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_archived = Column(Boolean, nullable=False, default=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    values = relationship("EmployeeFieldValue", back_populates="field", cascade="all, delete-orphan")


class EmployeeFieldValue(Base):
    __tablename__ = "employee_field_values"
    __table_args__ = (
        UniqueConstraint("field_id", "user_id", name="uq_employee_field_value_field_user"),
        # Uniqueness of values for fields marked unique.
        #
        # A partial index cannot look at another table, so "WHERE the
        # definition is unique" is expressed through `is_unique`, a copy of the
        # definition's flag kept on every value row. The index then makes the
        # database, not the application, the arbiter: two requests saving the
        # same code at the same moment cannot both commit, whatever the
        # isolation level, because the second insert blocks on the first's
        # index entry and fails when it commits.
        #
        # The copy stays truthful because the two writers serialize on the
        # definition row: saving a value reads the definition FOR SHARE, and
        # turning uniqueness on or off updates it FOR UPDATE and rewrites every
        # value's flag in the same transaction. A value saved while the flag
        # flips therefore either sees the new flag or waits for it; turning
        # uniqueness on over existing duplicates fails on this very index.
        Index(
            "uq_employee_field_value_unique",
            "field_id",
            "value_norm",
            unique=True,
            postgresql_where=text("is_unique AND value_norm IS NOT NULL"),
            sqlite_where=text("is_unique AND value_norm IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    field_id = Column(Integer, ForeignKey("employee_field_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # As entered, canonicalised for its type (ISO dates, plain numbers,
    # "true"/"false"). What the API returns.
    value_text = Column(Text, nullable=True)
    # Trimmed and lowercased for text and select, so "AB-12" and " ab-12"
    # are the same code for uniqueness and search.
    value_norm = Column(String(500), nullable=True)
    is_unique = Column(Boolean, nullable=False, default=False)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    field = relationship("EmployeeFieldDefinition", back_populates="values")
