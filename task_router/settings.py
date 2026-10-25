"""Configuration is server-owned. Offline never reads or uses a credential."""

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class RoutingSettings:
    data_dir: Path = Path("data/demo")
    mode: str = "offline"
    embedding_model: str = "fixture-hash-v1"
    dimension: int = 256
    chat_model: str = "openai/gpt-4o-mini"
    candidate_limit: int = 10
    threshold: float = 5.0
    margin: float = 1.25
    topic_similarity_min: float = 0.60
    timeout: float = 25.0
    retries: int = 2
    max_calls: int = 100
    max_tokens: int = 100000
    max_cost: float = 1.0
    max_output: int = 700
    # Conservative configurable reservation rates, USD per million tokens.
    input_rate: float = 5.0
    output_rate: float = 20.0
    embedding_rate: float = 1.0
    allow_live: bool = False
    execution_url: str | None = None
    bridge_token: str = ""

    @classmethod
    def from_env(cls):
        # CLI and server must load the same server-side .env settings.
        # A backend-only dotenv file, with process environment taking precedence.
        env_file = Path(os.getenv("OPENPOKE_ENV_FILE", ".env"))
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        mode = os.getenv("OPENPOKE_MODE", "offline")
        if mode not in {"offline", "live"}:
            raise ValueError("OPENPOKE_MODE must be offline or live")
        return cls(
            data_dir=Path(os.getenv("OPENPOKE_DATA_DIR", f"data/{mode}")),
            mode=mode,
            execution_url=os.getenv("OPENPOKE_EXECUTION_URL", "http://127.0.0.1:8004"),
            bridge_token=os.getenv("OPENPOKE_BRIDGE_TOKEN", ""),
            embedding_model=(
                "fixture-hash-v1"
                if mode == "offline"
                else os.getenv("OPENPOKE_EMBEDDING_MODEL", "openai/text-embedding-3-small")
            ),
            dimension=(256 if mode == "offline" else int(os.getenv("OPENPOKE_EMBEDDING_DIM", "1536"))),
            chat_model=os.getenv("OPENPOKE_CHAT_MODEL", "openai/gpt-4o-mini"),
            candidate_limit=int(os.getenv("OPENPOKE_CANDIDATE_LIMIT", "10")),
            topic_similarity_min=float(os.getenv("OPENPOKE_TOPIC_SIMILARITY_MIN", "0.60")),
            allow_live=os.getenv("OPENPOKE_ALLOW_LIVE", "0") == "1",
            max_calls=int(os.getenv("OPENPOKE_MAX_CALLS", "100")),
            max_tokens=int(os.getenv("OPENPOKE_MAX_TOKENS", "100000")),
            max_cost=float(os.getenv("OPENPOKE_MAX_COST_USD", "1")),
            timeout=float(os.getenv("OPENPOKE_PROVIDER_TIMEOUT", "25")),
            input_rate=float(os.getenv("OPENPOKE_INPUT_USD_PER_M", "5")),
            output_rate=float(os.getenv("OPENPOKE_OUTPUT_USD_PER_M", "20")),
            embedding_rate=float(os.getenv("OPENPOKE_EMBED_USD_PER_M", "1")),
        )
