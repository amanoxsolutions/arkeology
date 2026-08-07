"""Unit tests for the Settings configuration model.

All tests follow strict TDD — this file was written before config.py existed.
Tests use monkeypatch to isolate environment variables.
"""

import pytest

from cairn_mcp.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all relevant env vars before each test to start from a clean slate."""
    for var in [
        "AWS_REGION",
        "ARTIFACT_BUCKET",
        "VECTORS_BUCKET",
        "VECTORS_INDEX",
        "AWS_PROFILE",
        "WRITE_PREFIX",
        "READ_PREFIXES",
        "BEDROCK_EMBEDDING_MODEL",
        "BEDROCK_EMBEDDING_DIMENSIONS",
        "SEARCH_FETCH_TOP_K",
        "SEARCH_MAX_ITERATIONS",
        "SEARCH_DEFAULT_TOP_K",
        "LOG_LEVEL",
        "SECTION_CONCURRENCY",
        "EMBED_MAX_SECTIONS",
        "EMBED_MIN_SECTION_LENGTH",
        "ARTIFACT_CONCURRENCY",
        "BEDROCK_TEXT_MODEL",
        "EMBED_MAX_SECTION_LENGTH",
        "SYNTHESISE_MAX_RESPONSE_BYTES",
    ]:
        monkeypatch.delenv(var, raising=False)


def _required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set all required env vars to valid values."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-artifacts")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")


# --- Required variables ---


def test_all_required_present_constructs_successfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All required vars set → Settings constructs without error."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.aws_region == "us-east-1"
    assert settings.artifact_bucket == "my-artifacts"
    assert settings.vectors_bucket == "my-vectors"
    assert settings.vectors_index == "my-index"


def test_aws_region_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing AWS_REGION raises a validation error referencing the variable."""
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-artifacts")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    with pytest.raises(Exception, match="AWS_REGION"):
        Settings()


def test_artifact_bucket_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing ARTIFACT_BUCKET raises a validation error."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    with pytest.raises(Exception, match="ARTIFACT_BUCKET"):
        Settings()


def test_vectors_bucket_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing VECTORS_BUCKET raises a validation error."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-artifacts")
    monkeypatch.setenv("VECTORS_INDEX", "my-index")
    with pytest.raises(Exception, match="VECTORS_BUCKET"):
        Settings()


def test_vectors_index_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing VECTORS_INDEX raises a validation error."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ARTIFACT_BUCKET", "my-artifacts")
    monkeypatch.setenv("VECTORS_BUCKET", "my-vectors")
    with pytest.raises(Exception, match="VECTORS_INDEX"):
        Settings()


# --- Optional variables with defaults ---


def test_optional_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """All optional vars absent → correct defaults are used."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.aws_profile is None
    assert settings.write_prefix == "artifacts"
    assert settings.read_prefixes == ""
    assert settings.bedrock_embedding_model == "amazon.titan-embed-text-v2:0"
    assert settings.search_fetch_top_k == 25
    assert settings.search_max_iterations == 3
    assert settings.search_default_top_k == 5
    assert settings.log_level == "INFO"


def test_aws_profile_absent_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """AWS_PROFILE absent → aws_profile is None."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.aws_profile is None


def test_aws_profile_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """AWS_PROFILE set → aws_profile holds the value."""
    _required_env(monkeypatch)
    monkeypatch.setenv("AWS_PROFILE", "my-profile")
    settings = Settings()
    assert settings.aws_profile == "my-profile"


def test_bedrock_embedding_model_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """BEDROCK_EMBEDDING_MODEL absent → default is Titan v2."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.bedrock_embedding_model == "amazon.titan-embed-text-v2:0"


def test_bedrock_embedding_model_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """BEDROCK_EMBEDDING_MODEL set → value is stored."""
    _required_env(monkeypatch)
    monkeypatch.setenv("BEDROCK_EMBEDDING_MODEL", "custom-model:1")
    settings = Settings()
    assert settings.bedrock_embedding_model == "custom-model:1"


def test_write_prefix_absent_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """WRITE_PREFIX absent → write_prefix defaults to 'artifacts'."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.write_prefix == "artifacts"


