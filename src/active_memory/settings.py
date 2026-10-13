import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MEMORY_", extra="ignore")
    scope: str = "personal:owner"
    backend: str = "reference"
    data_dir: Path = Path("data")
    clients_file: Path = Path("config/clients.json")
    api_key: str = ""  # single-owner fallback; use separate hashed client keys on deployment
    host: str = "127.0.0.1"
    port: int = 8080
    worker_enabled: bool = True
    poll_seconds: float = Field(default=1, ge=0.1)
    extraction_mode: str = "provided"
    allow_model_calls: bool = False
    graphiti_enabled: bool = False
    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: str = ""
    model_name: str = "gpt-4.1-mini"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"
    # AM-003 link proposals. lexical = offline signals only; embedding adds provider vectors.
    similarity_mode: str = "lexical"
    proposal_threshold: float | None = Field(
        default=None, ge=0.1, le=1
    )  # 0.5 lexical, 0.6 embedding
    judge_enabled: bool = False
    max_judge_calls: int = Field(default=20, ge=0, le=500)
    auto_propose: bool = False
    timeout_seconds: int = Field(default=120, ge=5, le=600)

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.backend not in {"reference", "neo4j"}:
            raise ValueError("backend must be reference or neo4j")
        if self.extraction_mode not in {"provided", "llm"}:
            raise ValueError("extraction_mode must be provided or llm")
        if self.graphiti_enabled and self.backend != "neo4j":
            raise ValueError("Graphiti requires Neo4j")
        if (self.graphiti_enabled or self.extraction_mode == "llm") and not self.allow_model_calls:
            raise ValueError("explicit MEMORY_ALLOW_MODEL_CALLS=true required")
        if (self.graphiti_enabled or self.extraction_mode == "llm") and not self.model_api_key:
            raise ValueError("model_api_key required (local endpoints may use a placeholder)")
        if self.graphiti_enabled and not self.embedding_api_key:
            raise ValueError("embedding_api_key required")
        if self.similarity_mode not in {"lexical", "embedding"}:
            raise ValueError("similarity_mode must be lexical or embedding")
        if (self.similarity_mode == "embedding" or self.judge_enabled) and not (
            self.allow_model_calls
        ):
            raise ValueError("explicit MEMORY_ALLOW_MODEL_CALLS=true required")
        if self.similarity_mode == "embedding" and not self.embedding_api_key:
            raise ValueError("embedding_api_key required for embedding similarity")
        if self.judge_enabled and not self.model_api_key:
            raise ValueError("model_api_key required for the relation judge")
        if self.backend == "neo4j" and not self.neo4j_password:
            raise ValueError("neo4j_password required")
        if not self.scope.startswith("personal:"):
            raise ValueError("v0.1 supports one personal scope per deployment")
        return self

    @property
    def effective_threshold(self):
        if self.proposal_threshold is not None:
            return self.proposal_threshold
        return 0.6 if self.similarity_mode == "embedding" else 0.5

    def clients(self):
        if self.clients_file.exists():
            clients = json.loads(self.clients_file.read_text())
        elif len(self.api_key) >= 24:
            clients = [
                {
                    "id": "owner",
                    "key_sha256": hashlib.sha256(self.api_key.encode()).hexdigest(),
                    "permissions": ["read", "write", "admin"],
                }
            ]
        else:
            raise ValueError("configure clients.json or a MEMORY_API_KEY of at least 24 characters")
        if not clients:
            raise ValueError("empty clients configuration")
        for client in clients:
            digest = client.get("key_sha256", "")
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("client keys must be SHA-256 hex hashes")
            if not set(client.get("permissions", [])) <= {"read", "write", "admin"}:
                raise ValueError("unknown client permission")
        return clients
