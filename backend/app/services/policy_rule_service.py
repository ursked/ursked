import json
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import PolicyRule
from app.services.policy_engine_service import (
    ACTION_TYPES,
    CONDITION_FIELDS,
    OPERATORS,
)


class PolicyRuleValidationError(ValueError):
    """Raised when a policy rule references grammar the engine can't execute."""


DEFAULT_POLICY_RULES = [
    {
        "name": "Holiday Overtime",
        "description": "Overtime during holidays applies holiday OT category",
        "rule_type": "overtime",
        "priority": 5,
        "conditions": [
            {"field": "overtime_minutes", "operator": "gt", "value": 0},
            {"field": "is_holiday", "operator": "eq", "value": True},
        ],
        "actions": [{"type": "apply_ot_category", "category_code": "holiday_ot"}],
    },
    {
        "name": "Regular Overtime",
        "description": "Non-holiday overtime applies regular OT category",
        "rule_type": "overtime",
        "priority": 10,
        "conditions": [
            {"field": "overtime_minutes", "operator": "gt", "value": 0},
            {"field": "is_holiday", "operator": "eq", "value": False},
            {"field": "is_special", "operator": "eq", "value": False},
        ],
        "actions": [{"type": "apply_ot_category", "category_code": "regular_ot"}],
    },
    {
        "name": "Tardiness Over 1 Hour",
        "description": "Late by more than 60 minutes results in leave deduction",
        "rule_type": "tardiness",
        "priority": 5,
        "conditions": [
            {"field": "tardiness_minutes", "operator": "gt", "value": 60},
        ],
        "actions": [{"type": "leave_deduction", "round_to_hours": 1}],
    },
    {
        "name": "Tardiness Under 1 Hour",
        "description": "Late by up to 60 minutes triggers a warning",
        "rule_type": "tardiness",
        "priority": 10,
        "conditions": [
            {"field": "tardiness_minutes", "operator": "gt", "value": 0},
            {"field": "tardiness_minutes", "operator": "lte", "value": 60},
        ],
        "actions": [{"type": "send_warning"}],
    },
]


