"""Custom deterministic candidate verification, independent of any language model.

Weights are evidence, not probabilities. Hard metadata conflicts veto reuse;
otherwise ownership, a minimum score and a winning margin are all required.
The development configuration is frozen before held-out evaluation.
"""

from .store import tokens


class CandidateVerifier:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings

    def conflicts(self, request, task):
        conflicts = []
        emails = {c["email"].lower() for c in task["contacts"]}
        if request.contact_email and emails and request.contact_email not in emails:
            conflicts.append("contact differs")
        if request.contact_candidates and emails and not emails.intersection(request.contact_candidates):
            conflicts.append("person differs")
        if request.start_date and task["start_date"] and request.start_date != task["start_date"]:
            conflicts.append("date differs")
        if request.purpose and task["purpose"] and request.purpose != task["purpose"]:
            conflicts.append("purpose differs")
        return conflicts

    def verify(self, request, task, explicit=False, similarity=None, keyword_rank=None, **ignored):
        words = tokens(request.text)
        card_words = tokens(task["title"] + " " + task["summary"])
        contact = bool(
            request.contact_email and request.contact_email in {c["email"] for c in task["contacts"]}
        )
        date = bool(request.start_date and request.start_date == task["start_date"])
        purpose = bool(request.purpose and request.purpose == task["purpose"])
        history = self.store.history(task["id"], 4)
        supported = any(len(words & tokens(e["payload"])) >= 3 for e in history)
        components = {
            "explicit_ownership": 20.0 if explicit else 0.0,
            "contact_identity": 3.0 if contact else 0.0,
            "purpose": 2.0 if purpose else 0.0,
            "date": 3.0 if date else 0.0,
            "keyword": round(2 * len(words & card_words) / max(len(words), 1), 3),
            "vector": round(1.5 * max(0, similarity or 0), 3),
            "history": 0.5 if supported else 0.0,
            "state": -0.5 if task["state"] == "failed" else 0.0,
        }
        conflicts = self.conflicts(request, task)
        # Shared names, state, recency and similarity cannot independently establish ownership.
        # Contact + a broad category such as "social" is insufficient for a different subject.
        boilerplate = {
            "draft",
            "write",
            "email",
            "message",
            "note",
            "send",
            "reply",
            "please",
            "user",
            "clarification",
            "an",
            "a",
            "plan",
            "about",
        }
        names = {word for c in task["contacts"] for word in tokens(c["name"])}
        subject_overlap = bool((words - boilerplate - names) & (card_words - boilerplate - names))
        subject_supported = subject_overlap or (
            similarity is not None and similarity >= self.settings.topic_similarity_min
        )
        ownership_supported = (
            explicit
            or (contact and (date or (purpose and subject_supported)))
            or (date and purpose and supported)
        )
        return {
            "task_id": task["id"],
            "title": task["title"],
            "owner_id": task["owner_id"],
            "owner": task["legacy_name"],
            "state": task["state"],
            "version": task["version"],
            "contacts": task["contacts"],
            "start_date": task["start_date"],
            "threads": task["threads"],
            "score": round(sum(components.values()), 3),
            "components": components,
            "similarity": similarity,
            "keyword_rank": keyword_rank,
            "ownership_supported": ownership_supported,
            "subject_supported": subject_supported,
            "conflicts": conflicts,
            "evidence": history if supported or explicit else [],
        }

    def winner(self, candidates):
        eligible = sorted(
            (c for c in candidates if not c["conflicts"]), key=lambda c: (-c["score"], c["task_id"])
        )
        if not eligible:
            return None
        best = eligible[0]
        second = eligible[1]["score"] if len(eligible) > 1 else 0
        return (
            best
            if (
                best["ownership_supported"]
                and best["score"] >= self.settings.threshold
                and best["score"] - second >= self.settings.margin
            )
            else None
        )

    def assessment(self, candidates):
        eligible = sorted(
            (c for c in candidates if not c["conflicts"]), key=lambda c: (-c["score"], c["task_id"])
        )
        best = eligible[0] if eligible else None
        runner = eligible[1]["score"] if len(eligible) > 1 else 0
        checks = {
            "compatible_metadata": bool(best),
            "ownership_evidence": bool(best and best["ownership_supported"]),
            "score_threshold": bool(best and best["score"] >= self.settings.threshold),
            "ambiguity_margin": bool(best and best["score"] - runner >= self.settings.margin),
        }
        return {
            "engine": "deterministic-evidence-v1",
            "checks": checks,
            "best_score": best["score"] if best else None,
            "runner_up_score": runner,
            "actual_margin": round(best["score"] - runner, 3) if best else None,
            "threshold": self.settings.threshold,
            "required_margin": self.settings.margin,
            "accepted": all(checks.values()),
            "rejected_conflicts": sum(bool(c["conflicts"]) for c in candidates),
            "note": "Hard conflicts veto. All four checks must pass. Scores are not probabilities.",
        }