def test_write_prefix_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """WRITE_PREFIX set → trailing slashes are stripped."""
    _required_env(monkeypatch)
    monkeypatch.setenv("WRITE_PREFIX", "platform/my-service/")
    settings = Settings()
    assert settings.write_prefix == "platform/my-service"


def test_write_prefix_empty_string_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """WRITE_PREFIX='' → ValidationError (must not be empty)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("WRITE_PREFIX", "")
    with pytest.raises(Exception):
        Settings()


def test_write_prefix_whitespace_only_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """WRITE_PREFIX='   ' → ValidationError (effectively empty after strip)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("WRITE_PREFIX", "   ")
    with pytest.raises(Exception):
        Settings()


# --- SEARCH_FETCH_TOP_K validation ---


def test_search_fetch_top_k_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEARCH_FETCH_TOP_K absent → defaults to 25."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.search_fetch_top_k == 25


def test_search_fetch_top_k_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEARCH_FETCH_TOP_K=50 → accepted."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SEARCH_FETCH_TOP_K", "50")
    settings = Settings()
    assert settings.search_fetch_top_k == 50


def test_search_fetch_top_k_zero_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEARCH_FETCH_TOP_K=0 → validation error (must be ≥1)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SEARCH_FETCH_TOP_K", "0")
    with pytest.raises(Exception):
        Settings()


def test_search_fetch_top_k_above_ceiling_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEARCH_FETCH_TOP_K=101 → validation error (ceiling is 100)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SEARCH_FETCH_TOP_K", "101")
    with pytest.raises(Exception):
        Settings()


def test_search_fetch_top_k_100_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEARCH_FETCH_TOP_K=100 → accepted (boundary)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SEARCH_FETCH_TOP_K", "100")
    settings = Settings()
    assert settings.search_fetch_top_k == 100


# --- SEARCH_MAX_ITERATIONS validation ---


def test_search_max_iterations_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEARCH_MAX_ITERATIONS absent → defaults to 3."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.search_max_iterations == 3


def test_search_max_iterations_zero_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEARCH_MAX_ITERATIONS=0 → validation error."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SEARCH_MAX_ITERATIONS", "0")
    with pytest.raises(Exception):
        Settings()


def test_search_max_iterations_one_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEARCH_MAX_ITERATIONS=1 → accepted."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SEARCH_MAX_ITERATIONS", "1")
    settings = Settings()
    assert settings.search_max_iterations == 1


# --- SEARCH_DEFAULT_TOP_K validation ---


def test_search_default_top_k_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEARCH_DEFAULT_TOP_K absent → defaults to 5."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.search_default_top_k == 5


# --- LOG_LEVEL validation ---


def test_log_level_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOG_LEVEL absent → defaults to INFO."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.log_level == "INFO"


def test_log_level_lowercase_accepted_stored_uppercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOG_LEVEL=debug → accepted; stored as 'DEBUG'."""
    _required_env(monkeypatch)
    monkeypatch.setenv("LOG_LEVEL", "debug")
    settings = Settings()
    assert settings.log_level == "DEBUG"


def test_log_level_invalid_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOG_LEVEL=TRACE → validation error listing valid values."""
    _required_env(monkeypatch)
    monkeypatch.setenv("LOG_LEVEL", "TRACE")
    with pytest.raises(Exception):
        Settings()


# --- READ_PREFIXES parsing ---


def test_read_prefixes_absent_is_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """READ_PREFIXES absent → read_prefixes_list == []."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.read_prefixes_list == []


def test_read_prefixes_comma_separated_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """READ_PREFIXES='network/,shared/ , ' → ['network', 'shared'] (slashes normalized)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("READ_PREFIXES", "network/,shared/ , ")
    settings = Settings()
    assert settings.read_prefixes_list == ["network", "shared"]


