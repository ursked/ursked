"""Policy-driven leave filing rules.

Each rule has a per-policy mode configured in LeavePolicy.enforcement:
    "block" — filing is rejected with a 422 and structured violations
    "warn"  — filing succeeds; violations are stored on the application and
              surfaced to approvers
    "off"   — rule is not evaluated (default for missing keys)

Rules:
    insufficient_balance    requested days exceed available balance
    min_notice_days         filed later than the required advance notice
    max_consecutive_days    request spans more days than allowed at once
    overlapping_application another pending/approved request intersects range
    requires_documentation  leave type needs a supporting document, none given

Advisory warnings (2026-09): the seeded policy has every rule "off", so an
overlapping request or one that overdraws the balance was accepted without a
word to the employee. The defaults stay as they are (a company may genuinely
allow negative balances), but when `advisory=True` those two rules are still
checked in "off" mode and reported as warnings, so the employee sees them
before submitting and the approver sees them on the request.
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leave import LeaveApplication, LeavePolicy
from app.services.leave_service import LeaveService

MODES = ("block", "warn", "off")

RULE_INSUFFICIENT_BALANCE = "insufficient_balance"
RULE_MIN_NOTICE = "min_notice_days"
RULE_MAX_CONSECUTIVE = "max_consecutive_days"
RULE_OVERLAP = "overlapping_application"
RULE_DOCUMENTATION = "requires_documentation"

# Checked even when "off" if the caller asks for advisory warnings.
ADVISORY_RULES = {RULE_INSUFFICIENT_BALANCE, RULE_OVERLAP}


@dataclass
class RuleResult:
    rule: str
    mode: str  # "block" | "warn"
    message: str
    details: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _mode(policy: Optional[LeavePolicy], rule: str) -> str:
    if policy is None:
        return "off"
    enforcement = policy.enforcement or {}
    mode = enforcement.get(rule, "off")
    return mode if mode in MODES else "off"


def violations_message(violations: list) -> str:
    """One readable sentence for a list of blocking violations.

    The API used to return the raw violation list as the error detail, and the
    client printed it as JSON. The message is what a person reads; the list
    stays alongside it for the form to render as bullet points.
    """
    msgs = [v.message if isinstance(v, RuleResult) else v.get("message", "") for v in violations]
    msgs = [m for m in msgs if m]
    if not msgs:
        return "This request breaks the leave policy."
    if len(msgs) == 1:
        return f"This request cannot be filed: {msgs[0]}"
    return "This request cannot be filed: " + " ".join(msgs)


class LeaveRuleService:

    @staticmethod
    async def evaluate(
        db: AsyncSession,
        tenant_id: UUID,
        employee,
        *,
        leave_type: str,
        start_date: date,
        end_date: date,
        days_requested: float,
        supporting_documents: Optional[list] = None,
        exclude_application_id: Optional[int] = None,
        today: Optional[date] = None,
        rules: Optional[set[str]] = None,
        day_breakdown: Optional[list] = None,
        advisory: bool = False,
        default_days: float = 15,
    ) -> list[RuleResult]:
        """Evaluate filing rules. Returns violations only (passing rules and
        rules in "off" mode produce nothing). `rules` limits evaluation to a
        subset (used by the approval-time balance re-check). `day_breakdown`
        (from leave_days_service) lets a request that spans New Year be checked
        against each year's balance separately."""
        today = today or date.today()
        policy = await LeaveService.get_policy_for_employee(
            db, tenant_id, getattr(employee, "employee_type", None)
        )
        if policy is None and not advisory:
            return []

        def mode_of(rule: str) -> str:
            m = _mode(policy, rule)
            if m == "off" and advisory and rule in ADVISORY_RULES:
                return "warn"
            return m

        def wanted(rule: str) -> bool:
            return (rules is None or rule in rules) and mode_of(rule) != "off"

        # Entitlement thresholds for this leave type (per_type pools only)
        entitlement = None
        if policy is not None and policy.pool_type == "per_type":
            for ent in policy.entitlements:
                if ent.leave_type.code == leave_type:
                    entitlement = ent
                    break

        violations: list[RuleResult] = []

        if wanted(RULE_INSUFFICIENT_BALANCE):
            from app.services.leave_days_service import days_by_year

            per_year = days_by_year(day_breakdown) if day_breakdown else {}
            if len(per_year) <= 1:
                per_year = {start_date.year: days_requested}
            spans = len(per_year) > 1
            for yr, wanted_days in sorted(per_year.items()):
                if wanted_days <= 0:
                    continue
                balance_set = await LeaveService.compute_balances(
                    db, tenant_id, employee, year=yr, default_days=default_days
                )
                item = balance_set.for_type(leave_type)
                available = item.available_days if item else 0.0
                if exclude_application_id is not None:
                    # The request being re-checked is itself counted as pending
                    # or approved in that balance; do not charge it twice.
                    available += await LeaveRuleService._own_days(
                        db, exclude_application_id, yr
                    )
                if wanted_days > available + 1e-9:
                    shown = max(available, 0)
                    violations.append(RuleResult(
                        rule=RULE_INSUFFICIENT_BALANCE,
                        mode=mode_of(RULE_INSUFFICIENT_BALANCE),
                        message=(
                            f"This request needs {wanted_days:g} day(s)"
                            + (f" in {yr}" if spans else "")
                            + f" but only {shown:g} "
                            + ("is" if shown == 1 else "are")
                            + " available."
                        ),
                        details={
                            "year": yr,
                            "requested": wanted_days,
                            "available": available,
                            "deficit": round(wanted_days - available, 2),
                        },
                    ))

        if wanted(RULE_MIN_NOTICE):
            min_notice = entitlement.min_notice_days if entitlement else 0
            if min_notice and min_notice > 0:
                notice_given = (start_date - today).days
                if notice_given < min_notice:
                    violations.append(RuleResult(
                        rule=RULE_MIN_NOTICE,
                        mode=mode_of(RULE_MIN_NOTICE),
                        message=(
                            f"Requires {min_notice} day(s) advance notice; "
                            f"filed {max(notice_given, 0)} day(s) ahead."
                        ),
                        details={
                            "required_notice_days": min_notice,
                            "notice_given_days": notice_given,
                        },
                    ))

        if wanted(RULE_MAX_CONSECUTIVE):
            if policy is None:
                max_consecutive = None
            elif policy.pool_type == "shared":
                max_consecutive = policy.shared_max_consecutive_days
            else:
                max_consecutive = entitlement.max_consecutive_days if entitlement else None
            if max_consecutive and days_requested > max_consecutive:
                violations.append(RuleResult(
                    rule=RULE_MAX_CONSECUTIVE,
                    mode=mode_of(RULE_MAX_CONSECUTIVE),
                    message=(
                        f"Requested {days_requested:g} consecutive day(s); "
                        f"the maximum per request is {max_consecutive:g}."
                    ),
                    details={
                        "requested": days_requested,
                        "max_consecutive_days": max_consecutive,
                    },
                ))

        if wanted(RULE_OVERLAP):
            stmt = select(LeaveApplication.id, LeaveApplication.start_date,
                          LeaveApplication.end_date, LeaveApplication.status).where(
                LeaveApplication.tenant_id == tenant_id,
                LeaveApplication.employee_id == employee.id,
                LeaveApplication.status.in_(["pending", "approved"]),
                LeaveApplication.start_date <= end_date,
                LeaveApplication.end_date >= start_date,
            )
            if exclude_application_id is not None:
                stmt = stmt.where(LeaveApplication.id != exclude_application_id)
            result = await db.execute(stmt.limit(5))
            overlaps = [
                {
                    "application_id": row.id,
                    "start_date": str(row.start_date),
                    "end_date": str(row.end_date),
                    "status": row.status,
                }
                for row in result.all()
            ]
            if overlaps:
                ranges = ", ".join(
                    f"{o['start_date']} to {o['end_date']} ({o['status']})" for o in overlaps
                )
                violations.append(RuleResult(
                    rule=RULE_OVERLAP,
                    mode=mode_of(RULE_OVERLAP),
                    message=f"These dates overlap other leave already filed: {ranges}.",
                    details={"overlapping": overlaps},
                ))

        if wanted(RULE_DOCUMENTATION):
            needs_docs = bool(entitlement and entitlement.requires_documentation)
            if needs_docs and not supporting_documents:
                violations.append(RuleResult(
                    rule=RULE_DOCUMENTATION,
                    mode=mode_of(RULE_DOCUMENTATION),
                    message="This leave type requires a supporting document.",
                    details={"leave_type": leave_type},
                ))

        return violations

    @staticmethod
    async def _own_days(db: AsyncSession, application_id: int, year: int) -> float:
        from app.services.leave_days_service import application_days_in_year

        app = await db.get(LeaveApplication, application_id)
        if app is None or app.status not in ("pending", "approved"):
            return 0.0
        return application_days_in_year(app, year)

    @staticmethod
    def split(violations: list[RuleResult]) -> tuple[list[RuleResult], list[RuleResult]]:
        """Partition violations into (blocking, warnings)."""
        blocking = [v for v in violations if v.mode == "block"]
        warnings = [v for v in violations if v.mode == "warn"]
        return blocking, warnings
