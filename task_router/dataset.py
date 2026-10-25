"""Synthetic records only. Labels live separately in benchmarks/scenarios.json.

The curated collisions exercise ownership; generated distractors scale roster size.
Neither router nor providers import this module.
"""

import random

SEED = 27

# title, summary, contact, purpose, date, state
CORE = [
    (
        "Hawaii · Alice Chen · February",
        "Plan Hawaii vacation flights and a beachfront hotel with Alice Chen.",
        "alice.chen@example.test",
        "travel",
        "2027-02-12",
        "active",
    ),
    (
        "Hawaiian pizza · Alice Chen",
        "Coordinate pineapple pizza catering for the design team lunch.",
        "alice.chen@example.test",
        "dining",
        "2026-11-04",
        "active",
    ),
    (
        "Hawaii · Alice Morgan · February",
        "Book Hawaii trip hotel and island excursions with Alice Morgan.",
        "alice.morgan@example.test",
        "travel",
        "2027-02-12",
        "active",
    ),
    (
        "Hawaii · Alice Chen · June",
        "Plan another Hawaii vacation, summer flights and a quiet hotel with Alice Chen.",
        "alice.chen@example.test",
        "travel",
        "2027-06-20",
        "active",
    ),
    (
        "Kyoto autumn reunion",
        "Arrange an autumn reunion in Kyoto, travel tickets and a traditional inn with Kenji.",
        "kenji@example.test",
        "travel",
        "2025-10-08",
        "dormant",
    ),
    (
        "Orion invoice review",
        "Review overdue Orion supplier invoice and reconcile quarterly payment with Priya.",
        "priya@example.test",
        "finance",
        "2026-11-08",
        "awaiting_approval",
    ),
    (
        "Coastal retreat",
        "Organize a seaside escape, accommodation and air tickets with Noor.",
        "noor@example.test",
        "travel",
        "2027-03-10",
        "active",
    ),
    (
        "Atlas proposal",
        "Draft Atlas project proposal and accessibility design review with Sam.",
        "sam@example.test",
        "project",
        "2026-12-01",
        "active",
    ),
    (
        "Berlin train expedition",
        "Review Berlin travel rail tickets and lodging with Marta.",
        "marta@example.test",
        "travel",
        "2027-05-09",
        "failed",
    ),
    (
        "Hawaii archival receipts",
        "Hawaii trip expense invoice reconciliation with Alice Chen.",
        "alice.chen@example.test",
        "finance",
        "2024-01-10",
        "completed",
    ),
    (
        "Hawaii lodging alternatives",
        "Hawaii vacation hotel comparison and flights for backup group itinerary.",
        "group@example.test",
        "travel",
        "2027-02-12",
        "active",
    ),
    (
        "Legacy disconnected work",
        "Historical project notes without a verified thread link.",
        "legacy@example.test",
        "project",
        "2026-01-01",
        "dormant",
    ),
]


