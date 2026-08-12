from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attendance import LeaveCreditAdjustment
from app.models.leave import LeaveApplication, LeavePolicy, LeavePolicyEntitlement, LeaveType

# Fallback leave types used only when a tenant has no leave_types rows at all
# (mirrors the system types seeded by migration 008).
DEFAULT_LEAVE_TYPES = [
    {"code": "annual_vacation", "name": "Annual Vacation"},
    {"code": "sick_leave", "name": "Sick Leave"},
    {"code": "personal_leave", "name": "Personal Leave"},
    {"code": "emergency_leave", "name": "Emergency Leave"},
    {"code": "bereavement_leave", "name": "Bereavement Leave"},
    {"code": "paternity_leave", "name": "Paternity Leave"},
    {"code": "maternity_leave", "name": "Maternity Leave"},
    {"code": "other", "name": "Other"},
]


@dataclass
class BalanceItem:
    leave_type: str
    leave_type_name: str
    total_days: float
    used_days: float
    pending_days: float

    @property
    def available_days(self) -> float:
        return self.total_days - self.used_days - self.pending_days


@dataclass
class BalanceSet:
    employee_id: int
    balances: list[BalanceItem] = field(default_factory=list)
    policy_name: Optional[str] = None
    accrual_method: Optional[str] = None
    pool_type: Optional[str] = None

    def for_type(self, leave_type: str) -> Optional[BalanceItem]:
        """Balance item for a leave type. For shared pools the single
        shared_pool item covers every type."""
        if self.pool_type == "shared":
            return self.balances[0] if self.balances else None
        for item in self.balances:
            if item.leave_type == leave_type:
                return item
        return None


