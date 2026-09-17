"""The single SQL schema contract used by prompts and fixture checks."""

from __future__ import annotations

SCHEMA_VERSION = "fixture-v1"

TABLE_FIELDS: dict[str, str] = {
    "tasks": "id, title, description, priority, completed (boolean), due_date",
    "medications": "id, name, common_dosage, notes",
    "medication_plans": "id, plan_name, medication_id, dosage, notes, active (boolean)",
    "medication_plan_times": "id, plan_id, schedule_time",
    "medication_logs": "id, plan_id, taken_at, scheduled_time, notes",
    "exercise_catalog": "id, name, muscle_group, equipment, description",
    "recipes": "id, name, description, instructions, difficulty, prep_time_minutes",
    "ingredients": "id, name, category, default_unit",
    "inventory": "id, ingredient_id, quantity, unit, expiry_date, min_quantity",
    "media_items": "id, title, media_type, status, genre, author_creator, progress_current, progress_total, is_favorite, rating",
}


def prompt_schema(tables: list[str]) -> str:
    return "\n".join(f"- {table}: {TABLE_FIELDS[table]}" for table in tables)
