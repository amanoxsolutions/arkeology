"""Configuration model for cairn-mcp.

All configuration is read from environment variables once at startup.
The Settings object is constructed in __main__.py and passed through
dependency injection — it is never re-read from the environment mid-session.
Each field carries a description with its type, default, and constraints.
"""

from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})


class Settings(BaseSettings):
    """All configuration for the cairn-mcp server, sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=True,
        # Allow extra fields to avoid failures if unexpected env vars are set
        extra="ignore",
    )

    # ── Required ──────────────────────────────────────────────────────────────

    AWS_REGION: Annotated[
        str,
        Field(description="AWS region for all API calls (e.g. us-east-1)"),
    ]

    ARTIFACT_BUCKET: Annotated[
        str,
        Field(description="S3 bucket name for artifact content storage"),
    ]

    VECTORS_BUCKET: Annotated[
        str,
        Field(description="S3 Vectors bucket name"),
    ]

    VECTORS_INDEX: Annotated[
        str,
        Field(description="S3 Vectors index name within the vectors bucket"),
    ]

    # ── Optional ──────────────────────────────────────────────────────────────

    AWS_PROFILE: Annotated[
        str | None,
        Field(
            default=None,
            description="Named AWS profile; if absent, default credential chain is used",
        ),
    ]

    WRITE_PREFIX: Annotated[
        str,
        Field(
            default="artifacts",
            description=(
                "S3 key prefix for all writes (e.g. 'team/project'). "
                "Defaults to 'artifacts'. Must not be empty — an empty prefix "
                "breaks scope determination and cross-scope access control."
            ),
        ),
    ]

    READ_PREFIXES: Annotated[
        str,
        Field(
            default="",
            description=(
                "Comma-separated additional read prefixes; empty means no additional scopes"
            ),
        ),
    ]

    BEDROCK_EMBEDDING_MODEL: Annotated[
        str,
        Field(
            default="amazon.titan-embed-text-v2:0",
            description="Bedrock embedding model ID",
        ),
    ]

    BEDROCK_EMBEDDING_DIMENSIONS: Annotated[
        int,
        Field(
            default=1024,
            description=(
                "Output dimension of the embedding model. "
                "Must match the dimension of the configured VECTORS_INDEX. "
                "Defaults to 1024 (Amazon Titan Text Embeddings v2 default). "
                "Set explicitly when using a non-default dimension "
                "(e.g. Titan v2 at 256 or 512, or a different model entirely)."
            ),
        ),
    ]

    SEARCH_FETCH_TOP_K: Annotated[
        int,
        Field(
            default=25,
            description=(
                "Section vectors requested per S3 Vectors call in the search re-fetch loop "
                "(1–100 inclusive)"
            ),
        ),
    ]

    SEARCH_MAX_ITERATIONS: Annotated[
        int,
        Field(
            default=3,
            description="Maximum S3 Vectors calls per search before returning available results",
        ),
    ]

    SEARCH_DEFAULT_TOP_K: Annotated[
        int,
        Field(
            default=5,
            description="Default artifacts returned when caller does not specify (1–100)",
        ),
    ]

    LOG_LEVEL: Annotated[
        str,
        Field(
            default="INFO",
            description="Logging verbosity: DEBUG, INFO, WARNING, or ERROR",
        ),
    ]

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("SEARCH_FETCH_TOP_K")
    @classmethod
    def validate_search_fetch_top_k(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError(f"SEARCH_FETCH_TOP_K must be between 1 and 100 (got {v})")
        return v

    @field_validator("SEARCH_MAX_ITERATIONS")
    @classmethod
    def validate_search_max_iterations(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"SEARCH_MAX_ITERATIONS must be at least 1 (got {v})")
        return v

    @field_validator("SEARCH_DEFAULT_TOP_K")
    @classmethod
    def validate_search_default_top_k(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError(f"SEARCH_DEFAULT_TOP_K must be between 1 and 100 (got {v})")
        return v

    @field_validator("BEDROCK_EMBEDDING_DIMENSIONS")
    @classmethod
    def validate_bedrock_embedding_dimensions(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"BEDROCK_EMBEDDING_DIMENSIONS must be at least 1 (got {v})")
        return v

    @field_validator("WRITE_PREFIX")
    @classmethod
    def validate_write_prefix(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "WRITE_PREFIX must not be empty. "
                "Set it to a non-empty prefix such as 'artifacts' or 'team/project'. "
                "An empty prefix breaks scope determination and cross-scope access control."
            )
        return v.strip("/")

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)} (got '{v}')")
        return upper

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def aws_region(self) -> str:
        """AWS region for all API calls."""
        return self.AWS_REGION

    @property
    def artifact_bucket(self) -> str:
        """S3 bucket name for artifact content storage."""
        return self.ARTIFACT_BUCKET

    @property
    def vectors_bucket(self) -> str:
        """S3 Vectors bucket name."""
        return self.VECTORS_BUCKET

    @property
    def vectors_index(self) -> str:
        """S3 Vectors index name."""
        return self.VECTORS_INDEX

    @property
    def aws_profile(self) -> str | None:
        """Named AWS profile, or None to use the default credential chain."""
        return self.AWS_PROFILE

    @property
    def write_prefix(self) -> str:
        """S3 key prefix for all writes."""
        return self.WRITE_PREFIX

    @property
    def read_prefixes(self) -> str:
        """Raw comma-separated READ_PREFIXES value."""
        return self.READ_PREFIXES

    @property
    def bedrock_embedding_model(self) -> str:
        """Bedrock embedding model ID."""
        return self.BEDROCK_EMBEDDING_MODEL

    @property
    def bedrock_embedding_dimensions(self) -> int:
        """Output dimension of the embedding model."""
        return self.BEDROCK_EMBEDDING_DIMENSIONS

    @property
    def search_fetch_top_k(self) -> int:
        """Section vectors requested per S3 Vectors call."""
        return self.SEARCH_FETCH_TOP_K

    @property
    def search_max_iterations(self) -> int:
        """Maximum S3 Vectors calls per search."""
        return self.SEARCH_MAX_ITERATIONS

    @property
    def search_default_top_k(self) -> int:
        """Default artifacts returned when caller does not specify."""
        return self.SEARCH_DEFAULT_TOP_K

    @property
    def log_level(self) -> str:
        """Logging level string (uppercase)."""
        return self.LOG_LEVEL

    @property
    def read_prefixes_list(self) -> list[str]:
        """READ_PREFIXES split on commas, stripped, with empty entries removed."""
        if not self.READ_PREFIXES:
            return []
        return [p.strip() for p in self.READ_PREFIXES.split(",") if p.strip()]

    @property
    def effective_read_scopes(self) -> list[str]:
        """Full read scope: write prefix followed by all additional read prefixes."""
        return [self.WRITE_PREFIX] + self.read_prefixes_list

    @model_validator(mode="before")
    @classmethod
    def check_required_non_empty(cls, values: Any) -> Any:
        """Validate required string fields are non-empty."""
        for field_name in ("AWS_REGION", "ARTIFACT_BUCKET", "VECTORS_BUCKET", "VECTORS_INDEX"):
            val = values.get(field_name) if isinstance(values, dict) else None
            if val is not None and not str(val).strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        return values
