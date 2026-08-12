from datetime import date
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.configurable_types import UserOrgNode
from app.models.leave import LeaveApplication
from app.models.org_hierarchy import OrgLevel, OrgNode
from app.models.user import User


class OrgService:

    # ── Level Operations ─────────────────────────────────────────────

    @staticmethod
    async def get_levels(db: AsyncSession, tenant_id: UUID) -> List[OrgLevel]:
        stmt = (
            select(OrgLevel)
            .where(OrgLevel.tenant_id == tenant_id)
            .order_by(OrgLevel.level_number)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def set_levels(
        db: AsyncSession, tenant_id: UUID, levels: List[dict]
    ) -> List[OrgLevel]:
        """Replace all levels atomically. Validates no nodes exist at removed levels."""
        existing = await OrgService.get_levels(db, tenant_id)
        existing_map: Dict[int, OrgLevel] = {l.level_number: l for l in existing}
        new_numbers = {l["level_number"] for l in levels}

        # Check if any removed levels have nodes
        for lvl in existing:
            if lvl.level_number not in new_numbers:
                count_stmt = (
                    select(func.count())
                    .select_from(OrgNode)
                    .where(OrgNode.level_id == lvl.id)
                )
                count_result = await db.execute(count_stmt)
                if count_result.scalar() > 0:
                    raise ValueError(
                        f"Cannot remove level {lvl.level_number} ({lvl.name}) "
                        f"because it has existing nodes"
                    )

        # Delete removed levels
        for lvl in existing:
            if lvl.level_number not in new_numbers:
                await db.delete(lvl)

        # Upsert remaining
        result_levels = []
        for item in sorted(levels, key=lambda x: x["level_number"]):
            num = item["level_number"]
            if num in existing_map:
                existing_map[num].name = item["name"]
                result_levels.append(existing_map[num])
            else:
                new_level = OrgLevel(
                    tenant_id=tenant_id,
                    level_number=num,
                    name=item["name"],
                )
                db.add(new_level)
                result_levels.append(new_level)

        await db.flush()
        for lvl in result_levels:
            await db.refresh(lvl)
        return result_levels

    # ── Node CRUD ────────────────────────────────────────────────────

    @staticmethod
    async def get_node_by_id(
        db: AsyncSession, node_id: int, tenant_id: UUID
    ) -> Optional[OrgNode]:
        stmt = (
            select(OrgNode)
            .options(
                selectinload(OrgNode.level),
                selectinload(OrgNode.head_user),
                selectinload(OrgNode.deputy_head_user),
            )
            .where(OrgNode.id == node_id, OrgNode.tenant_id == tenant_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_node(
        db: AsyncSession, tenant_id: UUID, data: dict
    ) -> OrgNode:
        # Validate level belongs to this tenant
        level_stmt = select(OrgLevel).where(
            OrgLevel.id == data["level_id"], OrgLevel.tenant_id == tenant_id
        )
        level_result = await db.execute(level_stmt)
        level = level_result.scalar_one_or_none()
        if not level:
            raise ValueError("Level not found for this tenant")

        # Validate parent if provided
        if data.get("parent_id"):
            parent = await OrgService.get_node_by_id(
                db, data["parent_id"], tenant_id
            )
            if not parent:
                raise ValueError("Parent node not found")
            if parent.level.level_number >= level.level_number:
                raise ValueError(
                    f"Child level ({level.level_number}) must be greater than "
                    f"parent level ({parent.level.level_number})"
                )
        else:
            # Root node must be at level 1
            if level.level_number != 1:
                raise ValueError("Root nodes must be at level 1")

        # Validate head user if provided
        if data.get("head_user_id"):
            head_stmt = select(User).where(
                User.id == data["head_user_id"], User.tenant_id == tenant_id
            )
            head_result = await db.execute(head_stmt)
            if not head_result.scalar_one_or_none():
                raise ValueError("Head user not found")

        node = OrgNode(tenant_id=tenant_id, **data)
        db.add(node)
        await db.flush()
        await db.refresh(node)

        # Re-fetch with relationships
        return await OrgService.get_node_by_id(db, node.id, tenant_id)  # type: ignore

    @staticmethod
    async def update_node(
        db: AsyncSession, node: OrgNode, tenant_id: UUID, data: dict
    ) -> OrgNode:
        # Handle reparenting
        if "parent_id" in data and data["parent_id"] != node.parent_id:
            new_parent_id = data["parent_id"]
            if new_parent_id is not None:
                parent = await OrgService.get_node_by_id(
                    db, new_parent_id, tenant_id
                )
                if not parent:
                    raise ValueError("Parent node not found")
                # Check circular reference
                if not await OrgService._validate_no_circular_parent(
                    db, node.id, new_parent_id, tenant_id
                ):
                    raise ValueError("Cannot set parent: would create a circular reference")
                # Validate level hierarchy
                node_level = await db.get(OrgLevel, node.level_id)
                if parent.level.level_number >= node_level.level_number:
                    raise ValueError(
                        f"Child level ({node_level.level_number}) must be greater "
                        f"than parent level ({parent.level.level_number})"
                    )

        for key, value in data.items():
            setattr(node, key, value)

        await db.flush()
        await db.refresh(node)
        return await OrgService.get_node_by_id(db, node.id, tenant_id)  # type: ignore

    @staticmethod
    async def delete_node(
        db: AsyncSession, node_id: int, tenant_id: UUID
    ) -> bool:
        node = await OrgService.get_node_by_id(db, node_id, tenant_id)
        if not node:
            return False
        await db.delete(node)
        await db.flush()
        return True

    # ── Tree Operations ──────────────────────────────────────────────

    @staticmethod
    async def get_full_tree(db: AsyncSession, tenant_id: UUID) -> dict:
        """Load all levels and nodes, build nested tree in Python."""
        levels = await OrgService.get_levels(db, tenant_id)

        # Load all nodes with level and head user
        nodes_stmt = (
            select(OrgNode)
            .options(
                selectinload(OrgNode.level),
                selectinload(OrgNode.head_user),
                selectinload(OrgNode.deputy_head_user),
            )
            .where(OrgNode.tenant_id == tenant_id)
            .order_by(OrgNode.sort_order, OrgNode.name)
        )
        nodes_result = await db.execute(nodes_stmt)
        all_nodes = list(nodes_result.scalars().all())

        # Count members per node
        member_counts = await OrgService._count_members_per_node(db, tenant_id)

        # Build adjacency map
        children_map: Dict[Optional[int], list] = {}
        for node in all_nodes:
            pid = node.parent_id
            if pid not in children_map:
                children_map[pid] = []
            children_map[pid].append(node)

        def build_tree(parent_id: Optional[int]) -> list:
            children = children_map.get(parent_id, [])
            result = []
            for node in children:
                tree_node = {
                    "id": node.id,
                    "parent_id": node.parent_id,
                    "level_id": node.level_id,
                    "level_name": node.level.name if node.level else "",
                    "level_number": node.level.level_number if node.level else 0,
                    "name": node.name,
                    "code": node.code,
                    "head_user_id": node.head_user_id,
                    "head_user_name": (
                        node.head_user.full_name if node.head_user else None
                    ),
                    "deputy_head_user_id": node.deputy_head_user_id,
                    "deputy_head_user_name": (
                        node.deputy_head_user.full_name
                        if node.deputy_head_user
                        else None
                    ),
                    "member_count": member_counts.get(node.id, 0),
                    "is_active": node.is_active,
                    "children": build_tree(node.id),
                }
                result.append(tree_node)
            return result

        level_dicts = [
            {"id": l.id, "level_number": l.level_number, "name": l.name}
            for l in levels
        ]
        root_nodes = build_tree(None)

        return {"levels": level_dicts, "nodes": root_nodes}

    # ── Member Operations ────────────────────────────────────────────

    @staticmethod
    async def get_node_members(
        db: AsyncSession, node_id: int, tenant_id: UUID
    ) -> List[dict]:
        """Return both primary and secondary members with an is_primary flag."""
        # Primary members (from user.org_node_id)
        stmt = (
            select(User)
            .where(
                User.org_node_id == node_id,
                User.tenant_id == tenant_id,
                User.is_active == True,
            )
            .order_by(User.last_name, User.first_name)
        )
        result = await db.execute(stmt)
        primary_users = list(result.scalars().all())
        primary_ids = {u.id for u in primary_users}

        members = []
        for u in primary_users:
            members.append({
                "id": u.id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "email": u.email,
                "job_title": u.job_title,
                "avatar": None,
                "is_primary": True,
            })

        # Secondary members (from user_org_nodes where is_primary=False)
        sec_stmt = (
            select(User)
            .join(UserOrgNode, UserOrgNode.user_id == User.id)
            .where(
                UserOrgNode.org_node_id == node_id,
                UserOrgNode.is_primary == False,
                User.tenant_id == tenant_id,
                User.is_active == True,
            )
            .order_by(User.last_name, User.first_name)
        )
        sec_result = await db.execute(sec_stmt)
        for u in sec_result.scalars().all():
            if u.id not in primary_ids:
                members.append({
                    "id": u.id,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "email": u.email,
                    "job_title": u.job_title,
                    "avatar": None,
                    "is_primary": False,
                })

        return members

    @staticmethod
    async def assign_members(
        db: AsyncSession, node_id: int, user_ids: List[int], tenant_id: UUID,
        assigned_by: Optional[int] = None,
    ) -> int:
        """Assign users to a node as primary members. Also writes to user_org_nodes."""
        count = 0
        for uid in user_ids:
            stmt = select(User).where(
                User.id == uid, User.tenant_id == tenant_id
            )
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                old_node_id = user.org_node_id
                user.org_node_id = node_id
                count += 1

                # Remove old primary assignment from junction table
                if old_node_id:
                    await db.execute(
                        delete(UserOrgNode).where(
                            UserOrgNode.user_id == uid,
                            UserOrgNode.org_node_id == old_node_id,
                            UserOrgNode.is_primary == True,
                        )
                    )

                # Upsert primary assignment in junction table
                existing = await db.execute(
                    select(UserOrgNode).where(
                        UserOrgNode.user_id == uid,
                        UserOrgNode.org_node_id == node_id,
                    )
                )
                uon = existing.scalar_one_or_none()
                if uon:
                    uon.is_primary = True
                else:
                    db.add(UserOrgNode(
                        user_id=uid,
                        org_node_id=node_id,
                        is_primary=True,
                        assigned_by=assigned_by,
                    ))
        await db.flush()
        return count

    @staticmethod
    async def unassign_members(
        db: AsyncSession, user_ids: List[int], tenant_id: UUID
    ) -> int:
        """Unassign users from their primary node. Also cleans user_org_nodes."""
        count = 0
        for uid in user_ids:
            stmt = select(User).where(
                User.id == uid, User.tenant_id == tenant_id
            )
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            if user and user.org_node_id is not None:
                # Remove primary assignment from junction table
                await db.execute(
                    delete(UserOrgNode).where(
                        UserOrgNode.user_id == uid,
                        UserOrgNode.org_node_id == user.org_node_id,
                        UserOrgNode.is_primary == True,
                    )
                )
                user.org_node_id = None
                count += 1
        await db.flush()
        return count

    @staticmethod
    async def assign_secondary_members(
        db: AsyncSession, node_id: int, user_ids: List[int], tenant_id: UUID,
        assigned_by: Optional[int] = None,
    ) -> int:
        """Assign users as secondary members of a node."""
        count = 0
        for uid in user_ids:
            # Verify user belongs to tenant
            user_stmt = select(User).where(User.id == uid, User.tenant_id == tenant_id)
            user_result = await db.execute(user_stmt)
            if not user_result.scalar_one_or_none():
                continue

            # Check if already assigned
            existing = await db.execute(
                select(UserOrgNode).where(
                    UserOrgNode.user_id == uid,
                    UserOrgNode.org_node_id == node_id,
                )
            )
            if existing.scalar_one_or_none():
                continue  # Already assigned (primary or secondary)

            db.add(UserOrgNode(
                user_id=uid,
                org_node_id=node_id,
                is_primary=False,
                assigned_by=assigned_by,
            ))
            count += 1
        await db.flush()
        return count

    @staticmethod
    async def remove_secondary_members(
        db: AsyncSession, node_id: int, user_ids: List[int], tenant_id: UUID,
    ) -> int:
        """Remove secondary memberships from a node."""
        count = 0
        for uid in user_ids:
            result = await db.execute(
                select(UserOrgNode).where(
                    UserOrgNode.user_id == uid,
                    UserOrgNode.org_node_id == node_id,
                    UserOrgNode.is_primary == False,
                )
            )
            uon = result.scalar_one_or_none()
            if uon:
                await db.delete(uon)
                count += 1
        await db.flush()
        return count

    # ── Approval Chain ───────────────────────────────────────────────

    @staticmethod
    async def get_approval_chain(
        db: AsyncSession, user_id: int, tenant_id: UUID
    ) -> List[dict]:
        """Derive approval chain by walking up org_nodes parent chain."""
        # Get the user
        user_stmt = select(User).where(
            User.id == user_id, User.tenant_id == tenant_id
        )
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        if not user or not user.org_node_id:
            return []

        today = date.today()
        chain = []
        current_node_id = user.org_node_id
        # The visited set guarantees termination (finite nodes, each visited
        # once), so there is no depth cap — hierarchies can be any depth.
        visited: set[int] = set()

        while current_node_id:
            if current_node_id in visited:
                break
            visited.add(current_node_id)

            node = await OrgService.get_node_by_id(db, current_node_id, tenant_id)
            if not node:
                break

            approver_id = node.head_user_id
            approver_name = node.head_user.full_name if node.head_user else None
            is_deputy = False

            # Skip if head is the requesting user themselves
            if approver_id == user_id:
                current_node_id = node.parent_id
                continue

            # Check if head is on approved leave today
            if approver_id:
                leave_stmt = (
                    select(func.count())
                    .select_from(LeaveApplication)
                    .where(
                        LeaveApplication.employee_id == approver_id,
                        LeaveApplication.status == "approved",
                        LeaveApplication.start_date <= today,
                        LeaveApplication.end_date >= today,
                    )
                )
                leave_result = await db.execute(leave_stmt)
                head_on_leave = leave_result.scalar() > 0

                if head_on_leave and node.deputy_head_user_id:
                    approver_id = node.deputy_head_user_id
                    approver_name = (
                        node.deputy_head_user.full_name
                        if node.deputy_head_user
                        else None
                    )
                    is_deputy = True

            if approver_id and approver_name:
                chain.append(
                    {
                        "node_id": node.id,
                        "node_name": node.name,
                        "level_name": node.level.name if node.level else "",
                        "approver_id": approver_id,
                        "approver_name": approver_name,
                        "is_deputy": is_deputy,
                    }
                )

            current_node_id = node.parent_id

        return chain

    # ── Validation Helpers ───────────────────────────────────────────

    @staticmethod
    async def _validate_no_circular_parent(
        db: AsyncSession,
        node_id: int,
        new_parent_id: int,
        tenant_id: UUID,
    ) -> bool:
        """Returns True if valid (no cycle), False if circular."""
        if node_id == new_parent_id:
            return False

        current_id = new_parent_id
        # visited seeds with node_id so re-encountering it (a cycle back onto
        # the node being reparented) is caught. Walking to the root always
        # terminates because each node has one parent and we never revisit.
        visited = {node_id, new_parent_id}

        while True:
            stmt = select(OrgNode.parent_id).where(
                OrgNode.id == current_id, OrgNode.tenant_id == tenant_id
            )
            result = await db.execute(stmt)
            parent_id = result.scalar_one_or_none()

            if parent_id is None:
                return True  # Reached root without finding node_id
            if parent_id in visited:
                return False

            visited.add(parent_id)
            current_id = parent_id

    @staticmethod
    async def _count_members_per_node(
        db: AsyncSession, tenant_id: UUID
    ) -> Dict[int, int]:
        """Count all members (primary + secondary) per node."""
        # Primary members via user.org_node_id
        primary_stmt = (
            select(User.org_node_id, func.count())
            .where(
                User.tenant_id == tenant_id,
                User.org_node_id.isnot(None),
                User.is_active == True,
            )
            .group_by(User.org_node_id)
        )
        primary_result = await db.execute(primary_stmt)
        counts: Dict[int, int] = {row[0]: row[1] for row in primary_result.all()}

        # Secondary members via user_org_nodes
        secondary_stmt = (
            select(UserOrgNode.org_node_id, func.count())
            .join(User, User.id == UserOrgNode.user_id)
            .where(
                User.tenant_id == tenant_id,
                User.is_active == True,
                UserOrgNode.is_primary == False,
            )
            .group_by(UserOrgNode.org_node_id)
        )
        secondary_result = await db.execute(secondary_stmt)
        for row in secondary_result.all():
            counts[row[0]] = counts.get(row[0], 0) + row[1]

        return counts
