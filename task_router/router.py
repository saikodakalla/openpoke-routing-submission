"""Ownership first, retrieval second, conservative explainable verification.

Scores are evidence weights, never probabilities. Similarity alone cannot dispatch.
The router contains no dataset IDs, expected answers, or fixture-specific rules.
"""

from dataclasses import asdict, dataclass, field
import fcntl
import hashlib
import json
import re
import time

from .store import tokens, uid
from . import activity
from .conversation import ConversationResolver
from .verifier import CandidateVerifier
from .providers import ProviderError


@dataclass
class Request:
    text: str
    conversation_id: str = "demo"
    request_id: str = field(default_factory=lambda: uid("request"))
    task_id: str | None = None
    thread_id: str | None = None
    contact_email: str | None = None
    contact_candidates: list[str] = field(default_factory=list)
    start_date: str | None = None
    purpose: str | None = None
    new_work: bool = False
    source: str = "user"
    approval_draft_id: str | None = None
    approval_order_id: str | None = None
    purchase: bool = False


def resolve(request):
    """Extract exact identifiers only. Missing constraints stay unknown."""
    request = Request(**asdict(request))
    if not request.contact_email:
        email = re.search(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", request.text)
        request.contact_email = email[0].lower() if email else None
    if not request.start_date:
        date = re.search(r"\b\d{4}-\d{2}-\d{2}\b", request.text)
        request.start_date = date[0] if date else None
    if not request.task_id:
        match = re.search(r"\btask-[a-zA-Z0-9-]+", request.text)
        request.task_id = match[0] if match else None
    if not request.thread_id:
        match = re.search(r"\bthread-[a-zA-Z0-9-]+", request.text)
        request.thread_id = match[0] if match else None
    if not request.purpose:
        # This small visible intent lexicon is not an embedding model.
        intents = {
            "dining": {"pizza", "lunch", "dinner", "restaurant", "catering"},
            "travel": {"trip", "travel", "flight", "hotel", "vacation", "itinerary"},
            "finance": {"invoice", "budget", "payment", "tax"},
            "project": {"project", "proposal", "release", "design"},
        }
        words = tokens(request.text)
        matches = [purpose for purpose, keywords in intents.items() if words & keywords]
        request.purpose = matches[0] if len(matches) == 1 else None
    return request


class Router:
    def __init__(self, store, index, settings, provider=None):
        self.store, self.index, self.settings = store, index, settings
        self.verifier = CandidateVerifier(store, settings)
        self.conversation = ConversationResolver(store, settings, provider)

    def route(self, request):
        # Cross-process serialization is scoped to a conversation, not the entire app.
        locks = self.store.path.parent / "locks"
        locks.mkdir(exist_ok=True)
        lock = locks / (hashlib.sha256(request.conversation_id.encode()).hexdigest() + ".lock")
        with lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            return self._route(request)

    def _route(self, original):
        started = time.perf_counter()
        existing = self.store.rows(
            "SELECT trace,original_request FROM routing_runs WHERE id=?", (original.request_id,)
        )
        if existing:
            if asdict(Request(**json.loads(existing[0]["original_request"]))) != asdict(original):
                raise ValueError("request_id already belongs to a different request")
            return json.loads(existing[0]["trace"])
        request = resolve(original)
        trace = {
            "request_id": request.request_id,
            "conversation_id": request.conversation_id,
            "mode": self.settings.mode,
            "path": "direct",
            "candidates": [],
            "timings_ms": {},
            "decision": "clarify",
            "task_id": None,
            "owner_id": None,
            "new_agent_created": False,
            "execution": {"status": "not_dispatched"},
            "usage": [],
            "broader_search": False,
        }
        if request.source != "user":
            trace.update(decision="ignored", response="Background status recorded; no new task was routed.")
            return self._persist(original, request, trace, started)
        pending = self.store.rows(
            "SELECT * FROM routing_runs WHERE conversation_id=? AND status='clarify'",
            (request.conversation_id,),
        )
        parent = None
        if pending:
            parent = pending[0]
            previous = Request(**json.loads(parent["resolved_request"]))
            # Answers refine the pending work. The original instruction stays intact.
            for key in (
                "task_id",
                "thread_id",
                "contact_email",
                "start_date",
                "purpose",
                "approval_draft_id",
                "approval_order_id",
            ):
                value = getattr(request, key)
                if value:
                    setattr(previous, key, value)
            previous.text += "\nUser clarification: " + request.text
            previous.request_id = request.request_id
            previous.new_work = request.new_work
            request = resolve(previous)
            trace["parent_id"] = parent["id"]
        facts = self.conversation.prepare(
            request, original.text, json.loads(parent["trace"]) if parent else None
        )
        from .preferences import resolve_purchase

        purchase = resolve_purchase(self.store, request)
        if purchase:
            trace["purchase_evidence"] = purchase["counts"]
            if "response" in purchase:
                trace.update(
                    path="keyword", response=purchase["response"], clarification=purchase["clarification"]
                )
                return self._persist(original, request, trace, started, parent)
        stage = time.perf_counter()
        lookup_operation = activity.begin(
            "lookup", "Checking task ownership", "SQLite · task, thread and conversation links"
        )
        direct = set()
        invalid = []
        if request.task_id:
            t = self.store.task(request.task_id)
            if t and t["state"] != "deleted":
                direct.add(t["id"])
            else:
                invalid.append("The referenced task does not have a current record.")
        if request.thread_id:
            owners = self.store.rows(
                "SELECT task_id FROM threads WHERE id=? AND verified=1", (request.thread_id,)
            )
            if owners:
                direct.update(r["task_id"] for r in owners)
            else:
                invalid.append("This thread has no verified ownership link.")
        followup = re.search(
            r"\b(it|that|same|they|them|follow.up|send it|yes|approve)\b", original.text, re.I
        )
        if not direct and not invalid and followup and not request.new_work and not pending:
            recent = self.store.rows(
                "SELECT task_id FROM conversation_links WHERE conversation_id=? "
                "AND message_id>=? ORDER BY message_id DESC LIMIT 1",
                (request.conversation_id, f"{time.time_ns() - 86_400_000_000_000:020d}"),
            )
            if recent:
                t = self.store.task(recent[0]["task_id"])
                if t and t["state"] != "deleted" and not self._conflicts(request, t):
                    direct.add(t["id"])
                    trace["context_evidence"] = (
                        "Most recent confirmed task in this conversation + explicit follow-up"
                    )
        activity.finish(lookup_operation, "lookup", "Checking task ownership")
        trace["timings_ms"]["lookup"] = (time.perf_counter() - stage) * 1000
        if direct or invalid:
            with activity.step(
                "ownership_check",
                "Verifying explicit ownership",
                "Task/thread links and metadata compatibility",
            ):
                trace["candidates"] = [
                    self.verify(request, self.store.task(t), explicit=True) for t in sorted(direct)
                ]
            compatible = [c for c in trace["candidates"] if not c["conflicts"]]
            if len(direct) == 1 and len(compatible) == 1 and not invalid:
                return self._select(original, request, trace, compatible[0], started, parent)
            trace["response"] = (
                "I couldn't identify that conversation. What is it about?"
                if invalid
                else "I found conflicting conversations. Which plans or conversation do you mean?"
            )
            return self._persist(original, request, trace, started, parent)
        # Try recorded metadata and words before paying for language intake.
        preliminary = self.store.metadata_candidates(request, self.settings.candidate_limit * 3)
        if len(preliminary) <= self.settings.candidate_limit * 3:
            signals = {
                r["task_id"]: {"keyword_rank": r["rank"]}
                for r in self.store.keyword(request.text, self.settings.candidate_limit)
            }
            for record in preliminary:
                signals.setdefault(record["task_id"], {})
            assessed = self._verify_ids(request, signals)
            selected = self._winner(assessed)
            if selected:
                trace.update(
                    path="keyword", candidates=assessed, metadata_ids=[r["task_id"] for r in preliminary]
                )
                return self._select(original, request, trace, selected, started, parent)
        try:
            facts = self.conversation.understand(request, facts)
        except ProviderError as exc:
            trace["retrieval_error"] = str(exc)
            trace["response"] = (
                "Live language understanding isn't configured yet. Add your OpenRouter key to the local .env file and enable live mode."
                if "missing" in str(exc).lower() or "disabled" in str(exc).lower()
                else "I couldn't understand the request because the language service is unavailable. Please retry when the connection is restored."
            )
            return self._persist(original, request, trace, started, parent)
        stage = time.perf_counter()
        metadata = self.store.metadata_candidates(request, self.settings.candidate_limit * 3)
        if len(metadata) > self.settings.candidate_limit * 3:
            trace["response"] = (
                "There are several conversations with this person. What are the plans or conversation about?"
            )
            trace["metadata_overflow"] = True
            return self._persist(original, request, trace, started, parent)
        keywords = self.store.keyword(request.text, self.settings.candidate_limit)
        ids = {r["task_id"]: {"keyword_rank": r["rank"]} for r in keywords}
        for record in metadata:
            ids.setdefault(record["task_id"], {})
        trace["metadata_ids"] = [r["task_id"] for r in metadata]
        trace["path"] = "keyword"
        candidates = self._verify_ids(request, ids)
        selected = self._winner(candidates)
        trace["timings_ms"]["keyword_verify"] = (time.perf_counter() - stage) * 1000
        if selected:
            trace["candidates"] = candidates
            return self._select(original, request, trace, selected, started, parent)
        trace["path"] = "vector"
        stage = time.perf_counter()
        try:
            # Semantic fallback is the only request path allowed to build/repair vectors.
            index_started = time.perf_counter()
            prepared = self.index.ensure_current(request.request_id)
            trace["timings_ms"]["index_prepare"] = (time.perf_counter() - index_started) * 1000
            trace["indexing"] = {"updated_records": prepared, "collection": self.index.name}
            retrieved = self.index.query(
                request.text, self.settings.candidate_limit, request_id=request.request_id
            )
            trace["retrieved_ids"] = [r["task_id"] for r in retrieved]
            for r in retrieved:
                ids.setdefault(r["task_id"], {}).update(r)
            candidates = self._verify_ids(request, ids)
            selected = self._winner(candidates)
            if not selected:
                # Exactly one bounded expansion. Never eliminate contenders until one wins.
                trace["broader_search"] = True
                broader = self.index.query(
                    request.text, self.settings.candidate_limit * 3, request_id=request.request_id
                )
                for r in broader:
                    ids.setdefault(r["task_id"], {}).update(r)
                candidates = self._verify_ids(request, ids)
                selected = self._winner(candidates)
        except Exception as exc:
            trace["retrieval_error"] = f"{type(exc).__name__}: {exc}"
            # Direct ownership remains available during provider outages; no fixture fallback.
            trace["candidates"] = candidates
            trace["response"] = (
                "I couldn’t search saved work right now. Please try again once the connection is restored."
            )
            return self._persist(original, request, trace, started, parent)
        trace["timings_ms"]["vector_verify"] = (time.perf_counter() - stage) * 1000
        trace["candidates"] = candidates[: self.settings.candidate_limit * 3]
        if selected:
            return self._select(original, request, trace, selected, started, parent)
        if request.new_work or self.conversation.can_establish(request, facts, candidates):
            if facts["action"] == "email" and not request.contact_email:
                trace["response"], trace["clarification"] = self.conversation.question([], request, facts)
                return self._persist(original, request, trace, started, parent)
            task_id, created = self.store.establish(
                request.text, request.contact_email, request.purpose, request.start_date
            )
            trace["decision"] = "create" if created else "reuse"
            trace["new_agent_created"] = created
            return self._select(original, request, trace, {"task_id": task_id}, started, parent)
        trace["response"], trace["clarification"] = self.conversation.question(candidates, request, facts)
        return self._persist(original, request, trace, started, parent)

    def _conflicts(self, request, task):
        return self.verifier.conflicts(request, task)

    def verify(self, request, task, **signals):
        return self.verifier.verify(request, task, **signals)

    def _verify_ids(self, request, ids):
        with activity.step("verify", "Verifying task matches"):
            candidates = []
            for task_id, signals in ids.items():
                task = self.store.task(task_id)
                if task and task["state"] != "deleted":
                    candidates.append(self.verify(request, task, **signals))
            candidates = sorted(candidates, key=lambda c: (-c["score"], c["task_id"]))
            activity.note("candidates", "Candidate evidence ready", {"candidates": candidates})
            return candidates

    def _winner(self, candidates):
        return self.verifier.winner(candidates)

    def _select(self, original, request, trace, candidate, started, parent):
        task = self.store.task(candidate["task_id"])
        activity.note(
            "ownership",
            "Using the verified task owner",
            {"task_id": task["id"], "owner": task["legacy_name"]},
        )
        trace.update(
            task_id=task["id"],
            owner_id=task["owner_id"],
            owner=task["legacy_name"],
            task_version=task["version"],
            decision=trace["decision"] if trace["decision"] == "create" else "reuse",
            response="Task ownership verified. Dispatching to " + task["legacy_name"],
        )
        return self._persist(original, request, trace, started, parent)

    def _persist(self, original, request, trace, started, parent=None):
        trace["timings_ms"]["routing_total"] = (time.perf_counter() - started) * 1000
        trace["resolved_request"] = asdict(request)
        trace["verification"] = self.verifier.assessment(trace["candidates"])
        trace["threshold"], trace["ambiguity_margin"] = self.settings.threshold, self.settings.margin
        trace["usage"] = self.store.rows(
            "SELECT kind,model,tokens,cost_bound,usage,status,elapsed_ms FROM provider_calls WHERE request_id=?",
            (request.request_id,),
        )
        if trace["decision"] == "clarify":
            activity.note("clarify", "Waiting for your clarification")
        pending = {
            "original": asdict(original),
            "candidates": trace["candidates"],
            "missing_constraints": [
                k for k in ("task_id", "thread_id", "contact_email", "start_date") if not getattr(request, k)
            ],
        }
        with self.store.connect(write=True) as db:
            if parent:
                db.execute("UPDATE routing_runs SET status='answered' WHERE id=?", (parent["id"],))
            db.execute(
                "INSERT INTO routing_runs(id,conversation_id,original_request,resolved_request,status,trace,pending,parent_id) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    request.request_id,
                    request.conversation_id,
                    json.dumps(asdict(original)),
                    json.dumps(asdict(request)),
                    trace["decision"],
                    json.dumps(trace),
                    json.dumps(pending) if trace["decision"] == "clarify" else None,
                    parent["id"] if parent else None,
                ),
            )
            db.execute(
                "INSERT INTO messages(request_id,conversation_id,role,content) VALUES(?,?,?,?)",
                (request.request_id, request.conversation_id, "user", original.text),
            )
            if trace["task_id"]:
                db.execute(
                    "INSERT INTO conversation_links VALUES(?,?,?,?)",
                    (
                        request.conversation_id,
                        f"{time.time_ns():020d}",
                        trace["task_id"],
                        "verified dispatch",
                    ),
                )
                self.store.event(
                    trace["task_id"],
                    "request",
                    {"text": request.text, "decision": trace["decision"]},
                    request.request_id,
                    db,
                )
            else:
                db.execute(
                    "INSERT INTO messages(request_id,conversation_id,role,content) VALUES(?,?,?,?)",
                    (request.request_id, request.conversation_id, "assistant", trace["response"]),
                )
        return trace
