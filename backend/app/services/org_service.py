from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.configurable_types import UserOrgNode
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
    def level_changes(existing: List[OrgLevel], levels: List[dict]) -> dict:
        """How many levels a set_levels payload adds and removes, so the router
        can require organization:create / organization:delete for them."""
        if any(item.get("id") for item in levels):
            kept = {item.get("id") for item in levels if item.get("id")}
            added = sum(1 for item in levels if not item.get("id"))
        else:
            wanted = {item["level_number"] for item in levels}
            kept = {l.id for l in existing if l.level_number in wanted}
            numbers = {l.level_number for l in existing}
            added = sum(1 for item in levels if item["level_number"] not in numbers)
        removed = sum(1 for l in existing if l.id not in kept)
        return {"added": added, "removed": removed}

    @staticmethod
    async def set_levels(
        db: AsyncSession, tenant_id: UUID, levels: List[dict]
    ) -> List[OrgLevel]:
        """Replace all levels atomically. Validates no nodes exist at removed levels.

        Levels are matched by id. They used to be matched by level_number, so
        deleting a middle level (1, 2, 3 saved as 1, 2 renumbered) deleted
        level 3 instead and renamed level 2: units kept their level row but
        showed another level's name. A payload with no ids at all comes from
        an old client and is still matched by number.
        """
        existing = await OrgService.get_levels(db, tenant_id)
        by_id: Dict[int, OrgLevel] = {l.id: l for l in existing}
        by_number: Dict[int, OrgLevel] = {l.level_number: l for l in existing}
        ordered = sorted(levels, key=lambda x: x["level_number"])
        use_ids = any(item.get("id") for item in levels)

        # Which existing level (if any) each payload item keeps.
        targets: List[Optional[int]] = []
        for item in ordered:
            if use_ids:
                lid = item.get("id")
                if lid is not None and lid not in by_id:
                    raise ValueError("One of the levels no longer exists. Reload the page and try again.")
                targets.append(lid)
            else:
                lvl = by_number.get(item["level_number"])
                targets.append(lvl.id if lvl else None)
        kept = {t for t in targets if t is not None}

        removed = [l for l in existing if l.id not in kept]
        for lvl in removed:
            count = (
                await db.execute(
                    select(func.count()).select_from(OrgNode).where(OrgNode.level_id == lvl.id)
                )
            ).scalar()
            if count:
                raise ValueError(
                    f'The level "{lvl.name}" still has {count} unit(s). Move or delete them '
                    "before removing the level."
                )
        for lvl in removed:
            await db.delete(lvl)
        await db.flush()

        # Park kept levels on free numbers first: renumbering in place (3 -> 2
        # while 2 still exists) would trip the per-tenant unique constraint.
        offset = 10000 + max([l.level_number for l in existing] + [0])
        for lid in kept:
            by_id[lid].level_number += offset
        await db.flush()

        result_levels = []
        for number, (item, lid) in enumerate(zip(ordered, targets), start=1):
            if lid is not None:
                lvl = by_id[lid]
                lvl.level_number = number
                lvl.name = item["name"]
            else:
                lvl = OrgLevel(tenant_id=tenant_id, level_number=number, name=item["name"])
                db.add(lvl)
            result_levels.append(lvl)
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
    async def _check_person(db: AsyncSession, tenant_id: UUID, user_id: Optional[int], role: str) -> None:
        if not user_id:
            return
        u = (
            await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if not u:
            raise ValueError(f"The chosen {role} does not exist.")
        if not u.is_active:
            raise ValueError(
                f"{u.first_name} {u.last_name} is inactive and cannot be the {role} of a unit."
            )

    @staticmethod
    async def _grant_approver_roles(
        db: AsyncSession, tenant_id: UUID, data: dict, granted_by: Optional[int]
    ) -> List[str]:
        """Heads and deputies approve leave in org-chart routing, so naming one
        is naming an approver: give them Leave Approver if they have no
        reviewer role (the unit panel says so before saving)."""
        from app.services.leave_access import ensure_reviewer_role

        names = []
        for key, what in (("head_user_id", "head"), ("deputy_head_user_id", "deputy")):
            uid = data.get(key)
            if uid and await ensure_reviewer_role(
                db, tenant_id, uid, granted_by=granted_by, context=f"made {what} of a unit"
            ):
                u = await db.get(User, uid)
                names.append(f"{u.first_name} {u.last_name}")
        return names

    @staticmethod
    async def create_node(
        db: AsyncSession, tenant_id: UUID, data: dict, granted_by: Optional[int] = None
    ) -> OrgNode:
        # Validate level belongs to this tenant
        level = (
            await db.execute(
                select(OrgLevel).where(OrgLevel.id == data["level_id"], OrgLevel.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if not level:
            raise ValueError("Level not found for this tenant")

        # Validate parent if provided
        if data.get("parent_id"):
            parent = await OrgService.get_node_by_id(db, data["parent_id"], tenant_id)
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

        await OrgService._check_person(db, tenant_id, data.get("head_user_id"), "head")
        await OrgService._check_person(db, tenant_id, data.get("deputy_head_user_id"), "deputy")

        node = OrgNode(tenant_id=tenant_id, **data)
        db.add(node)
        await db.flush()
        await OrgService._grant_approver_roles(db, tenant_id, data, granted_by)
        await db.refresh(node)

        # Re-fetch with relationships
        return await OrgService.get_node_by_id(db, node.id, tenant_id)  # type: ignore

    @staticmethod
    async def update_node(
        db: AsyncSession, node: OrgNode, tenant_id: UUID, data: dict, granted_by: Optional[int] = None
    ) -> OrgNode:
        # Handle reparenting ("Move under...")
        if "parent_id" in data and data["parent_id"] != node.parent_id:
            new_parent_id = data["parent_id"]
            node_level = await db.get(OrgLevel, node.level_id)
            if new_parent_id is not None:
                parent = await OrgService.get_node_by_id(db, new_parent_id, tenant_id)
                if not parent:
                    raise ValueError("Parent node not found")
                # Check circular reference
                if not await OrgService._validate_no_circular_parent(
                    db, node.id, new_parent_id, tenant_id
                ):
                    raise ValueError(
                        "A unit cannot be moved under itself or under one of its own sub-units."
                    )
                if parent.level.level_number >= node_level.level_number:
                    raise ValueError(
                        f"A {node_level.name} can only sit under a higher level than its own; "
                        f"{parent.name} is a {parent.level.name}."
                    )
            elif node_level.level_number != 1:
                # Previously unchecked, so a PATCH could orphan a sub-unit into
                # a second, invalid top of the tree.
                raise ValueError(
                    f"Only top-level units can stand on their own; choose a unit to move this {node_level.name} under."
                )

        await OrgService._check_person(db, tenant_id, data.get("head_user_id"), "head")
        await OrgService._check_person(db, tenant_id, data.get("deputy_head_user_id"), "deputy")

        for key, value in data.items():
            setattr(node, key, value)

        await db.flush()
        await OrgService._grant_approver_roles(db, tenant_id, data, granted_by)
        await db.refresh(node)
        return await OrgService.get_node_by_id(db, node.id, tenant_id)  # type: ignore

    @staticmethod
    async def delete_preview(db: AsyncSession, node_id: int, tenant_id: UUID) -> Optional[dict]:
        """Everything deleting a unit would change, listed before confirming.

        Deleting used to cascade: every unit below went with it (the FK is ON
        DELETE CASCADE), and so did the approval rules targeting them, without a
        word. Now the unit's members and direct sub-units move up to its parent,
        approval rules scoped to it are switched off rather than deleted, and
        policy rules stop referring to it.
        """
        from app.models.leave import LeaveApproverAssignment
        from app.models.policy import PolicyRule

        node = await OrgService.get_node_by_id(db, node_id, tenant_id)
        if not node:
            return None
        parent = await OrgService.get_node_by_id(db, node.parent_id, tenant_id) if node.parent_id else None

        members = (
            await db.execute(
                select(User)
                .where(User.tenant_id == tenant_id, User.org_node_id == node_id)
                .order_by(User.last_name, User.first_name)
            )
        ).scalars().all()
        secondary = (
            await db.execute(
                select(User)
                .join(UserOrgNode, UserOrgNode.user_id == User.id)
                .where(
                    UserOrgNode.org_node_id == node_id,
                    UserOrgNode.is_primary == False,  # noqa: E712
                    User.tenant_id == tenant_id,
                )
            )
        ).scalars().all()
        children = (
            await db.execute(
                select(OrgNode)
                .where(OrgNode.tenant_id == tenant_id, OrgNode.parent_id == node_id)
                .order_by(OrgNode.sort_order, OrgNode.name)
            )
        ).scalars().all()

        rules = (
            await db.execute(
                select(LeaveApproverAssignment).where(
                    LeaveApproverAssignment.tenant_id == tenant_id,
                    LeaveApproverAssignment.org_node_id == node_id,
                )
            )
        ).scalars().all()
        rule_rows = [
            {
                "id": r.id,
                "description": (
                    f"Leave approval rule for {node.name}"
                    f"{' and its sub-units' if r.cascade else ''}"
                    f"{'' if r.is_active else ' (already off)'}"
                ),
            }
            for r in rules
        ]

        policy_rows = []
        for pr in (
            await db.execute(select(PolicyRule).where(PolicyRule.tenant_id == tenant_id))
        ).scalars().all():
            scope = list(pr.scope_org_node_ids or [])
            if node_id in scope:
                policy_rows.append({
                    "id": pr.id,
                    "name": pr.name,
                    # A rule scoped ONLY to this unit is switched off: an empty
                    # scope means "all employees", which would widen it.
                    "deactivated": not [x for x in scope if x != node_id],
                })

        blocked = None
        if children and parent is None:
            blocked = (
                f"{node.name} is a top-level unit with sub-units. Move its sub-units under "
                "another unit first; they cannot become top-level units themselves."
            )

        def person(u):
            return {"id": u.id, "name": f"{u.first_name} {u.last_name}"}

        return {
            "node_id": node.id,
            "node_name": node.name,
            "parent_id": parent.id if parent else None,
            "parent_name": parent.name if parent else None,
            "can_delete": blocked is None,
            "blocked_reason": blocked,
            "members_moved": [person(u) for u in members],
            "secondary_members": [person(u) for u in secondary],
            "children_moved": [{"id": c.id, "name": c.name} for c in children],
            "approver_rules_deactivated": rule_rows,
            "policy_rules_changed": policy_rows,
        }

    @staticmethod
    async def delete_node(
        db: AsyncSession, node_id: int, tenant_id: UUID
    ) -> Optional[dict]:
        """Delete one unit, moving what it held to its parent (see
        delete_preview). Returns the summary of what changed, or None if the
        unit does not exist. Raises ValueError when it cannot be done safely."""
        from app.models.leave import LeaveApproverAssignment
        from app.models.policy import PolicyRule

        preview = await OrgService.delete_preview(db, node_id, tenant_id)
        if preview is None:
            return None
        if not preview["can_delete"]:
            raise ValueError(preview["blocked_reason"])
        node_name = preview["node_name"]
        parent_id = preview["parent_id"]

        # Sub-units move up to the parent; their levels still sit below the
        # parent's, so the level rule keeps holding.
        for child in (
            await db.execute(
                select(OrgNode).where(OrgNode.parent_id == node_id, OrgNode.tenant_id == tenant_id)
            )
        ).scalars().all():
            child.parent_id = parent_id
        await db.flush()

        # Primary members follow to the parent (or are unassigned at the top).
        member_ids = [m["id"] for m in preview["members_moved"]]
        if member_ids:
            if parent_id:
                await OrgService.assign_members(db, parent_id, member_ids, tenant_id)
            else:
                await OrgService.unassign_members(db, node_id, member_ids, tenant_id)
        # Secondary memberships move to the parent unless already there.
        for uon in (
            await db.execute(select(UserOrgNode).where(UserOrgNode.org_node_id == node_id))
        ).scalars().all():
            if parent_id:
                dup = (
                    await db.execute(
                        select(UserOrgNode.id).where(
                            UserOrgNode.user_id == uon.user_id,
                            UserOrgNode.org_node_id == parent_id,
                        )
                    )
                ).scalar_one_or_none()
                if dup is None:
                    uon.org_node_id = parent_id
                    continue
            await db.delete(uon)

        # Approval rules: detached and switched off, with the reason shown next
        # to them. Left attached, the FK would delete them with the unit.
        for r in (
            await db.execute(
                select(LeaveApproverAssignment).where(
                    LeaveApproverAssignment.tenant_id == tenant_id,
                    LeaveApproverAssignment.org_node_id == node_id,
                )
            )
        ).scalars().all():
            r.org_node_id = None
            r.cascade = False
            r.is_active = False
            r.deactivated_reason = f"Its unit, {node_name}, was deleted."

        for pr in (
            await db.execute(select(PolicyRule).where(PolicyRule.tenant_id == tenant_id))
        ).scalars().all():
            scope = list(pr.scope_org_node_ids or [])
            if node_id in scope:
                rest = [x for x in scope if x != node_id]
                pr.scope_org_node_ids = rest or None
                if not rest:
                    pr.is_active = False
        await db.flush()

        # Delete by statement, not through the ORM object: its `children`
        # relationship is delete-orphan, and a stale loaded collection would
        # take the sub-units we just moved with it.
        await db.execute(delete(OrgNode).where(OrgNode.id == node_id, OrgNode.tenant_id == tenant_id))
        await db.flush()
        return preview

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
                User.is_active == True,  # noqa: E712
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
                UserOrgNode.is_primary == False,  # noqa: E712
                User.tenant_id == tenant_id,
                User.is_active == True,  # noqa: E712
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
                            UserOrgNode.is_primary == True,  # noqa: E712
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
        db: AsyncSession, node_id: int, user_ids: List[int], tenant_id: UUID
    ) -> int:
        """Remove users' primary membership of THIS unit.

        Users whose primary unit is elsewhere are left alone. The route used to
        ignore the unit in its URL and clear whatever primary unit the user
        had, so removing a secondary member from one unit took them out of
        their real team somewhere else."""
        count = 0
        for uid in user_ids:
            user = (
                await db.execute(select(User).where(User.id == uid, User.tenant_id == tenant_id))
            ).scalar_one_or_none()
            if user and user.org_node_id == node_id:
                await db.execute(
                    delete(UserOrgNode).where(
                        UserOrgNode.user_id == uid,
                        UserOrgNode.org_node_id == node_id,
                        UserOrgNode.is_primary == True,  # noqa: E712
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
            user = user_result.scalar_one_or_none()
            if not user or user.org_node_id == node_id:
                continue  # unknown, or already a primary member here

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
                select(UserOrgNode)
                .join(User, User.id == UserOrgNode.user_id)
                .where(
                    UserOrgNode.user_id == uid,
                    UserOrgNode.org_node_id == node_id,
                    UserOrgNode.is_primary == False,  # noqa: E712
                    User.tenant_id == tenant_id,
                )
            )
            uon = result.scalar_one_or_none()
            if uon:
                await db.delete(uon)
                count += 1
        await db.flush()
        return count

    # The org-chart approval walk that lived here (get_approval_chain) disagreed
    # with filing: it ignored approval rules, the fallback, inactive heads and
    # the required number of levels. The one resolver is
    # LeaveApprovalService.resolve_approval_chain.

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
                User.is_active == True,  # noqa: E712
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
                User.is_active == True,  # noqa: E712
                UserOrgNode.is_primary == False,  # noqa: E712
            )
            .group_by(UserOrgNode.org_node_id)
        )
        secondary_result = await db.execute(secondary_stmt)
        for row in secondary_result.all():
            counts[row[0]] = counts.get(row[0], 0) + row[1]

        return counts
