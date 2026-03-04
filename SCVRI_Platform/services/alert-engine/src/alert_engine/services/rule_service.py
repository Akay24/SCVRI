"""Alert rule service — CRUD and event-based rule evaluation."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from jinja2 import Environment, BaseLoader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scvri_shared.exceptions import NotFoundError
from scvri_shared.logging import get_logger
from alert_engine.schemas.rule import AlertRuleCreate, AlertRuleResponse, AlertRuleUpdate

log = get_logger(__name__)

_jinja_env = Environment(loader=BaseLoader(), autoescape=False)


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_rule(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: AlertRuleCreate,
) -> AlertRuleResponse:
    rule_id = uuid.uuid4()

    await db.execute(text("""
        INSERT INTO alert.alert_rules
            (id, tenant_id, name, description, trigger_type,
             event_topics, event_types, conditions, severity,
             alert_title_template, alert_description_template,
             cooldown_seconds, suppress_outside_hours,
             suppress_start_hour, suppress_end_hour,
             auto_escalate_minutes, supplier_ids, is_global,
             status, fire_count, created_by, created_at, updated_at)
        VALUES
            (:id, :tenant_id, :name, :description, :trigger_type,
             :event_topics::jsonb, :event_types::jsonb, :conditions::jsonb, :severity,
             :title_tmpl, :desc_tmpl,
             :cooldown, :suppress_hours,
             :suppress_start, :suppress_end,
             :auto_escalate, :supplier_ids::jsonb, :is_global,
             'active', 0, :created_by, now(), now())
    """), {
        "id": str(rule_id),
        "tenant_id": str(tenant_id),
        "name": data.name,
        "description": data.description,
        "trigger_type": data.trigger_type,
        "event_topics": json.dumps(data.event_topics),
        "event_types": json.dumps(data.event_types),
        "conditions": json.dumps([c.model_dump() for c in data.conditions]),
        "severity": data.severity,
        "title_tmpl": data.alert_title_template,
        "desc_tmpl": data.alert_description_template,
        "cooldown": data.cooldown_seconds,
        "suppress_hours": data.suppress_outside_hours,
        "suppress_start": data.suppress_start_hour,
        "suppress_end": data.suppress_end_hour,
        "auto_escalate": data.auto_escalate_minutes,
        "supplier_ids": json.dumps([str(s) for s in data.supplier_ids]),
        "is_global": data.is_global,
        "created_by": str(user_id),
    })
    await db.commit()
    log.info("rule.created", rule_id=str(rule_id), name=data.name)
    return await get_rule(db, tenant_id, rule_id)


async def get_rule(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
) -> AlertRuleResponse:
    row = (await db.execute(text("""
        SELECT * FROM alert.alert_rules
        WHERE id = :id AND (tenant_id = :tenant_id OR is_global = TRUE)
    """), {"id": str(rule_id), "tenant_id": str(tenant_id)})).mappings().one_or_none()

    if row is None:
        raise NotFoundError(f"Alert rule {rule_id} not found")
    return _map_rule(row)


async def list_rules(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    status: str | None = None,
    trigger_type: str | None = None,
) -> list[AlertRuleResponse]:
    filters = "(tenant_id = :tenant_id OR is_global = TRUE)"
    params: dict[str, Any] = {"tenant_id": str(tenant_id)}

    if status:
        filters += " AND status = :status"
        params["status"] = status
    if trigger_type:
        filters += " AND trigger_type = :trigger_type"
        params["trigger_type"] = trigger_type

    rows = (await db.execute(text(f"""
        SELECT * FROM alert.alert_rules
        WHERE {filters}
        ORDER BY name
    """), params)).mappings().all()

    return [_map_rule(r) for r in rows]


async def update_rule(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
    data: AlertRuleUpdate,
) -> AlertRuleResponse:
    await get_rule(db, tenant_id, rule_id)  # 404 guard

    sets: list[str] = ["updated_at = now()"]
    params: dict[str, Any] = {"id": str(rule_id), "tenant_id": str(tenant_id)}

    if data.name is not None:
        sets.append("name = :name"); params["name"] = data.name
    if data.description is not None:
        sets.append("description = :description"); params["description"] = data.description
    if data.conditions is not None:
        sets.append("conditions = :conditions::jsonb")
        params["conditions"] = json.dumps([c.model_dump() for c in data.conditions])
    if data.severity is not None:
        sets.append("severity = :severity"); params["severity"] = data.severity
    if data.cooldown_seconds is not None:
        sets.append("cooldown_seconds = :cooldown"); params["cooldown"] = data.cooldown_seconds
    if data.auto_escalate_minutes is not None:
        sets.append("auto_escalate_minutes = :auto_escalate")
        params["auto_escalate"] = data.auto_escalate_minutes
    if data.status is not None:
        sets.append("status = :status"); params["status"] = data.status

    await db.execute(text(f"""
        UPDATE alert.alert_rules
        SET {', '.join(sets)}
        WHERE id = :id AND tenant_id = :tenant_id
    """), params)
    await db.commit()
    return await get_rule(db, tenant_id, rule_id)


async def delete_rule(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
) -> None:
    await get_rule(db, tenant_id, rule_id)
    await db.execute(text("""
        UPDATE alert.alert_rules SET status = 'inactive', updated_at = now()
        WHERE id = :id AND tenant_id = :tenant_id
    """), {"id": str(rule_id), "tenant_id": str(tenant_id)})
    await db.commit()


# ── Rule evaluation ───────────────────────────────────────────────────────────

async def evaluate_event_rules(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    event_topic: str,
    event_type: str,
    event_payload: dict,
) -> list[uuid.UUID]:
    """
    Evaluate all active event rules for the given tenant + event.
    Returns list of alert IDs created.
    """
    # Fetch matching rules
    rows = (await db.execute(text("""
        SELECT * FROM alert.alert_rules
        WHERE (tenant_id = :tenant_id OR is_global = TRUE)
          AND status = 'active'
          AND trigger_type = 'event'
          AND event_topics::jsonb ? :topic
          AND (
                jsonb_array_length(event_types::jsonb) = 0
                OR event_types::jsonb ? :event_type
              )
    """), {
        "tenant_id": str(tenant_id),
        "topic": event_topic,
        "event_type": event_type,
    })).mappings().all()

    alert_ids: list[uuid.UUID] = []
    system_user = uuid.UUID("00000000-0000-0000-0000-000000000001")

    for rule_row in rows:
        rule = _map_rule(rule_row)

        # Cooldown check
        if rule.last_fired_at:
            elapsed = (datetime.now(timezone.utc) - rule.last_fired_at).total_seconds()
            if elapsed < rule.cooldown_seconds:
                log.debug(
                    "rule.cooldown_active",
                    rule_id=str(rule.id),
                    remaining_s=rule.cooldown_seconds - elapsed,
                )
                continue

        # Business-hour suppression
        if rule.suppress_outside_hours:
            now_hour = datetime.now(timezone.utc).hour
            if rule.suppress_start_hour is not None and rule.suppress_end_hour is not None:
                if not (rule.suppress_start_hour <= now_hour < rule.suppress_end_hour):
                    log.debug("rule.suppressed_outside_hours", rule_id=str(rule.id))
                    continue

        # Condition evaluation
        if not _check_conditions(rule.conditions, event_payload):
            continue

        # Render templates
        title = _render_template(rule.alert_title_template, event_payload)
        description = _render_template(rule.alert_description_template, event_payload)

        from alert_engine.schemas.alert import AlertCreate  # noqa: PLC0415
        from alert_engine.services import alert_service  # noqa: PLC0415

        supplier_id = _extract_supplier_id(event_payload)

        alert_in = AlertCreate(
            title=title,
            description=description,
            severity=rule.severity,
            source=_topic_to_source(event_topic),
            source_event_type=event_type,
            rule_id=rule.id,
            supplier_id=supplier_id,
            payload=event_payload,
        )
        new_alert = await alert_service.create_alert(
            db, tenant_id, system_user, alert_in
        )
        alert_ids.append(new_alert.id)

        # Update rule fire statistics
        await db.execute(text("""
            UPDATE alert.alert_rules
            SET fire_count   = fire_count + 1,
                last_fired_at = now(),
                updated_at   = now()
            WHERE id = :id
        """), {"id": str(rule.id)})
        await db.commit()

        log.info(
            "rule.fired",
            rule_id=str(rule.id),
            alert_id=str(new_alert.id),
            event_type=event_type,
        )

    return alert_ids


# ── Condition evaluator ───────────────────────────────────────────────────────

def _check_conditions(conditions: list, payload: dict) -> bool:
    from alert_engine.schemas.rule import RuleCondition  # noqa: PLC0415

    for cond_data in conditions:
        if isinstance(cond_data, dict):
            from alert_engine.schemas.rule import RuleCondition  # noqa: PLC0415
            cond = RuleCondition(**cond_data)
        else:
            cond = cond_data

        value = _get_nested(payload, cond.field)
        if not _apply_operator(value, cond.operator, cond.value):
            return False
    return True


def _get_nested(data: dict, path: str) -> Any:
    """Extract a value from a nested dict using dot-notation path."""
    keys = path.split(".")
    val: Any = data
    for key in keys:
        if isinstance(val, dict):
            val = val.get(key)
        else:
            return None
    return val


def _apply_operator(actual: Any, operator: str, expected: Any) -> bool:
    try:
        if operator == "gt":   return actual > expected
        if operator == "gte":  return actual >= expected
        if operator == "lt":   return actual < expected
        if operator == "lte":  return actual <= expected
        if operator == "eq":   return actual == expected
        if operator == "neq":  return actual != expected
        if operator == "in":   return actual in expected
        if operator == "contains":
            return expected in (actual or "")
    except (TypeError, ValueError):
        pass
    return False


def _render_template(tmpl: str, context: dict) -> str:
    try:
        return _jinja_env.from_string(tmpl).render(**context)
    except Exception:  # noqa: BLE001
        return tmpl


def _topic_to_source(topic: str) -> str:
    mapping = {
        "risk.events": "risk_engine",
        "visibility.events": "visibility",
        "scorecard.computed": "scorecard",
    }
    return mapping.get(topic, "system")


def _extract_supplier_id(payload: dict) -> uuid.UUID | None:
    sid = payload.get("supplier_id")
    if sid:
        try:
            return uuid.UUID(str(sid))
        except ValueError:
            pass
    return None


# ── Mapper ────────────────────────────────────────────────────────────────────

def _map_rule(row: Any) -> AlertRuleResponse:
    from alert_engine.schemas.rule import RuleCondition  # noqa: PLC0415

    def _load(col: Any) -> list:
        if isinstance(col, str):
            return json.loads(col)
        if col is None:
            return []
        return list(col)

    conditions_raw = _load(row.get("conditions"))
    conditions = [
        RuleCondition(**c) if isinstance(c, dict) else c
        for c in conditions_raw
    ]

    supplier_ids_raw = _load(row.get("supplier_ids"))
    supplier_ids = [uuid.UUID(s) for s in supplier_ids_raw if s]

    return AlertRuleResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        description=row.get("description"),
        trigger_type=row["trigger_type"],
        event_topics=_load(row.get("event_topics")),
        event_types=_load(row.get("event_types")),
        conditions=conditions,
        severity=row["severity"],
        alert_title_template=row["alert_title_template"],
        alert_description_template=row["alert_description_template"],
        cooldown_seconds=row.get("cooldown_seconds", 3600),
        suppress_outside_hours=bool(row.get("suppress_outside_hours", False)),
        suppress_start_hour=row.get("suppress_start_hour"),
        suppress_end_hour=row.get("suppress_end_hour"),
        auto_escalate_minutes=row.get("auto_escalate_minutes"),
        supplier_ids=supplier_ids,
        is_global=bool(row.get("is_global", False)),
        status=row.get("status", "active"),
        fire_count=row.get("fire_count", 0),
        last_fired_at=row.get("last_fired_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Rule test (dry-run evaluation) ────────────────────────────────────────────

async def test_rule(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
    sample_payload: dict,
) -> dict:
    """
    Dry-run evaluate a rule against a sample payload.
    Returns match result and per-condition breakdown; does NOT fire alerts.
    """
    rule = await get_rule(db, tenant_id, rule_id)

    condition_results = []
    for cond in rule.conditions:
        actual = _get_nested(sample_payload, cond.field)
        matched = actual is not None and _apply_operator(actual, cond.operator, cond.value)
        condition_results.append({
            "field": cond.field,
            "operator": cond.operator,
            "expected": cond.value,
            "actual": actual,
            "matched": matched,
            "description": cond.description,
        })

    all_matched = all(r["matched"] for r in condition_results) if condition_results else True

    rendered_title = _render_template(rule.alert_title_template, sample_payload)
    rendered_description = _render_template(rule.alert_description_template, sample_payload)

    return {
        "rule_id": str(rule_id),
        "rule_name": rule.name,
        "would_fire": all_matched,
        "conditions": condition_results,
        "rendered_title": rendered_title,
        "rendered_description": rendered_description,
    }
