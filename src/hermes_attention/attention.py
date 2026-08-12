from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from .calendar import CalendarStore
from .continuations import ContinuationStore
from .db import iso, parse_time, stable_id, utc_now
from .inbox import InboxStore, PRIORITIES
from .tasks import TaskStore


SCHEMA = "attention_opportunity_set.v1"
WEIGHTS = {
    "urgency": 0.34,
    "owner_impact": 0.25,
    "continuity_affinity": 0.18,
    "freshness": 0.11,
    "bounded_aging": 0.08,
    "provider_priority": 0.04,
}
PRIORITY_FEATURE = {
    "critical": 1.0,
    "urgent": 0.9,
    "high": 0.7,
    "normal": 0.4,
    "low": 0.15,
}


@dataclass(frozen=True)
class Candidate:
    source_kind: str
    source_id: str
    source_version: str
    review_version: str
    title: str
    summary: str
    event_at: datetime
    subject_ref: str
    urgency: float
    owner_impact: float
    continuity_affinity: float
    provider_priority_hint: str = "normal"
    provider_id: str = ""
    capability_hints: Sequence[str] = field(default_factory=tuple)
    context: Mapping[str, Any] = field(default_factory=dict)

    @property
    def opportunity_id(self) -> str:
        return stable_id("opp", self.source_kind, self.source_id, self.source_version)


class InboxCandidates:
    def __init__(self, store: InboxStore):
        self.store = store

    def candidates(self, now: datetime) -> Iterable[Candidate]:
        for row in self.store.due(now=now):
            priority = row["priority_hint"] if row["priority_hint"] in PRIORITIES else "normal"
            yield Candidate(
                source_kind="provider_event",
                source_id=row["event_id"],
                source_version=row["source_version"],
                review_version=self.store.review_version(row, now),
                title=row["title"],
                summary=_compact_summary(row["compact_payload"]),
                event_at=parse_time(row["event_at"]) or now,
                subject_ref=row["subject_ref"],
                urgency=0.52,
                owner_impact=0.48,
                continuity_affinity=0.72 if row["followup_of"] else 0.45,
                provider_priority_hint=priority,
                provider_id=row["provider_id"],
                capability_hints=tuple(row["capability_hints"]),
                context={
                    "event_kind": row["event_kind"],
                    "compact_payload": row["compact_payload"],
                    "source_refs": row["source_refs"],
                    "instruction_status": "context_only",
                },
            )


class ContinuationCandidates:
    def __init__(self, store: ContinuationStore):
        self.store = store

    def candidates(self, now: datetime) -> Iterable[Candidate]:
        for row in self.store.due(now=now):
            yield Candidate(
                source_kind="continuation",
                source_id=row["continuation_id"],
                source_version=row["source_version"],
                review_version=self.store.review_version(row, now),
                title=row["goal"],
                summary=row["stage"],
                event_at=parse_time(row["due_at"]) or now,
                subject_ref=row["causal_root_id"] or row["parent_ref"],
                urgency=0.58,
                owner_impact=0.62,
                continuity_affinity=0.96,
                capability_hints=tuple(row["capability_refs"]),
                context={"stage": row["stage"], "source_refs": row["source_refs"]},
            )


class TaskCandidates:
    def __init__(self, store: TaskStore):
        self.store = store

    def candidates(self, now: datetime) -> Iterable[Candidate]:
        for row in self.store.due(now=now):
            reason = row["attention_reason"]
            urgency = {
                "expired": 0.94,
                "overdue": 0.86,
                "warning": 0.42 + 0.38 * row["due_proximity"],
                "blocked": 0.78,
                "pinned": 0.72,
                "next_check": 0.62,
                "new_cycle": 0.48,
                "new": 0.48,
                "changed": 0.58,
            }.get(reason, 0.5)
            yield Candidate(
                source_kind="ongoing",
                source_id=row["task_id"],
                source_version=row["source_version"],
                review_version=row["review_version"],
                title=row["title"],
                summary=row["summary"],
                event_at=parse_time(row["semantic_changed_at"]) or now,
                subject_ref=row["parent_task_id"] or row["task_id"],
                urgency=urgency,
                owner_impact=0.72,
                continuity_affinity=0.82,
                context={
                    "task_kind": row["kind"],
                    "attention_reason": reason,
                    "due_at": row["due_at"],
                    "form_schema": row["form_schema"],
                },
            )