def seed(store, size=600, seed_value=SEED):
    if size < len(CORE):
        raise ValueError(f"Use at least {len(CORE)} tasks")
    if store.rows("SELECT id FROM tasks LIMIT 1"):
        raise ValueError("Refusing to overwrite existing records; reset the isolated demo explicitly")
    rng = random.Random(seed_value)
    records = list(CORE)
    destinations = ["Lisbon", "Oslo", "Toronto", "Seoul", "Lima", "Nairobi", "Porto", "Vienna"]
    for i in range(len(records), size):
        place = rng.choice(destinations)
        purpose = rng.choice(["travel", "dining", "finance", "project"])
        item = {
            "travel": "flight hotel trip",
            "dining": "restaurant team dinner",
            "finance": "invoice payment review",
            "project": "project release proposal",
        }[purpose]
        records.append(
            (
                f"{place} {item} {i}",
                f"Coordinate {item} for {place} with collaborator {i}; reference plan {rng.randrange(10000)}.",
                f"person{i}@example.test",
                purpose,
                f"2027-{rng.randrange(1, 13):02d}-{rng.randrange(1, 28):02d}",
                rng.choice(["active", "dormant", "completed"]),
            )
        )
    with store.connect(write=True) as db:
        for i, (title, summary, email, purpose, date, state) in enumerate(records, 1):
            task_id, owner = f"task-{i:04d}", f"agent-{i:04d}"
            name = "Email to Alice" if i == 1 else "Execution: " + title
            db.execute(
                "INSERT INTO agents(id,legacy_name,history_ref) VALUES(?,?,?)",
                (owner, name, f"sqlite:task_events/{task_id}"),
            )
            db.execute(
                "INSERT INTO tasks(id,owner_id,title,summary,purpose,state,start_date) VALUES(?,?,?,?,?,?,?)",
                (task_id, owner, title, summary, purpose, state, date),
            )
            contact_id = "contact-" + email
            name = email.split("@")[0].replace(".", " ").title()
            db.execute("INSERT OR IGNORE INTO contacts VALUES(?,?,?)", (contact_id, name, email))
            db.execute("INSERT INTO task_contacts VALUES(?,?)", (task_id, contact_id))
            db.execute(
                "INSERT INTO threads(id,task_id,subject,recipient,verified) VALUES(?,?,?,?,?)",
                (f"thread-{i:04d}", task_id, title, email, 0 if i == 12 else 1),
            )
            store.event(
                task_id,
                "ownership",
                {
                    "owner_id": owner,
                    "thread_id": f"thread-{i:04d}",
                    "contact": email,
                    "purpose": purpose,
                    "date": date,
                },
                db=db,
            )
            store.event(
                task_id,
                "history",
                {"text": summary, "action": "Earlier synthetic draft discussed; no email sent."},
                db=db,
            )
        db.execute(
            "INSERT INTO commitments(id,task_id,owner_id,due_at,payload) VALUES(?,?,?,?,?)",
            (
                "reminder-dormant",
                "task-0005",
                "agent-0005",
                "2027-01-01T09:00:00Z",
                "Review reunion follow-up",
            ),
        )
    return {"tasks": size, "seed": seed_value, "synthetic": True}


SAMPLES = [
    {"label": "Known thread", "text": "Draft a follow-up in thread-0001", "thread_id": "thread-0001"},
    {"label": "Two Alices", "text": "Draft an email to Alice about the Hawaii trip"},
    {
        "label": "Travel vs. pizza",
        "text": "Draft the pizza lunch note for alice.chen@example.test",
        "purpose": "dining",
    },
    {
        "label": "Dormant work",
        "text": "Draft a follow-up for the Kyoto trip to kenji@example.test",
        "purpose": "travel",
    },
    {"label": "Vector fallback", "text": "Ask about the seaside escape and air tickets"},
    {
        "label": "New work",
        "text": "Draft a new proposal to riley@example.test for the observatory project",
        "new_work": True,
    },
]


def seed_showcase(store, size=100):
    """Separate reproducible dataset; never overwrites the user's existing registry.

    Vendor names are data. Runtime routing reads categories, aliases and completed
    receipts, including cancellations which must not inflate preference counts.
    """
    import json

    if size < 14:
        raise ValueError("The showcase needs at least 14 tasks")
    result = seed(store, size)
    with store.connect(write=True) as db:
        for number, name, aliases, items in (
            (13, "Domino's", ["dominoes", "dominos", "domino's"], "Medium thin-crust margherita"),
            (14, "Pizza Pizza", ["pizza pizza"], "Large vegetarian pizza"),
        ):
            task_id, merchant = f"task-{number:04d}", f"merchant-{number}"
            summary = f"Past pizza orders from {name}; saved repeat basket: {items}."
            db.execute(
                "UPDATE tasks SET title=?,summary=?,purpose='dining',state='active',start_date=NULL,version=version+1 WHERE id=?",
                (f"Pizza orders · {name}", summary, task_id),
            )
            db.execute(
                "UPDATE agents SET legacy_name=? WHERE id=(SELECT owner_id FROM tasks WHERE id=?)",
                ("Orders: " + name, task_id),
            )
            db.execute(
                "INSERT INTO merchants VALUES(?,?,?,?,?)",
                (merchant, name, "pizza", json.dumps(aliases), task_id),
            )
            for i in range(2):
                db.execute(
                    "INSERT INTO orders VALUES(?,?,?,?,?,?)",
                    (
                        f"order-{number}-{i}",
                        merchant,
                        task_id,
                        items,
                        f"2026-10-{10 + i:02d}T18:00:00Z",
                        "completed",
                    ),
                )
            db.execute(
                "INSERT INTO orders VALUES(?,?,?,?,?,?)",
                (f"cancel-{number}", merchant, task_id, items, "2026-10-13T18:00:00Z", "cancelled"),
            )
            store.event(task_id, "history", {"text": summary, "synthetic": True}, db=db)
    return dict(result, dataset="daily-life-showcase-v1", completed_orders=4)
