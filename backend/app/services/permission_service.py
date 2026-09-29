from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.permission import RolePermission
from app.models.role import Role

VALID_MODULES = [
    "employees",
    "organization",
    "schedules",
    "leave",
    "finances",
    "settings",
    "reports",
]

# ── What each module controls ────────────────────────────────────────
#
# The Permissions screen is enforced by the API. Until 2026-09 it was only
# checked on attendance, policy rules, work sites and data export, while every
# other endpoint used a hard-coded role list, so an admin could untick a box and
# nothing changed. This is the contract every router follows:
#
#   Self-service is NEVER gated by the matrix. Your own profile, schedule, leave,
#   punches, attendance and payslips are always yours to see; the matrix governs
#   acting on OTHER people and on company configuration.
#
#   Scope is separate from permission. A permission says WHAT a role may do; the
#   scope (access_scope.managed_employee_ids) says to WHOM. Roles in
#   FULL_SCOPE_ROLES act on everyone; any other role acts only on the employees
#   in the org units they head or deputise, and their descendants.
#
# ── Administration is not operations (owner, 2026-09-29) ─────────────────
#
#   "A manager for graphics is not an administrator of the app." Running the
#   system and running the company's day are different jobs, done from
#   different dashboards (session_portal says which door a session came in by):
#
#   ADMINISTRATION  what tenant_admin is for, and all it is for. In an admin
#                   session tenant_admin passes every check on these modules
#                   without a matrix row:
#                     employees     accounts, roles, activation
#                     organization  the org chart
#                     settings      company settings, the permission matrix,
#                                   background jobs, backups, email, and the
#                                   Policies screens: holidays, shift status
#                                   types, schedule formats, policy rules,
#                                   work sites
#                   and, outside the matrix: leave CONFIGURATION (policies,
#                   types, approver rules; leave_config_allowed), approving
#                   salary-access requests when the admin is an approver, and
#                   the audit log.
#   OPERATIONS      schedules, leave REVIEW, finances, reports (analytics
#                   included). tenant_admin grants none of it, in any
#                   session: its matrix rows for these modules are never
#                   consulted (matrix_role_ids) and it is in none of their
#                   FULL_SCOPE_ROLES. They are done from the regular dashboard
#                   by people holding the role for the job (manager, hr,
#                   schedule_editor, leave_approver, report_viewer), and
#                   finances from the finance dashboard by finance. An
#                   administrator who also does one of these jobs holds that
#                   role too (they may give it to themselves from the admin
#                   dashboard, and every other administrator is told) and
#                   does the job signed in normally.
#
#   The finances module is in force only in a FINANCE session (the separate
#   finance sign-in). In the regular dashboard nobody manages payroll, whatever
#   rows their roles hold; the finance role itself is dormant there.
#
#   employees     view   list and read other employees' records
#                 create add, invite and import employees
#                 edit   edit other employees' profiles and roles
#                 delete separate (resign/terminate) and reinstate
#   organization  view   the Organization page and unit member lists
#                 create create org levels and units
#                 edit   rename/move units, set heads, deputies, members,
#                        visibility grants
#                 delete delete units and levels
#   schedules     view   other people's drafts, attendance, overtime and
#                        tardiness; actuals on the grid
#                 create create shifts (single, bulk, copy, templates)
#                 edit   edit/move shifts, publish, snapshots, review change
#                        requests, record attendance
#                 delete delete and clear shifts
#                 Holidays are company-wide configuration (Policies): an
#                 administrator changes them, and so does anyone holding the
#                 matching schedules action with full scope
#                 (FULL_SCOPE_ROLES["schedules"]); a team manager cannot change
#                 everyone's holiday pay.
#   leave         view   other employees' leave requests and balances; read
#                        the approver rules
#                 create file leave on someone else's behalf
#                 edit   leave policies, types, approver rules; override or
#                        reassign a stuck approval
#                 delete delete policies, types and approver rules
#                 Configuration (policies, types, approver rules) is also open
#                 to an administrator; review (reading others' requests,
#                 overriding, reassigning, revoking, filing for others) is
#                 not. tenant_admin's own leave row reads edit/delete: that is
#                 configuration and nothing more.
#                 Approving a request is governed by the approver chain, not
#                 the matrix: the resolved approver may always act on their
#                 step, from the regular dashboard.
#   finances      view   the STRUCTURE: deduction types and their bracket
#                        tables, payout schedules, salary grade names, the
#                        payroll period calendar (names, dates, status)
#                 create create periods, deduction types, payout schedules
#                 edit   edit that structure; compute payroll
#                 delete void and delete
#                 Only in a finance session (see above).
#                 FIGURES are not the matrix's to give. Grade rates, salaries,
#                 raises, bonuses and allowances, payroll results and totals,
#                 other people's payslips, overtime pay and lateness
#                 deductions need an active salary-VIEWER enrollment, which
#                 another person must approve (salary_enrollment_service).
#                 Nobody bypasses it: the owner's rule is that nobody sees
#                 what anyone earns unless someone else agrees. So anything
#                 that shows, produces or changes a figure (a grade's rate, a
#                 salary, a bonus, computing a run) needs the matrix action
#                 AND viewer.
#                 Approve and finalize a run: finances:edit plus viewer, and
#                 never by the person who computed that run (maker-checker),
#                 whatever their role. Recomputing makes the recomputer the
#                 preparer and clears any approval.
#   settings      view   read company settings, policies, work sites
#                 edit   change them (create/delete for the list-type ones)
#   reports       view   analytics dashboards
#                 create run, preview and download ad-hoc reports
#                 edit   save and edit reports and scheduled exports
#                 delete delete saved reports and schedules
#                 The report_viewer role ("Reports & data") holds view, create
#                 and edit and nothing else, so a CEO or anyone who needs the
#                 numbers can have them without HR's or Finance's powers.