def test_read_prefixes_single_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """READ_PREFIXES='platform/' → ['platform'] (trailing slash stripped)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("READ_PREFIXES", "platform/")
    settings = Settings()
    assert settings.read_prefixes_list == ["platform"]


def test_read_prefixes_strips_surrounding_slashes_keeps_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Surrounding slashes are stripped so consumers can append '/' to rebuild the scope;
    internal slashes (multi-level prefixes) are preserved. This keeps READ_PREFIXES
    consistent with WRITE_PREFIX, which also strips surrounding slashes — otherwise a
    configured 'network/' becomes 'network//' at the call site and matches nothing,
    silently disabling foreign-scope reads."""
    _required_env(monkeypatch)
    monkeypatch.setenv("READ_PREFIXES", "/network/,shared/org/")
    settings = Settings()
    assert settings.read_prefixes_list == ["network", "shared/org"]


# --- effective_read_scopes ---


def test_effective_read_scopes_with_prefix_and_read_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """effective_read_scopes = [write_prefix] + read_prefixes_list, all slash-normalized."""
    _required_env(monkeypatch)
    monkeypatch.setenv("WRITE_PREFIX", "platform/")
    monkeypatch.setenv("READ_PREFIXES", "network/,shared/")
    settings = Settings()
    assert settings.effective_read_scopes == ["platform", "network", "shared"]


def test_effective_read_scopes_no_read_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """effective_read_scopes with no READ_PREFIXES → [write_prefix] only."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.effective_read_scopes == ["artifacts"]


# --- BEDROCK_EMBEDDING_DIMENSIONS ---


def test_bedrock_embedding_dimensions_defaults_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BEDROCK_EMBEDDING_DIMENSIONS defaults to 1024 when not set."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.bedrock_embedding_dimensions == 1024


def test_bedrock_embedding_dimensions_parses_positive_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BEDROCK_EMBEDDING_DIMENSIONS accepts a positive integer."""
    _required_env(monkeypatch)
    monkeypatch.setenv("BEDROCK_EMBEDDING_DIMENSIONS", "2048")
    settings = Settings()
    assert settings.bedrock_embedding_dimensions == 2048


def test_bedrock_embedding_dimensions_rejects_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BEDROCK_EMBEDDING_DIMENSIONS=0 raises ValidationError."""
    _required_env(monkeypatch)
    monkeypatch.setenv("BEDROCK_EMBEDDING_DIMENSIONS", "0")
    with pytest.raises(Exception):
        Settings()


def test_bedrock_embedding_dimensions_rejects_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BEDROCK_EMBEDDING_DIMENSIONS=-1 raises ValidationError."""
    _required_env(monkeypatch)
    monkeypatch.setenv("BEDROCK_EMBEDDING_DIMENSIONS", "-1")
    with pytest.raises(Exception):
        Settings()


# ---------------------------------------------------------------------------
# T26 — SECTION_CONCURRENCY
# ---------------------------------------------------------------------------


def test_section_concurrency_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECTION_CONCURRENCY absent → section_concurrency defaults to 5."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.section_concurrency == 5


def test_section_concurrency_zero_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECTION_CONCURRENCY=0 → ValidationError (must be ≥1)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SECTION_CONCURRENCY", "0")
    with pytest.raises(Exception):
        Settings()


def test_section_concurrency_negative_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECTION_CONCURRENCY=-1 → ValidationError (must be ≥1)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SECTION_CONCURRENCY", "-1")
    with pytest.raises(Exception):
        Settings()


# ---------------------------------------------------------------------------
# T28 — EMBED_MAX_SECTIONS
# ---------------------------------------------------------------------------


def test_embed_max_sections_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_MAX_SECTIONS absent → embed_max_sections defaults to 20."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.embed_max_sections == 20


