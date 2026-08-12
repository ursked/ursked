from collections import deque
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.role import UserRole, Role
from app.models.user import User


class HierarchyService:
    MAX_DEPTH = 20  # Safety limit for recursive traversal

    @staticmethod
    async def get_direct_reports(db: AsyncSession, user_id: int, tenant_id: UUID) -> List[User]:
        """Get users who directly report to the given user."""
        stmt = (
            select(User)
            .where(User.reports_to_id == user_id, User.tenant_id == tenant_id, User.is_active == True)
            .order_by(User.last_name, User.first_name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_all_subordinates(db: AsyncSession, user_id: int, tenant_id: UUID) -> List[User]:
        """Get all subordinates (direct + indirect) via BFS with depth limit."""
        subordinates = []
        queue = deque([user_id])
        visited = {user_id}
        depth = 0

        while queue and depth < HierarchyService.MAX_DEPTH:
            level_size = len(queue)
            for _ in range(level_size):
                current_id = queue.popleft()
                reports = await HierarchyService.get_direct_reports(db, current_id, tenant_id)
                for report in reports:
                    if report.id not in visited:
                        visited.add(report.id)
                        subordinates.append(report)
                        queue.append(report.id)
            depth += 1

        return subordinates

    @staticmethod
    async def get_approval_chain(db: AsyncSession, user_id: int, tenant_id: UUID) -> List[User]:
        """Walk up the reports_to chain, collecting users with the leave_approver role."""
        chain = []
        current_id = user_id
        visited = set()
        depth = 0

        while depth < HierarchyService.MAX_DEPTH:
            stmt = (
                select(User)
                .options(selectinload(User.user_roles).selectinload(UserRole.role))
                .where(User.id == current_id, User.tenant_id == tenant_id)
            )
            result = await db.execute(stmt)
            current_user = result.scalar_one_or_none()

            if not current_user or not current_user.reports_to_id:
                break

            next_id = current_user.reports_to_id
            if next_id in visited:
                break  # Circular reference detected
            visited.add(next_id)

            # Load the manager
            mgr_stmt = (
                select(User)
                .options(selectinload(User.user_roles).selectinload(UserRole.role))
                .where(User.id == next_id, User.tenant_id == tenant_id)
            )
            mgr_result = await db.execute(mgr_stmt)
            manager = mgr_result.scalar_one_or_none()

            if not manager:
                break

            if manager.has_role("leave_approver"):
                chain.append(manager)

            current_id = next_id
            depth += 1

        return chain

    @staticmethod
    async def is_manager_of(db: AsyncSession, manager_id: int, employee_id: int, tenant_id: UUID) -> bool:
        """Check if manager_id is a direct or indirect manager of employee_id."""
        current_id = employee_id
        visited = set()
        depth = 0

        while depth < HierarchyService.MAX_DEPTH:
            stmt = select(User.reports_to_id).where(User.id == current_id, User.tenant_id == tenant_id)
            result = await db.execute(stmt)
            reports_to = result.scalar_one_or_none()

            if reports_to is None:
                return False
            if reports_to == manager_id:
                return True
            if reports_to in visited:
                return False  # Circular reference

            visited.add(reports_to)
            current_id = reports_to
            depth += 1

        return False

    @staticmethod
    async def validate_reports_to(
        db: AsyncSession, user_id: int, new_reports_to_id: int, tenant_id: UUID
    ) -> bool:
        """Validate that setting reports_to won't create a circular reference.
        Returns True if valid (no cycle), False if it would create a cycle."""
        if user_id == new_reports_to_id:
            return False

        # Check if new_reports_to_id is a subordinate of user_id
        current_id = new_reports_to_id
        visited = {user_id}
        depth = 0

        while depth < HierarchyService.MAX_DEPTH:
            stmt = select(User.reports_to_id).where(User.id == current_id, User.tenant_id == tenant_id)
            result = await db.execute(stmt)
            reports_to = result.scalar_one_or_none()

            if reports_to is None:
                return True  # Reached top of chain without finding user_id
            if reports_to in visited:
                return False  # Would create a cycle

            visited.add(reports_to)
            current_id = reports_to
            depth += 1

        return True
