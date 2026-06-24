from __future__ import annotations

from pydantic import BaseModel, Field


class ResourceCheck(BaseModel):
    ok: bool
    missing: dict[str, int] = Field(default_factory=dict)


class ResourceLedgerEntry(BaseModel):
    entity_id: str
    resource: str
    before: int
    delta: int
    after: int
    reason: str


def check_resources(
    available: dict[str, int],
    required: dict[str, int],
) -> ResourceCheck:
    missing = {
        resource: amount - available.get(resource, 0)
        for resource, amount in required.items()
        if available.get(resource, 0) < amount
    }
    return ResourceCheck(ok=not missing, missing=missing)


def merge_requirements(*requirements: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for requirement in requirements:
        for resource, amount in requirement.items():
            merged[resource] = max(merged.get(resource, 0), amount)
    return merged


def apply_resource_delta(
    resources: dict[str, int],
    resource: str,
    delta: int,
    *,
    floor: int = 0,
) -> tuple[int, int]:
    before = resources.get(resource, 0)
    after = max(floor, before + delta)
    resources[resource] = after
    return before, after


def apply_resource_effects(
    entity_id: str,
    resources: dict[str, int],
    effects: dict[str, int],
    *,
    reason: str,
) -> list[ResourceLedgerEntry]:
    entries: list[ResourceLedgerEntry] = []
    for resource, delta in effects.items():
        before, after = apply_resource_delta(resources, resource, delta)
        entries.append(
            ResourceLedgerEntry(
                entity_id=entity_id,
                resource=resource,
                before=before,
                delta=delta,
                after=after,
                reason=reason,
            )
        )
    return entries