ADMIN_ROLE = "tenant_admin"
ADMINISTRATION_MODULES = frozenset({"employees", "organization", "settings"})
OPERATIONAL_MODULES = frozenset({"schedules", "leave", "finances", "reports"})

# Operational roles an administrator may give themselves from the admin
# dashboard, so a one-person company is never locked out of its own schedules,
# leave or reports. Every such change is audited and told to every other
# administrator (employee_record_service.set_roles). finance too: salary
# figures still need another person's approval (salary-viewer enrollment).
SELF_ASSIGNABLE_ROLES = frozenset(
    {"manager", "hr", "schedule_editor", "leave_approver", "report_viewer", "finance"}
)

# Roles that act on every employee without an org-chart scope, per module.
# tenant_admin only in the administration modules (see above).
FULL_SCOPE_ROLES = {
    "employees": {"tenant_admin", "hr", "finance"},
    "organization": {"tenant_admin", "hr"},
    "schedules": {"hr", "schedule_editor"},
    "leave": {"hr"},
    "finances": {"finance"},
    "settings": {"tenant_admin", "hr", "finance"},
    "reports": {"hr", "finance", "report_viewer"},
}

# Default permission matrix: role_code -> {module: (can_view, can_create, can_edit, can_delete, extra)}
#
# These reproduce what each role could actually do before the matrix was
# enforced, so enforcing it changes nothing until an admin edits a box. Where
# the old hard-coded behaviour was itself a defect (e.g. any reviewer approving
# any request), the fix lives in the router, not in these defaults.
#
# `extra` used to carry {"view_salary": True} for admin, HR and Finance. Nothing
# ever enforced it, yet screens showed it as though it decided who sees pay;
# salary-viewer enrollment decides that. It is no longer seeded or shown.
# Rows that already hold the key keep it (the column is left alone); it is inert.
DEFAULT_PERMISSIONS = {
    # Administration only (see the contract). Its rows for the operational
    # modules are never read; they are stored as below so the Permissions
    # screen shows what is true. leave edit/delete = configuring leave.
    "tenant_admin": {
        "employees": (True, True, True, True, {}),
        "organization": (True, True, True, True, {}),
        "schedules": (False, False, False, False, {}),
        "leave": (False, False, True, True, {}),
        "finances": (False, False, False, False, {}),
        "settings": (True, True, True, True, {}),
        "reports": (False, False, False, False, {}),
    },
    "hr": {
        "employees": (True, True, True, False, {}),
        "organization": (True, True, True, False, {}),
        "schedules": (True, True, True, True, {}),
        "leave": (True, True, True, True, {}),
        "finances": (True, False, False, False, {}),
        "settings": (True, False, False, False, {}),
        "reports": (True, True, True, False, {}),
    },
    "finance": {
        "employees": (True, False, False, False, {}),
        "organization": (True, False, False, False, {}),
        "schedules": (False, False, False, False, {}),
        "leave": (True, False, False, False, {}),
        "finances": (True, True, True, True, {}),
        "settings": (True, False, False, False, {}),
        "reports": (True, True, True, False, {}),
    },
    "manager": {
        "employees": (True, False, False, False, {}),
        "organization": (True, False, False, False, {}),
        "schedules": (True, True, True, True, {}),
        "leave": (True, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (True, False, False, False, {}),
    },
    "schedule_editor": {
        "employees": (True, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (True, True, True, True, {}),
        "leave": (True, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (False, False, False, False, {}),
    },
    "leave_approver": {
        "employees": (True, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (True, False, False, False, {}),
        "leave": (True, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (False, False, False, False, {}),
    },
    # "Reports & data": run and save reports and read the analytics, for
    # whoever needs the numbers (a CEO, an analyst) without HR's or Finance's
    # powers. Company-wide (FULL_SCOPE_ROLES["reports"]).
    "report_viewer": {
        "employees": (False, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (False, False, False, False, {}),
        "leave": (False, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (True, True, True, False, {}),
    },
    "employee": {
        "employees": (False, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (False, False, False, False, {}),
        "leave": (False, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (False, False, False, False, {}),
    },
}


def admin_bypasses(user, module: str) -> bool:
    """tenant_admin in force (an admin session) passes every administration
    check without a matrix row, and nothing else."""
    return module in ADMINISTRATION_MODULES and user.has_role(ADMIN_ROLE)


def matrix_role_ids(user, module: str) -> List[int]:
    """The ids of the user's roles whose rows count for `module` in this
    request. THE rule behind every matrix check (require_permission,
    PermissionService.user_can, /permissions/me):

      * roles dormant in this session never count (User.role_ids);
      * tenant_admin's rows never count for an operational module, whatever
        they hold, so an administrator cannot be given operations by ticking
        a box on its locked row or by an old install's stored defaults;
      * finances counts only in a finance session. `portal` is None on a
        User that is not the request's (a background job acting as an
        owner), which answers from the stored roles as before.
    """
    if module == "finances" and getattr(user, "portal", None) not in (None, "finance"):
        return []
    if module in OPERATIONAL_MODULES:
        return user.role_ids_excluding(ADMIN_ROLE)
    return user.role_ids


def leave_config_allowed_sync(user) -> bool:
    """The administration half of leave configuration (no matrix read)."""
    return user.has_role(ADMIN_ROLE)


class PermissionService:
    @staticmethod
    async def user_can(db: AsyncSession, user, module: str, action: str) -> bool:
        """May `user` (as this request sees them) do module:action? Every
        handler-level check goes through here, so the administration bypass
        and the operational split are decided in one place."""
        if admin_bypasses(user, module):
            return True
        return await PermissionService.check_permission(
            db, user.tenant_id, matrix_role_ids(user, module), module, action
        )

    @staticmethod
    async def leave_config_allowed(db: AsyncSession, user, action: str) -> bool:
        """Leave policies, types and approver rules: an administrator (admin
        session) or anyone holding leave:<action> (HR by default). Reviewing
        leave is NOT this; see leave_access."""
        if leave_config_allowed_sync(user):
            return True
        return await PermissionService.user_can(db, user, "leave", action)

    @staticmethod
    async def user_permissions(db: AsyncSession, user) -> Dict[str, Any]:
        """/permissions/me: what this session may do, module by module,
        answered by the same rules as user_can."""
        merged: Dict[str, Dict[str, bool]] = {}
        extra: Dict[str, bool] = {}
        for module in VALID_MODULES:
            if admin_bypasses(user, module):
                merged[module] = {"view": True, "create": True, "edit": True, "delete": True}
                continue
            got = await PermissionService.get_user_permissions(
                db, user.tenant_id, matrix_role_ids(user, module)
            )
            merged[module] = got["permissions"].get(
                module, {"view": False, "create": False, "edit": False, "delete": False}
            )
            for k, v in got["extra"].items():
                extra[k] = extra.get(k, False) or v
        if leave_config_allowed_sync(user):
            # Configuration only: the Policies screens read edit/delete. The
            # leave REVIEW screens are not in the admin dashboard.
            merged["leave"] = {**merged["leave"], "edit": True, "delete": True}
        return {"permissions": merged, "extra": extra}

    @staticmethod
    async def seed_default_permissions(db: AsyncSession, tenant_id: UUID) -> None:
        """Idempotently seed default permissions for all system roles in a tenant."""
        stmt = select(Role).where(Role.tenant_id == tenant_id, Role.is_system == True)
        result = await db.execute(stmt)
        roles = list(result.scalars().all())

        for role in roles:
            perms = DEFAULT_PERMISSIONS.get(role.code, {})
            for module, (v, c, e, d, extra) in perms.items():
                existing = await db.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.module == module,
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                db.add(RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    module=module,
                    can_view=v,
                    can_create=c,
                    can_edit=e,
                    can_delete=d,
                    extra_permissions=extra or {},
                ))
        await db.flush()

    @staticmethod
    async def get_permission_matrix(db: AsyncSession, tenant_id: UUID) -> List[Dict[str, Any]]:
        """Get all roles with their module permissions for the tenant."""
        stmt = (
            select(Role)
            .where(Role.tenant_id == tenant_id, Role.is_active == True, Role.is_system == True)
            .order_by(Role.code)
        )
        result = await db.execute(stmt)
        roles = list(result.scalars().all())

        entries = []
        for role in roles:
            perm_stmt = select(RolePermission).where(RolePermission.role_id == role.id)
            perm_result = await db.execute(perm_stmt)
            perms = list(perm_result.scalars().all())

            modules = {}
            for p in perms:
                modules[p.module] = p

            entries.append({
                "role_id": role.id,
                "role_code": role.code,
                "role_name": role.name,
                "modules": modules,
            })

        return entries

    @staticmethod
    async def get_role_permissions(db: AsyncSession, role_id: int) -> List[RolePermission]:
        stmt = select(RolePermission).where(RolePermission.role_id == role_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_role_permissions(
        db: AsyncSession,
        tenant_id: UUID,
        role_id: int,
        permissions: List[Dict[str, Any]],
    ) -> List[RolePermission]:
        """Upsert permissions for a role. permissions is a list of dicts with module, can_view, etc."""
        updated = []
        for perm_data in permissions:
            module = perm_data["module"]
            if module not in VALID_MODULES:
                continue

            stmt = select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.module == module,
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.can_view = perm_data.get("can_view", existing.can_view)
                existing.can_create = perm_data.get("can_create", existing.can_create)
                existing.can_edit = perm_data.get("can_edit", existing.can_edit)
                existing.can_delete = perm_data.get("can_delete", existing.can_delete)
                if "extra_permissions" in perm_data and perm_data["extra_permissions"] is not None:
                    existing.extra_permissions = perm_data["extra_permissions"]
                updated.append(existing)
            else:
                rp = RolePermission(
                    tenant_id=tenant_id,
                    role_id=role_id,
                    module=module,
                    can_view=perm_data.get("can_view", False),
                    can_create=perm_data.get("can_create", False),
                    can_edit=perm_data.get("can_edit", False),
                    can_delete=perm_data.get("can_delete", False),
                    extra_permissions=perm_data.get("extra_permissions", {}),
                )
                db.add(rp)
                await db.flush()
                updated.append(rp)

        await db.flush()
        return updated

    @staticmethod
    async def get_user_permissions(db: AsyncSession, tenant_id: UUID, role_ids: List[int]) -> Dict[str, Any]:
        """
        Get merged permissions across all of a user's roles.
        Returns {permissions: {module: {view: bool, ...}}, extra: {key: bool, ...}}
        """
        if not role_ids:
            return {"permissions": {}, "extra": {}}

        stmt = select(RolePermission).where(RolePermission.role_id.in_(list(role_ids)))
        result = await db.execute(stmt)
        all_perms = list(result.scalars().all())

        # OR-merge across roles per module
        merged: Dict[str, Dict[str, bool]] = {}
        extra_merged: Dict[str, bool] = {}

        for p in all_perms:
            if p.module not in merged:
                merged[p.module] = {"view": False, "create": False, "edit": False, "delete": False}
            merged[p.module]["view"] = merged[p.module]["view"] or p.can_view
            merged[p.module]["create"] = merged[p.module]["create"] or p.can_create
            merged[p.module]["edit"] = merged[p.module]["edit"] or p.can_edit
            merged[p.module]["delete"] = merged[p.module]["delete"] or p.can_delete

            # Merge extra permissions
            if p.extra_permissions:
                for key, val in p.extra_permissions.items():
                    if isinstance(val, bool):
                        extra_merged[key] = extra_merged.get(key, False) or val

        return {"permissions": merged, "extra": extra_merged}

    @staticmethod
    async def check_permission(
        db: AsyncSession,
        tenant_id: UUID,
        role_ids: List[int],
        module: str,
        action: str,
    ) -> bool:
        """Check if any of the given roles has the specified module+action permission."""
        if not role_ids:
            return False

        action_col = {
            "view": RolePermission.can_view,
            "create": RolePermission.can_create,
            "edit": RolePermission.can_edit,
            "delete": RolePermission.can_delete,
        }.get(action)

        if action_col is None:
            return False

        # limit(1)/first(): a user holding two roles that both grant the action
        # (e.g. hr + manager, both employees:view) matches two rows, and
        # scalar_one_or_none() raised MultipleResultsFound -> a 500 on every
        # request that checked the permission.
        stmt = select(RolePermission.id).where(
            RolePermission.role_id.in_(role_ids),
            RolePermission.module == module,
            action_col == True,
        ).limit(1)
        result = await db.execute(stmt)
        return result.scalars().first() is not None

    @staticmethod
    async def check_extra_permission(
        db: AsyncSession,
        tenant_id: UUID,
        role_ids: List[int],
        permission_key: str,
    ) -> bool:
        """Check if any of the given roles has a specific extra permission."""
        if not role_ids:
            return False

        stmt = select(RolePermission).where(RolePermission.role_id.in_(role_ids))
        result = await db.execute(stmt)
        all_perms = list(result.scalars().all())

        for p in all_perms:
            if p.extra_permissions and p.extra_permissions.get(permission_key) is True:
                return True
        return False