class LeaveService:

    @staticmethod
    async def get_policy_for_employee(
        db: AsyncSession, tenant_id: UUID, employee_type: Optional[str]
    ) -> Optional[LeavePolicy]:
        """Find the matching leave policy for an employee based on their employment type.

        1. Find active policy where employment_types JSON contains employee_type
        2. Fallback to is_default=True policy
        3. Return None if no policy exists
        """
        if employee_type:
            stmt = (
                select(LeavePolicy)
                .options(selectinload(LeavePolicy.entitlements).selectinload(LeavePolicyEntitlement.leave_type))
                .where(
                    LeavePolicy.tenant_id == tenant_id,
                    LeavePolicy.is_active == True,
                    # employment_types is a plain JSON column, so cast to JSONB
                    # for containment (@>). A bare JSON .contains() emits LIKE.
                    cast(LeavePolicy.employment_types, JSONB).contains(
                        cast([employee_type], JSONB)
                    ),
                )
                .order_by(LeavePolicy.id)
                .limit(1)
            )
            result = await db.execute(stmt)
            policy = result.scalar_one_or_none()
            if policy:
                return policy

        # Fallback to default policy
        stmt = (
            select(LeavePolicy)
            .options(selectinload(LeavePolicy.entitlements).selectinload(LeavePolicyEntitlement.leave_type))
            .where(
                LeavePolicy.tenant_id == tenant_id,
                LeavePolicy.is_active == True,
                LeavePolicy.is_default == True,
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def compute_accrued_credits(
        annual_credits: float,
        accrual_method: str,
        *,
        year: Optional[int] = None,
        as_of: Optional[date] = None,
    ) -> float:
        """Credits accrued for `year` as of `as_of` (both default to today).

        annual: full credits from Jan 1.
        monthly: 1/12 per elapsed month; past years are fully accrued,
        future years have nothing accrued yet.
        """
        as_of = as_of or datetime.utcnow().date()
        year = year or as_of.year
        if accrual_method == "monthly":
            if year < as_of.year:
                months = 12
            elif year > as_of.year:
                months = 0
            else:
                months = as_of.month
            return round(annual_credits / 12 * months, 2)
        # Annual: full credits available for current and past years.
        if year > as_of.year:
            return 0.0
        return annual_credits

    @staticmethod
    async def compute_balances(
        db: AsyncSession,
        tenant_id: UUID,
        employee,
        *,
        year: Optional[int] = None,
        as_of: Optional[date] = None,
        default_days: float = 15,
    ) -> BalanceSet:
        """Compute an employee's leave balances for a calendar year.

        Sources: policy entitlements (accrual-prorated) + year-scoped credit
        adjustments − approved usage − pending usage. Falls back to the
        tenant's flat default_days per active leave type when no policy covers
        the employee.
        """
        as_of = as_of or datetime.utcnow().date()
        year = year or as_of.year
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)
        employee_id = employee.id

        async def _sum_applications(status: str) -> dict[str, float]:
            stmt = (
                select(
                    LeaveApplication.leave_type,
                    func.coalesce(func.sum(LeaveApplication.days_requested), 0).label("total"),
                )
                .where(
                    LeaveApplication.tenant_id == tenant_id,
                    LeaveApplication.employee_id == employee_id,
                    LeaveApplication.status == status,
                    LeaveApplication.start_date >= year_start,
                    LeaveApplication.end_date <= year_end,
                )
                .group_by(LeaveApplication.leave_type)
            )
            result = await db.execute(stmt)
            return {row.leave_type: float(row.total) for row in result.all()}

        used_map = await _sum_applications("approved")
        pending_map = await _sum_applications("pending")

        # Credit adjustments (OT conversions, tardiness deductions, manual,
        # carry-over, expiry, cash conversion) scoped to the requested year.
        adj_stmt = (
            select(
                LeaveCreditAdjustment.leave_type,
                func.coalesce(func.sum(LeaveCreditAdjustment.credits), 0).label("total"),
            )
            .where(
                LeaveCreditAdjustment.tenant_id == tenant_id,
                LeaveCreditAdjustment.employee_id == employee_id,
                LeaveCreditAdjustment.effective_date >= year_start,
                LeaveCreditAdjustment.effective_date <= year_end,
            )
            .group_by(LeaveCreditAdjustment.leave_type)
        )
        adj_result = await db.execute(adj_stmt)
        adj_map: dict[Optional[str], float] = {
            row.leave_type: float(row.total) for row in adj_result.all()
        }
        # Adjustments with no leave_type apply as a general pool: added to the
        # shared pool total, or to every type for per_type policies (existing
        # behavior, kept to avoid balance regressions).
        general_adj = adj_map.get(None, 0.0)

        policy = await LeaveService.get_policy_for_employee(
            db, tenant_id, getattr(employee, "employee_type", None)
        )

        if policy:
            balances: list[BalanceItem] = []
            if policy.pool_type == "per_type":
                for ent in policy.entitlements:
                    code = ent.leave_type.code
                    total = LeaveService.compute_accrued_credits(
                        ent.annual_credits, policy.accrual_method, year=year, as_of=as_of
                    )
                    total += adj_map.get(code, 0.0) + general_adj
                    balances.append(BalanceItem(
                        leave_type=code,
                        leave_type_name=ent.leave_type.name,
                        total_days=total,
                        used_days=used_map.get(code, 0.0),
                        pending_days=pending_map.get(code, 0.0),
                    ))
            else:
                total = LeaveService.compute_accrued_credits(
                    policy.shared_annual_credits or 0, policy.accrual_method,
                    year=year, as_of=as_of,
                )
                total += sum(adj_map.values())
                balances.append(BalanceItem(
                    leave_type="shared_pool",
                    leave_type_name="Shared Leave Pool",
                    total_days=total,
                    used_days=sum(used_map.values()),
                    pending_days=sum(pending_map.values()),
                ))

            return BalanceSet(
                employee_id=employee_id,
                balances=balances,
                policy_name=policy.name,
                accrual_method=policy.accrual_method,
                pool_type=policy.pool_type,
            )

        # No policy: flat default_days per active leave type.
        lt_result = await db.execute(
            select(LeaveType)
            .where(LeaveType.tenant_id == tenant_id, LeaveType.is_active == True)
            .order_by(LeaveType.sort_order)
        )
        leave_types = lt_result.scalars().all()

        type_list = (
            [{"code": lt.code, "name": lt.name} for lt in leave_types]
            if leave_types
            else DEFAULT_LEAVE_TYPES
        )
        balances = []
        for lt in type_list:
            code = lt["code"]
            total = float(default_days) + adj_map.get(code, 0.0) + general_adj
            balances.append(BalanceItem(
                leave_type=code,
                leave_type_name=lt["name"],
                total_days=total,
                used_days=used_map.get(code, 0.0),
                pending_days=pending_map.get(code, 0.0),
            ))
        return BalanceSet(employee_id=employee_id, balances=balances)