def _compact_summary(payload: Mapping[str, Any]) -> str:
    parts = []
    for key, value in list(payload.items())[:6]:
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}={value}")
    return "; ".join(parts)[:360]


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class AttentionCoordinator:
    """Candidate merger and transaction coordinator over source-owned APIs.

    It does not implement source-table SQL. It knows the four product-owned
    stores, never provider transports or tool schemas. New external systems
    enter Inbox without changing scoring.
    """

    def __init__(
        self,
        *,
        calendar: CalendarStore,
        inbox: InboxStore,
        continuations: ContinuationStore,
        tasks: TaskStore,
    ):
        self.calendar = calendar
        self.inbox = inbox
        self.continuations = continuations
        self.tasks = tasks
        self.providers = (
            InboxCandidates(inbox),
            ContinuationCandidates(continuations),
            TaskCandidates(tasks),
        )
        self._owners = {
            "calendar": calendar,
            "provider_event": inbox,
            "continuation": continuations,
            "ongoing": tasks,
        }

    def build(self, *, now: datetime | None = None, limit: int = 12) -> dict[str, Any]:
        current = now or utc_now()
        direct = self.calendar.due_direct(now=current)
        if direct:
            row = direct[0]
            return {
                "schema": SCHEMA,
                "built_at": iso(current),
                "direct_trigger": {
                    "source_kind": "calendar",
                    "source_id": row["item_id"],
                    "source_version": row["source_version"],
                    "review_version": self.calendar.review_version(row, current),
                    "reason": "schedule_due",
                    "title": row["title"],
                    "context_note": row["context_note"],
                    "capability_hints": row["capability_refs"],
                },
                "eligible_count": 0,
                "eligible_membership": [],
                "review_id": stable_id("review", "direct"),
                "review_limit": max(1, limit),
                "review_membership": [],
                "opportunities": [],
                "weights": WEIGHTS,
            }

        ranked = [self._rank(item, current) for provider in self.providers for item in provider.candidates(current)]
        ranked.sort(key=lambda item: (-item["score"], item["event_at"], item["opportunity_id"]))
        review_limit = max(1, limit)
        selected = self._diverse(ranked, review_limit)
        eligible_membership = self._membership(ranked, include_review_version=False)
        review_membership = self._membership(selected, include_review_version=True)
        return {
            "schema": SCHEMA,
            "set_id": self._membership_id("aos", eligible_membership),
            "review_id": self._membership_id("review", review_membership),
            "built_at": iso(current),
            "direct_trigger": None,
            "eligible_count": len(ranked),
            "eligible_membership": eligible_membership,
            "prompt_count": len(selected),
            "review_limit": review_limit,
            "review_membership": review_membership,
            "weights": WEIGHTS,
            "opportunities": selected,
        }

    @staticmethod
    def _membership(
        items: Sequence[Mapping[str, Any]],
        *,
        include_review_version: bool,
    ) -> list[dict[str, str]]:
        return sorted(
            (
                {
                    "opportunity_id": str(item["opportunity_id"]),
                    "source_kind": str(item["source_kind"]),
                    "source_id": str(item["source_id"]),
                    "source_version": str(item["source_version"]),
                    **(
                        {"review_version": str(item["review_version"])}
                        if include_review_version
                        else {}
                    ),
                }
                for item in items
            ),
            key=lambda member: (
                member["source_kind"],
                member["source_id"],
                member["source_version"],
            ),
        )

    @staticmethod
    def _membership_id(prefix: str, members: Sequence[Mapping[str, str]]) -> str:
        identity = [
            ":".join(
                (
                    member["source_kind"],
                    member["source_id"],
                    member["source_version"],
                    member.get("review_version", ""),
                )
            )
            for member in members
        ]
        return stable_id(prefix, *(identity or ["empty"]))

    def _rank(self, candidate: Candidate, now: datetime) -> dict[str, Any]:
        age_hours = max(0.0, (now - candidate.event_at).total_seconds() / 3600)
        features = {
            "urgency": _bounded(candidate.urgency),
            "owner_impact": _bounded(candidate.owner_impact),
            "continuity_affinity": _bounded(candidate.continuity_affinity),
            "freshness": max(0.0, 1.0 - age_hours / 24.0),
            "bounded_aging": min(1.0, age_hours / 72.0),
            "provider_priority": PRIORITY_FEATURE.get(candidate.provider_priority_hint, 0.4),
        }
        score = sum(WEIGHTS[key] * value for key, value in features.items())
        return {
            "opportunity_id": candidate.opportunity_id,
            "source_kind": candidate.source_kind,
            "source_id": candidate.source_id,
            "source_version": candidate.source_version,
            "review_version": candidate.review_version,
            "title": candidate.title,
            "summary": candidate.summary,
            "event_at": iso(candidate.event_at),
            "subject_ref": candidate.subject_ref,
            "provider_id": candidate.provider_id,
            "provider_priority_hint": candidate.provider_priority_hint,
            "capability_hints": list(candidate.capability_hints),
            "context": dict(candidate.context),
            "features": {key: round(value, 6) for key, value in features.items()},
            "score": round(score, 6),
        }

    @staticmethod
    def _diverse(ranked: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        chosen = []
        providers: dict[str, int] = {}
        subjects: dict[str, int] = {}
        for item in ranked:
            provider = item["provider_id"]
            subject = item["subject_ref"]
            if provider and providers.get(provider, 0) >= 2:
                continue
            if subject and subjects.get(subject, 0) >= 2:
                continue
            chosen.append(item)
            providers[provider] = providers.get(provider, 0) + 1
            subjects[subject] = subjects.get(subject, 0) + 1
            if len(chosen) >= limit:
                break
        return chosen

    def claim_exact(
        self,
        source_kind: str,
        source_id: str,
        source_version: str,
        review_version: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        owner = self._owners.get(source_kind)
        if owner is None:
            return {"claimed": False, "reason": "unknown_source_owner"}
        result = owner.claim_exact(
            source_id, source_version, review_version, now=now
        )
        if result.get("claimed"):
            result["source_kind"] = source_kind
        return result

    def settle(
        self,
        source_kind: str,
        claim_token: str,
        outcome: str,
        *,
        result: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        owner = self._owners.get(source_kind)
        if owner is None:
            return {"settled": False, "reason": "unknown_source_owner"}
        return owner.settle(claim_token, outcome, result=result, now=now)

    def validate_claim(
        self,
        source_kind: str,
        claim_token: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        owner = self._owners.get(source_kind)
        if owner is None:
            return {"valid": False, "reason": "unknown_source_owner"}
        return owner.validate_claim(claim_token, now=now)

    def quiet_set(
        self,
        set_id: str,
        review_id: str,
        *,
        review_limit: int = 12,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically close only the exact bounded subset the Agent reviewed."""
        current = now or utc_now()
        built = self.build(now=current, limit=review_limit)
        if built.get("direct_trigger"):
            return {"settled": False, "reason": "direct_trigger_requires_exact_focus"}
        if not built.get("eligible_count"):
            return {"settled": False, "reason": "set_empty"}
        if str(built.get("set_id") or "") != str(set_id or ""):
            return {"settled": False, "reason": "set_changed"}
        if str(built.get("review_id") or "") != str(review_id or ""):
            return {"settled": False, "reason": "review_changed"}
        members = list(built.get("review_membership") or [])
        database = self.inbox.database
        receipts: list[str] = []
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            frozen: list[tuple[Any, Any, Mapping[str, Any]]] = []
            for member in members:
                owner = self._owners.get(str(member.get("source_kind") or ""))
                if owner is None:
                    connection.rollback()
                    return {"settled": False, "reason": "unknown_source_owner"}
                row, reason = owner.freeze_available_in_tx(
                    connection,
                    str(member.get("source_id") or ""),
                    str(member.get("source_version") or ""),
                    str(member.get("review_version") or ""),
                    current,
                )
                if row is None:
                    connection.rollback()
                    return {"settled": False, "reason": reason}
                frozen.append((owner, row, member))
            for owner, row, member in frozen:
                result = {
                    "set_id": set_id,
                    "review_id": review_id,
                    "scope": "review_membership",
                }
                receipt_id = owner.settle_row_in_tx(
                    connection,
                    row,
                    "quiet",
                    result=result,
                    receipt_scope=f"{set_id}:{review_id}",
                    now=current,
                    increment_generation=True,
                )
                receipts.append(receipt_id)
            connection.commit()
        return {
            "settled": True,
            "set_id": set_id,
            "review_id": review_id,
            "scope": "review_membership",
            "member_count": len(frozen),
            "receipt_ids": receipts,
        }

    def defer(
        self,
        source_kind: str,
        claim_token: str,
        *,
        goal: str,
        stage: str,
        due_at: datetime,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically settle one selected source into one Continuation."""
        owner = self._owners.get(source_kind)
        if owner is None:
            return {"deferred": False, "reason": "unknown_source_owner"}
        current = now or utc_now()
        if due_at <= current:
            raise ValueError("due_at must be in the future")
        database = self.inbox.database
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row, reason = owner.current_claim_in_tx(connection, claim_token, current)
            if row is None:
                connection.commit()
                return {"deferred": False, "reason": reason}
            source_id = owner.row_id(row)
            continuation = self.continuations.create_in_tx(
                connection,
                goal=goal,
                stage=stage,
                due_at=due_at,
                causal_root_id=source_id,
                parent_ref=f"{source_kind}:{source_id}",
                source_refs=(f"{source_kind}:{source_id}",),
                now=current,
            )
            continuation_id = str(continuation["continuation_id"])
            receipt_result = {"continuation_id": continuation_id, "due_at": iso(due_at)}
            receipt_id = owner.settle_row_in_tx(
                connection,
                row,
                "scheduled",
                result=receipt_result,
                receipt_scope=str(row["claim_generation"]),
                now=current,
            )
            connection.commit()
        return {
            "deferred": True,
            "source_kind": source_kind,
            "source_id": source_id,
            "continuation_id": continuation_id,
            "receipt_id": receipt_id,
        }