def test_embed_max_sections_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_MAX_SECTIONS=5 → embed_max_sections == 5."""
    _required_env(monkeypatch)
    monkeypatch.setenv("EMBED_MAX_SECTIONS", "5")
    settings = Settings()
    assert settings.embed_max_sections == 5


def test_embed_max_sections_zero_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_MAX_SECTIONS=0 → ValidationError (must be ≥1)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("EMBED_MAX_SECTIONS", "0")
    with pytest.raises(Exception):
        Settings()


# ---------------------------------------------------------------------------
# T28 — EMBED_MIN_SECTION_LENGTH
# ---------------------------------------------------------------------------


def test_embed_min_section_length_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_MIN_SECTION_LENGTH absent → embed_min_section_length defaults to 50."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.embed_min_section_length == 50


def test_embed_min_section_length_zero_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_MIN_SECTION_LENGTH=0 → valid (disables the minimum-length filter)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("EMBED_MIN_SECTION_LENGTH", "0")
    settings = Settings()
    assert settings.embed_min_section_length == 0


def test_embed_min_section_length_negative_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_MIN_SECTION_LENGTH=-1 → ValidationError (must be ≥0)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("EMBED_MIN_SECTION_LENGTH", "-1")
    with pytest.raises(Exception):
        Settings()


# ---------------------------------------------------------------------------
# READ_PREFIXES validator — comment filtering and whitespace rejection
# ---------------------------------------------------------------------------


def test_read_prefixes_comment_only_token_silently_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """READ_PREFIXES='# comma-separated' → comment token dropped → empty list."""
    _required_env(monkeypatch)
    monkeypatch.setenv("READ_PREFIXES", "# comma-separated")
    settings = Settings()
    assert settings.read_prefixes_list == []


def test_read_prefixes_valid_and_comment_token_mixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """READ_PREFIXES='platform/, # a comment' → only valid prefix retained, slash-normalized."""
    _required_env(monkeypatch)
    monkeypatch.setenv("READ_PREFIXES", "platform/, # a comment")
    settings = Settings()
    assert settings.read_prefixes_list == ["platform"]


def test_read_prefixes_internal_whitespace_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """READ_PREFIXES='or leave blank' → ValidationError (whitespace in prefix)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("READ_PREFIXES", "or leave blank")
    with pytest.raises(Exception, match="whitespace"):
        Settings()


def test_read_prefixes_comment_then_whitespace_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """READ_PREFIXES='# comma-separated, or leave blank' → ValidationError.

    The comment token is dropped first; the whitespace token still triggers the error.
    This is the exact value observed in the live-test log (line 580).
    """
    _required_env(monkeypatch)
    monkeypatch.setenv("READ_PREFIXES", "# comma-separated, or leave blank")
    with pytest.raises(Exception, match="whitespace"):
        Settings()


# ---------------------------------------------------------------------------
# Z1 — ARTIFACT_CONCURRENCY is removed; the env var is silently ignored
# ---------------------------------------------------------------------------


def test_artifact_concurrency_env_var_is_silently_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARTIFACT_CONCURRENCY=10 in the environment → Settings() constructs without error
    and the Settings object does NOT have an 'artifact_concurrency' attribute.
    """
    _required_env(monkeypatch)
    monkeypatch.setenv("ARTIFACT_CONCURRENCY", "10")
    # Must not raise ValidationError
    settings = Settings()
    # The field must not exist on Settings (removed in T39)
    assert not hasattr(settings, "artifact_concurrency"), (
        "Settings must not have an 'artifact_concurrency' attribute after T39 removal"
    )


# ---------------------------------------------------------------------------
# Z1 — BEDROCK_TEXT_MODEL
# ---------------------------------------------------------------------------


def test_bedrock_text_model_absent_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """BEDROCK_TEXT_MODEL absent → bedrock_text_model is None."""
    _required_env(monkeypatch)
    settings = Settings()
    # Red: Settings doesn't have bedrock_text_model yet; getattr returns sentinel
    assert getattr(settings, "bedrock_text_model", "NOT_SET") is None


def test_bedrock_text_model_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """BEDROCK_TEXT_MODEL set → bedrock_text_model holds the value."""
    _required_env(monkeypatch)
    monkeypatch.setenv("BEDROCK_TEXT_MODEL", "amazon.nova-lite-v1:0")
    settings = Settings()
    assert getattr(settings, "bedrock_text_model", "NOT_SET") == "amazon.nova-lite-v1:0"


# ---------------------------------------------------------------------------
# Z1 — EMBED_MAX_SECTION_LENGTH
# ---------------------------------------------------------------------------


def test_embed_max_section_length_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_MAX_SECTION_LENGTH absent → embed_max_section_length defaults to 24000."""
    _required_env(monkeypatch)
    settings = Settings()
    # Red: Settings doesn't have embed_max_section_length yet; getattr returns sentinel
    assert getattr(settings, "embed_max_section_length", "NOT_SET") == 24000


