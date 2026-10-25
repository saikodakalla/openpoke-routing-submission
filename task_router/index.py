"""Persistent Chroma with externally supplied vectors and durable version checks."""

from . import activity
import fcntl
import hashlib
import json
from pathlib import Path
from threading import RLock

import chromadb
from chromadb.config import Settings as ChromaSettings
import numpy as np


class TaskIndex:
    def __init__(self, store, embeddings, path: Path):
        self.store, self.embeddings = store, embeddings
        signature = f"{embeddings.model}:{embeddings.dimension}:summary-v1"
        self.name = "tasks-" + hashlib.sha256(signature.encode()).hexdigest()[:20]
        self.path = Path(path)
        self.client = None
        self._collection = None
        self._lock = RLock()
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT OR IGNORE INTO index_collections VALUES(?,?,?,1)",
                (self.name, embeddings.model, embeddings.dimension),
            )

    def _open(self, create=False):
        """Inspection may load an existing index, but never initializes one."""
        with self._lock:
            if self._collection is not None:
                return self._collection
            if not create and not (self.path / "chroma.sqlite3").exists():
                return None
            if self.client is None:
                self.client = chromadb.PersistentClient(
                    path=str(self.path), settings=ChromaSettings(anonymized_telemetry=False)
                )
            try:
                collection = self.client.get_collection(self.name, embedding_function=None)
            except chromadb.errors.NotFoundError:
                if not create:
                    return None
                collection = self.client.create_collection(
                    self.name,
                    embedding_function=None,
                    metadata={
                        "model": self.embeddings.model,
                        "dimension": self.embeddings.dimension,
                        "summary_version": 1,
                    },
                    configuration={"hnsw": {"space": "cosine"}},
                )
            if (
                collection.metadata["model"] != self.embeddings.model
                or collection.metadata["dimension"] != self.embeddings.dimension
            ):
                raise ValueError("Incompatible index metadata; rebuild in a separate collection")
            self._collection = collection
            return collection

    @property
    def collection(self):
        # Explicit developer access is allowed to initialize; UI reads use _open(False).
        return self._open(create=True)

    def count_existing(self):
        collection = self._open()
        return collection.count() if collection is not None else 0

    def ensure_current(self, request_id=None):
        """Only semantic request handling or explicit CLI indexing calls this."""
        # Serialize the cold build across requests/processes to avoid duplicate paid batches.
        with (self.path.parent / ("." + self.name + ".lock")).open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            return self._ensure_current(request_id)

    def _ensure_current(self, request_id=None):
        if self._open() is None:
            self.schedule(rebuild=True)  # recover a lost disposable Chroma directory
        self.schedule()
        if not self.store.rows(
            "SELECT 1 FROM index_state WHERE collection=? AND indexed_version<>pending_version LIMIT 1",
            (self.name,),
        ):
            return 0
        with activity.step(
            "index", "Preparing semantic task memory", "Pending task cards only; cached embeddings reused"
        ):
            return self.repair(request_id=request_id)

    def schedule(self, rebuild=False):
        with self.store.connect(write=True) as db:
            db.execute(
                "INSERT OR IGNORE INTO index_state(task_id,collection,pending_version) SELECT id,?,version FROM tasks",
                (self.name,),
            )
            if rebuild:
                db.execute(
                    "UPDATE index_state SET indexed_version=0,error=NULL WHERE collection=?", (self.name,)
                )

    def repair(self, batch_size=64, after_upsert=None, request_id=None):
        self.schedule()
        self._open(create=True)
        indexed = 0
        while True:
            rows = self.store.rows(
                "SELECT t.* FROM tasks t JOIN index_state i ON i.task_id=t.id "
                "WHERE i.collection=? AND i.indexed_version<>i.pending_version LIMIT ?",
                (self.name, batch_size),
            )
            if not rows:
                break
            active = [r for r in rows if r["state"] != "deleted"]
            try:
                vectors = self.embeddings.embed([self.card(r) for r in active], request_id) if active else []
                if active:
                    self.collection.upsert(
                        ids=[r["id"] for r in active],
                        embeddings=vectors,
                        documents=[self.card(r) for r in active],
                        metadatas=[
                            {
                                "version": r["version"],
                                "owner_id": r["owner_id"],
                                "state": r["state"],
                                "summary_version": 1,
                            }
                            for r in active
                        ],
                    )
                deleted = [r["id"] for r in rows if r["state"] == "deleted"]
                if deleted:
                    self.collection.delete(ids=deleted)
                if after_upsert:
                    after_upsert()  # testable crash window: replaying upsert is safe
                with self.store.connect(write=True) as db:
                    for r in rows:
                        # A newer summary may arrive while embedding. Never mark it indexed.
                        db.execute(
                            "UPDATE index_state SET indexed_version=?,error=NULL WHERE task_id=? AND collection=?",
                            (r["version"], r["id"], self.name),
                        )
                indexed += len(rows)
            except Exception as exc:
                with self.store.connect(write=True) as db:
                    db.executemany(
                        "UPDATE index_state SET error=? WHERE task_id=? AND collection=?",
                        [(str(exc), r["id"], self.name) for r in rows],
                    )
                raise
        return indexed

    @staticmethod
    def card(task):
        # Contacts/dates/IDs are metadata; they are never hand-assigned vector axes.
        return task["title"] + "\n" + task["summary"]

    def query(self, text, limit=10, where=None, request_id=None):
        if self._open() is None:
            self.ensure_current(request_id)
        if not self.collection.count():
            return []
        with activity.step(
            "embedding",
            "Embedding the request",
            {
                "model": self.embeddings.model,
                "dimension": self.embeddings.dimension,
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                "collection": self.name,
            },
        ):
            vector = self.embeddings.embed([text], request_id)[0]
        with activity.step("vector", "Searching task memory", "Chroma · embedding similarity search"):
            result = self.collection.query(
                query_embeddings=[vector],
                n_results=min(limit, self.collection.count()),
                where=where,
                include=["metadatas", "distances"],
            )
        candidates = []
        for task_id, meta, distance in zip(
            result["ids"][0], result["metadatas"][0], result["distances"][0], strict=True
        ):
            task = self.store.task(task_id)
            if (
                task
                and task["version"] == meta["version"]
                and task["state"] != "deleted"
                and task["owner_id"] == meta["owner_id"]
            ):
                candidates.append(
                    {"task_id": task_id, "similarity": 1 - distance, "version": meta["version"]}
                )
        activity.note(
            "retrieval",
            "Retrieved current task candidates",
            {
                "collection": self.name,
                "candidates": [
                    dict(
                        r,
                        title=self.store.task(r["task_id"])["title"],
                        owner=self.store.task(r["task_id"])["legacy_name"],
                    )
                    for r in candidates
                ],
            },
        )
        return candidates

    def projection(self, limit=800, request_id=None):
        # Inspection reads the already cached request vector. It must never call a provider.
        if self._open() is None:
            return {
                "points": [],
                "deferred": True,
                "model": self.embeddings.model,
                "dimension": self.embeddings.dimension,
                "label": "Semantic memory has not been needed yet. A complex request builds it on demand.",
            }
        query_vector = None
        required = set()
        if request_id:
            events = self.store.rows(
                "SELECT kind,detail FROM request_activity WHERE request_id=? AND status='completed' ORDER BY id",
                (request_id,),
            )
            for event in events:
                detail = json.loads(event["detail"]) if event["detail"] else {}
                if not isinstance(detail, dict) or detail.get("collection") != self.name:
                    continue
                if event["kind"] == "embedding":
                    cached = self.store.rows(
                        "SELECT vector FROM embedding_cache WHERE model=? AND dimension=? AND content_hash=?",
                        (self.embeddings.model, self.embeddings.dimension, detail.get("content_hash")),
                    )
                    if cached:
                        query_vector = json.loads(cached[0]["vector"])
                if event["kind"] == "retrieval":
                    required.update(r["task_id"] for r in detail.get("candidates", []))
        data = self.collection.get(limit=limit, include=["embeddings", "metadatas"])
        # A bounded background sample must not hide a request's actual retrieved candidates.
        missing = sorted(required - set(data["ids"]))
        if missing:
            extra = self.collection.get(ids=missing, include=["embeddings", "metadatas"])
            if extra["ids"]:
                data["ids"].extend(extra["ids"])
                data["metadatas"].extend(extra["metadatas"])
                data["embeddings"] = np.concatenate([data["embeddings"], extra["embeddings"]])
        if not data["ids"]:
            return {"points": [], "label": "PCA of stored vectors; projected distance is not ownership"}
        valid = [(i, self.store.task(task_id)) for i, task_id in enumerate(data["ids"])]
        valid = [
            (i, t)
            for i, t in valid
            if t
            and t["state"] != "deleted"
            and t["version"] == data["metadatas"][i]["version"]
            and t["owner_id"] == data["metadatas"][i]["owner_id"]
        ]
        if not valid:
            return {"points": [], "label": "No current vectors"}
        matrix = np.array([data["embeddings"][i] for i, _ in valid], dtype=float)
        centered = matrix - matrix.mean(axis=0)
        _, singular, axes = np.linalg.svd(centered, full_matrices=False)
        for axis in axes:
            if axis[np.argmax(np.abs(axis))] < 0:
                axis *= -1  # reproducible sign convention
        xy = centered @ axes[:2].T
        if xy.shape[1] == 1:
            xy = np.column_stack([xy[:, 0], np.zeros(len(xy))])
        energy = float((singular[:2] ** 2).sum() / max((singular**2).sum(), 1e-12))
        query = None
        if query_vector is not None:
            q = (np.array(query_vector) - matrix.mean(axis=0)) @ axes[:2].T
            query = {"request_id": request_id, "x": float(q[0]), "y": float(q[1]) if len(q) > 1 else 0.0}
        return {
            "query": query,
            "sampled": self.collection.count() > len(data["ids"]),
            "label": "PCA · actual stored vectors · projected distance is not ownership",
            "model": self.embeddings.model,
            "dimension": matrix.shape[1],
            "explained_variance": energy,
            "collection": self.name,
            "points": [
                {
                    "id": t["id"],
                    "title": t["title"],
                    "owner": t["legacy_name"],
                    "state": t["state"],
                    "x": float(p[0]),
                    "y": float(p[1]),
                }
                for (_, t), p in zip(valid, xy, strict=True)
            ],
        }
