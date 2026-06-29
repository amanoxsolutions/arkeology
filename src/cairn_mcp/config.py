"""Configuration model for cairn-mcp.

All configuration is read from environment variables once at startup.
The Settings object is constructed in __main__.py and passed through
dependency injection — it is never re-read from the environment mid-session.
Each field carries a description with its type, default, and constraints.
"""

import logging
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})
_config_logger = logging.getLogger(__name__)


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
            ge=1,
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
            ge=1,
            le=100,
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
            ge=1,
            description="Maximum S3 Vectors calls per search before returning available results",
        ),
    ]

    SEARCH_DEFAULT_TOP_K: Annotated[
        int,
        Field(
            default=5,
            ge=1,
            le=100,
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

    FAILURE_LOG_PATH: Annotated[
        str,
        Field(
            default=".cairn_failures.jsonl",
            description=(
                "Path to the local partial-write failure log (.jsonl). "
                "Defaults to '.cairn_failures.jsonl' in the working directory."
            ),
        ),
    ]

    SECTION_CONCURRENCY: Annotated[
        int,
        Field(
            default=5,
            ge=1,
            description="Maximum number of concurrent section embedding calls during write.",
        ),
    ]

    EMBED_MAX_SECTIONS: Annotated[
        int,
        Field(
            default=20,
            ge=1,
            description="Maximum number of sections to embed per artifact write.",
        ),
    ]

    EMBED_MIN_SECTION_LENGTH: Annotated[
        int,
        Field(
            default=50,
            ge=0,
            description=(
                "Minimum section body length (chars) to embed. "
                "Sections shorter than this are skipped. Set to 0 to disable."
            ),
        ),
    ]

    BEDROCK_TEXT_MODEL: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Bedrock text generation model ID used by migrate_artifacts to generate "
                "missing descriptions (e.g. amazon.nova-lite-v1:0). "
                "When absent, the text model startup check is skipped entirely."
            ),
        ),
    ]

    EMBED_MAX_SECTION_LENGTH: Annotated[
        int,
        Field(
            default=24000,
            ge=0,
            description=(
                "Maximum section body length (chars) passed to bedrock.embed. "
                "Bodies longer than this are truncated before embedding but stored "
                "in full in S3. Set to 0 to disable truncation."
            ),
        ),
    ]

    # ── Validators ────────────────────────────────────────────────────────────
    # Numeric range constraints (ge/le) are declared on the fields above; only
    # validators with bespoke logic or messages live here.

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

    @field_validator("READ_PREFIXES")
    @classmethod
    def validate_read_prefixes(cls, v: str) -> str:
        """Filter comment tokens, reject internal whitespace, normalize surrounding slashes.

        Tokens starting with '#' are silently dropped — they are comment artifacts
        from .env files where inline comments were not stripped by python-dotenv.
        Tokens containing internal whitespace (e.g. 'or leave blank') are invalid
        S3 prefixes and raise an error so the operator knows to fix their .env.
        Surrounding slashes are stripped from each token so the stored form matches
        WRITE_PREFIX (which also strips them) and the `scope` value persisted in vector
        metadata — consumers append '/' to rebuild the scope, so a configured 'network/'
        must normalize to 'network' (otherwise the match becomes 'network//' and silently
        disables foreign-scope reads). Internal slashes (multi-level prefixes) are kept.
        """
        if not v:
            return v
        clean: list[str] = []
        for token in v.split(","):
            stripped = token.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if any(c in stripped for c in (" ", "\t")):
                raise ValueError(
                    f"READ_PREFIXES contains an invalid prefix '{stripped}': "
                    "S3 prefixes must not contain whitespace. "
                    "Check your .env file for template placeholder text."
                )
            normalized = stripped.strip("/")
            if normalized:
                clean.append(normalized)
        return ",".join(clean)

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)} (got '{v}')")
        return upper

    @field_validator("BEDROCK_EMBEDDING_MODEL")
    @classmethod
    def validate_bedrock_embedding_model(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "BEDROCK_EMBEDDING_MODEL must not be empty (e.g. 'amazon.titan-embed-text-v2:0')"
            )
        return v

    @field_validator("BEDROCK_TEXT_MODEL")
    @classmethod
    def validate_bedrock_text_model(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError(
                "BEDROCK_TEXT_MODEL must not be empty when provided; "
                "omit it entirely to disable the text model"
            )
        return v

    # ── Computed properties ────────────────────────────────────────────────────
    # These snake_case properties provide IDE-friendly access to the UPPER_CASE
    # pydantic-settings fields. We use explicit properties rather than an
    # alias_generator because alias_generator produces aliases on all fields
    # (including internal validators), requires careful mode="serialization"
    # handling, and loses IDE autocomplete on the property names. The explicit
    # approach is more verbose but fully transparent to type checkers and IDEs.

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
    def failure_log_path(self) -> Path:
        """Path to the local partial-write failure log."""
        return Path(self.FAILURE_LOG_PATH)

    @property
    def section_concurrency(self) -> int:
        """Maximum concurrent section embedding calls."""
        return self.SECTION_CONCURRENCY

    @property
    def embed_max_sections(self) -> int:
        """Maximum sections to embed per artifact write."""
        return self.EMBED_MAX_SECTIONS

    @property
    def embed_min_section_length(self) -> int:
        """Minimum section body length to embed (0 disables filter)."""
        return self.EMBED_MIN_SECTION_LENGTH

    @property
    def bedrock_text_model(self) -> str | None:
        """Bedrock text generation model ID, or None if not configured."""
        return self.BEDROCK_TEXT_MODEL

    @property
    def embed_max_section_length(self) -> int:
        """Maximum section body length passed to embed (0 disables truncation)."""
        return self.EMBED_MAX_SECTION_LENGTH

    @property
    def read_prefixes_list(self) -> list[str]:
        """READ_PREFIXES split on commas, stripped of whitespace and surrounding slashes,
        with empty entries removed. Surrounding slashes are normalized away so consumers can
        append '/' to rebuild a scope (kept consistent with WRITE_PREFIX and the validator)."""
        if not self.READ_PREFIXES:
            return []
        return [
            cleaned
            for token in self.READ_PREFIXES.split(",")
            if (cleaned := token.strip().strip("/"))
        ]

    @property
    def effective_read_scopes(self) -> list[str]:
        """Full read scope: write prefix followed by all additional read prefixes."""
        return [self.WRITE_PREFIX] + self.read_prefixes_list

    @model_validator(mode="before")
    @classmethod
    def check_required_non_empty(cls, values: Any) -> Any:
        """Validate required string fields are non-empty."""
        if not isinstance(values, dict):
            _config_logger.warning(
                "check_required_non_empty received non-dict values (%s); skipping field checks",
                type(values).__name__,
            )
            return values
        for field_name in ("AWS_REGION", "ARTIFACT_BUCKET", "VECTORS_BUCKET", "VECTORS_INDEX"):
            val = values.get(field_name)
            if val is not None and not str(val).strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        return values


def load_settings(**kwargs: Any) -> Settings:
    """Construct Settings from the environment, raising :exc:`ConfigurationError` on failure.

    This is the canonical entry point for building Settings at startup.
    Callers only need to handle :class:`~cairn_mcp.errors.ConfigurationError`
    rather than Pydantic internals.

    Args:
        **kwargs: Forwarded verbatim to the :class:`Settings` constructor
            (e.g. ``_env_file=".env"``).

    Returns:
        A valid, fully-validated :class:`Settings` instance.

    Raises:
        ConfigurationError: When one or more environment variables are invalid
            or missing, with a human-readable message listing each failure.
    """
    # Import here to avoid a circular import at module load time
    # (errors.py does not import from config.py, so the cycle is safe to break lazily).
    from cairn_mcp.errors import ConfigurationError

    try:
        return Settings(**kwargs)
    except ValidationError as exc:
        error_list = exc.errors()
        fields: list[str] = []
        messages: list[str] = []
        for err in error_list:
            field = " → ".join(str(loc) for loc in err["loc"]) if err.get("loc") else "unknown"
            fields.append(field)
            messages.append(f"  {field}: {err['msg']}")
        raise ConfigurationError(
            "Configuration error — fix the following before starting cairn-mcp:\n"
            + "\n".join(messages),
            fields=fields,
        ) from exc
