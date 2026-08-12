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
    ) -> list[RuleResult]:
        """Evaluate filing rules. Returns violations only (passing rules and
        rules in "off" mode produce nothing). `rules` limits evaluation to a
        subset (used by the approval-time balance re-check)."""
        today = today or date.today()
        policy = await LeaveService.get_policy_for_employee(
            db, tenant_id, getattr(employee, "employee_type", None)
        )
        if policy is None:
            return []

        def wanted(rule: str) -> bool:
            return (rules is None or rule in rules) and _mode(policy, rule) != "off"

        # Entitlement thresholds for this leave type (per_type pools only)
        entitlement = None
        if policy.pool_type == "per_type":
            for ent in policy.entitlements:
                if ent.leave_type.code == leave_type:
                    entitlement = ent
                    break

        violations: list[RuleResult] = []

        if wanted(RULE_INSUFFICIENT_BALANCE):
            balance_set = await LeaveService.compute_balances(
                db, tenant_id, employee, year=start_date.year
            )
            item = balance_set.for_type(leave_type)
            available = item.available_days if item else 0.0
            if days_requested > available:
                violations.append(RuleResult(
                    rule=RULE_INSUFFICIENT_BALANCE,
                    mode=_mode(policy, RULE_INSUFFICIENT_BALANCE),
                    message=(
                        f"Requested {days_requested:g} day(s) but only "
                        f"{available:g} available."
                    ),
                    details={
                        "requested": days_requested,
                        "available": available,
                        "deficit": round(days_requested - available, 2),
                    },
                ))

        if wanted(RULE_MIN_NOTICE):
            min_notice = entitlement.min_notice_days if entitlement else 0
            if min_notice and min_notice > 0:
                notice_given = (start_date - today).days
                if notice_given < min_notice:
                    violations.append(RuleResult(
                        rule=RULE_MIN_NOTICE,
                        mode=_mode(policy, RULE_MIN_NOTICE),
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
            if policy.pool_type == "shared":
                max_consecutive = policy.shared_max_consecutive_days
            else:
                max_consecutive = entitlement.max_consecutive_days if entitlement else None
            if max_consecutive and days_requested > max_consecutive:
                violations.append(RuleResult(
                    rule=RULE_MAX_CONSECUTIVE,
                    mode=_mode(policy, RULE_MAX_CONSECUTIVE),
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
                violations.append(RuleResult(
                    rule=RULE_OVERLAP,
                    mode=_mode(policy, RULE_OVERLAP),
                    message=(
                        f"Overlaps {len(overlaps)} existing leave "
                        f"request(s) in the same date range."
                    ),
                    details={"overlapping": overlaps},
                ))

        if wanted(RULE_DOCUMENTATION):
            needs_docs = bool(entitlement and entitlement.requires_documentation)
            if needs_docs and not supporting_documents:
                violations.append(RuleResult(
                    rule=RULE_DOCUMENTATION,
                    mode=_mode(policy, RULE_DOCUMENTATION),
                    message="This leave type requires a supporting document.",
                    details={"leave_type": leave_type},
                ))

        return violations

    @staticmethod
    def split(violations: list[RuleResult]) -> tuple[list[RuleResult], list[RuleResult]]:
        """Partition violations into (blocking, warnings)."""
        blocking = [v for v in violations if v.mode == "block"]
        warnings = [v for v in violations if v.mode == "warn"]
        return blocking, warnings