class PolicyRuleService:

    @staticmethod
    async def seed_defaults(db: AsyncSession, tenant_id: UUID) -> None:
        """Idempotently seed default policy rules for a tenant."""
        for rule_data in DEFAULT_POLICY_RULES:
            stmt = select(PolicyRule).where(
                PolicyRule.tenant_id == tenant_id,
                PolicyRule.name == rule_data["name"],
            )
            result = await db.execute(stmt)
            if result.scalar_one_or_none():
                continue

            rule = PolicyRule(
                tenant_id=tenant_id,
                name=rule_data["name"],
                description=rule_data["description"],
                rule_type=rule_data["rule_type"],
                priority=rule_data["priority"],
                conditions=rule_data["conditions"],
                actions=rule_data["actions"],
            )
            db.add(rule)
        await db.flush()

    @staticmethod
    async def list_rules(
        db: AsyncSession,
        tenant_id: UUID,
        rule_type: Optional[str] = None,
        active_only: bool = True,
    ) -> List[PolicyRule]:
        stmt = select(PolicyRule).where(PolicyRule.tenant_id == tenant_id)
        if rule_type:
            stmt = stmt.where(PolicyRule.rule_type == rule_type)
        if active_only:
            stmt = stmt.where(PolicyRule.is_active == True)
        stmt = stmt.order_by(PolicyRule.priority.asc(), PolicyRule.id.asc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_rule(db: AsyncSession, tenant_id: UUID, rule_id: int) -> Optional[PolicyRule]:
        stmt = select(PolicyRule).where(
            PolicyRule.tenant_id == tenant_id, PolicyRule.id == rule_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _validate_condition_node(node, depth: int = 0) -> int:
        """Recursively validate a condition node; returns the number of leaves.

        Accepts the tree grammar: a leaf {field,operator,value}, or a group
        {"all"|"any"|"not": ...}. Unknown fields/operators are rejected so a rule
        can never silently no-op. Returns leaf count so the caller can require ≥1."""
        if depth > 10:
            raise PolicyRuleValidationError("Condition nesting is too deep.")
        if isinstance(node, list):
            return sum(PolicyRuleService._validate_condition_node(n, depth + 1) for n in node)
        if isinstance(node, dict) and ("all" in node or "any" in node):
            children = node.get("all") if "all" in node else node.get("any")
            return sum(
                PolicyRuleService._validate_condition_node(n, depth + 1)
                for n in (children or [])
            )
        if isinstance(node, dict) and "not" in node:
            return PolicyRuleService._validate_condition_node(node.get("not"), depth + 1)
        # Leaf.
        if not isinstance(node, dict):
            raise PolicyRuleValidationError("Malformed condition.")
        field = node.get("field")
        operator = node.get("operator")
        if field not in CONDITION_FIELDS:
            raise PolicyRuleValidationError(
                f"Unknown condition field '{field}'. Allowed: "
                f"{', '.join(sorted(CONDITION_FIELDS))}."
            )
        if operator not in OPERATORS:
            raise PolicyRuleValidationError(
                f"Unknown operator '{operator}'. Allowed: "
                f"{', '.join(sorted(OPERATORS))}."
            )
        if "value" not in node:
            raise PolicyRuleValidationError(f"Condition on '{field}' is missing a value.")
        return 1

    @staticmethod
    def _validate_action(action: dict, depth: int = 0) -> None:
        """Validate a single action, including range-band actions whose bands each
        carry an inner action."""
        if depth > 3:
            raise PolicyRuleValidationError("Action nesting is too deep.")
        atype = action.get("type")
        if atype == "bands":
            if not action.get("field"):
                raise PolicyRuleValidationError("A range-band action needs a 'field'.")
            bands = action.get("bands") or []
            if not bands:
                raise PolicyRuleValidationError("A range-band action needs at least one band.")
            for band in bands:
                inner = band.get("action")
                if not isinstance(inner, dict):
                    raise PolicyRuleValidationError("Each band needs an 'action'.")
                PolicyRuleService._validate_action(inner, depth + 1)
            return
        if atype not in ACTION_TYPES:
            raise PolicyRuleValidationError(
                f"Unknown action '{atype}'. Allowed: {', '.join(sorted(ACTION_TYPES))}."
            )

    @staticmethod
    def _validate(conditions, actions: list) -> None:
        """Reject a rule the engine could never execute correctly.

        A rule with an unknown field/operator/action, or with no conditions (which
        the engine treats as never-matching), is a silent footgun — it saves clean
        but does nothing. Fail loudly at save time instead."""
        leaves = PolicyRuleService._validate_condition_node(conditions or [])
        if leaves < 1:
            raise PolicyRuleValidationError(
                "A rule must have at least one condition (a rule with no conditions "
                "never fires)."
            )
        if not actions:
            raise PolicyRuleValidationError("A rule must have at least one action.")
        for a in actions:
            PolicyRuleService._validate_action(a)

    @staticmethod
    async def create_rule(db: AsyncSession, tenant_id: UUID, data: dict, created_by: Optional[int] = None) -> PolicyRule:
        PolicyRuleService._validate(data.get("conditions") or [], data.get("actions") or [])
        rule = PolicyRule(
            tenant_id=tenant_id,
            name=data["name"],
            description=data.get("description"),
            rule_type=data["rule_type"],
            priority=data.get("priority", 0),
            is_active=data.get("is_active", True),
            conditions=data["conditions"],
            actions=data["actions"],
            employment_types=data.get("employment_types"),
            scope_org_node_ids=data.get("scope_org_node_ids"),
            effective_from=data.get("effective_from"),
            effective_until=data.get("effective_until"),
            created_by=created_by,
        )
        db.add(rule)
        await db.flush()
        return rule

    @staticmethod
    async def update_rule(db: AsyncSession, tenant_id: UUID, rule_id: int, data: dict) -> Optional[PolicyRule]:
        rule = await PolicyRuleService.get_rule(db, tenant_id, rule_id)
        if not rule:
            return None

        # Validate the resulting conditions/actions (merged view) if either changes.
        new_conditions = data["conditions"] if data.get("conditions") is not None else rule.conditions
        new_actions = data["actions"] if data.get("actions") is not None else rule.actions
        if "conditions" in data or "actions" in data:
            PolicyRuleService._validate(new_conditions or [], new_actions or [])

        for field in ["name", "description", "rule_type", "priority", "is_active", "conditions", "actions", "employment_types"]:
            if field in data and data[field] is not None:
                setattr(rule, field, data[field])

        # Scope fields are nullable — an explicit key (even null) sets/clears them.
        for field in ["scope_org_node_ids", "effective_from", "effective_until"]:
            if field in data:
                setattr(rule, field, data[field])

        await db.flush()
        return rule

    @staticmethod
    async def delete_rule(db: AsyncSession, tenant_id: UUID, rule_id: int) -> bool:
        rule = await PolicyRuleService.get_rule(db, tenant_id, rule_id)
        if not rule:
            return False
        await db.delete(rule)
        await db.flush()
        return True