def test_embed_max_section_length_zero_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_MAX_SECTION_LENGTH=0 → valid (disables truncation)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("EMBED_MAX_SECTION_LENGTH", "0")
    settings = Settings()
    assert getattr(settings, "embed_max_section_length", "NOT_SET") == 0


def test_embed_max_section_length_negative_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_MAX_SECTION_LENGTH=-1 → ValidationError (must be ≥0)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("EMBED_MAX_SECTION_LENGTH", "-1")
    # Red: unknown field is ignored, no exception raised until field is added with validator.
    with pytest.raises(Exception):
        Settings()


# ---------------------------------------------------------------------------
# M4 — BEDROCK_EMBEDDING_MODEL / BEDROCK_TEXT_MODEL empty-string validators
# ---------------------------------------------------------------------------


def test_bedrock_embedding_model_empty_string_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """BEDROCK_EMBEDDING_MODEL='' → ValidationError (must not be empty)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("BEDROCK_EMBEDDING_MODEL", "")
    with pytest.raises(Exception, match="BEDROCK_EMBEDDING_MODEL"):
        Settings()


def test_bedrock_text_model_empty_string_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """BEDROCK_TEXT_MODEL='' → ValidationError (must not be empty when provided)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("BEDROCK_TEXT_MODEL", "")
    with pytest.raises(Exception, match="BEDROCK_TEXT_MODEL"):
        Settings()


# ---------------------------------------------------------------------------
# M4 — load_settings() factory raises ConfigurationError
# ---------------------------------------------------------------------------


def test_load_settings_returns_settings_on_valid_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_settings() with valid env → returns a Settings instance."""
    from cairn_mcp.config import load_settings

    _required_env(monkeypatch)
    settings = load_settings()
    assert settings.aws_region == "us-east-1"


def test_load_settings_raises_configuration_error_on_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_settings() with missing required fields → raises ConfigurationError."""
    from cairn_mcp.config import load_settings
    from cairn_mcp.errors import ConfigurationError

    # All required env vars are absent (autouse fixture already cleaned them)
    with pytest.raises(ConfigurationError):
        load_settings()


def test_load_settings_configuration_error_reports_failing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ConfigurationError from load_settings() lists the failing field name(s)."""
    from cairn_mcp.config import load_settings
    from cairn_mcp.errors import ConfigurationError

    # Only AWS_REGION is missing
    monkeypatch.setenv("ARTIFACT_BUCKET", "bucket")
    monkeypatch.setenv("VECTORS_BUCKET", "vbucket")
    monkeypatch.setenv("VECTORS_INDEX", "idx")
    try:
        load_settings()
        pytest.fail("Expected ConfigurationError")
    except ConfigurationError as exc:
        assert exc.fields, "fields must be non-empty"
        assert any("AWS_REGION" in f for f in exc.fields)


# --- SYNTHESISE_MAX_RESPONSE_BYTES validation (CA-5) ---


def test_synthesise_max_response_bytes_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """SYNTHESISE_MAX_RESPONSE_BYTES absent → defaults to 1,000,000 (1 MB)."""
    _required_env(monkeypatch)
    settings = Settings()
    assert settings.synthesise_max_response_bytes == 1_000_000


def test_synthesise_max_response_bytes_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """SYNTHESISE_MAX_RESPONSE_BYTES=500000 → accepted."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SYNTHESISE_MAX_RESPONSE_BYTES", "500000")
    settings = Settings()
    assert settings.synthesise_max_response_bytes == 500000


def test_synthesise_max_response_bytes_zero_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """SYNTHESISE_MAX_RESPONSE_BYTES=0 → validation error (must be ≥1)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SYNTHESISE_MAX_RESPONSE_BYTES", "0")
    with pytest.raises(Exception):
        Settings()


def test_synthesise_max_response_bytes_negative_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """SYNTHESISE_MAX_RESPONSE_BYTES=-1 → validation error (must be ≥1)."""
    _required_env(monkeypatch)
    monkeypatch.setenv("SYNTHESISE_MAX_RESPONSE_BYTES", "-1")
    with pytest.raises(Exception):
        Settings()
