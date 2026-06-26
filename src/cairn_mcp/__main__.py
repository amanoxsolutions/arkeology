"""Entry point for cairn-mcp server.

Configures logging, validates configuration and AWS prerequisites,
then delegates to the FastMCP server.
"""

import logging
import os
import sys

from cairn_mcp import server
from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import _VALID_LOG_LEVELS, load_settings
from cairn_mcp.errors import ConfigurationError, CredentialError, StartupValidationError
from cairn_mcp.startup import validate_startup

logger = logging.getLogger(__name__)

# Third-party loggers that emit sensitive or very large content at DEBUG.
# Always clamped to WARNING regardless of the configured LOG_LEVEL to prevent
# secretAccessKey, sessionToken, full HTTP bodies, and artifact content from
# appearing in logs.
# - botocore/boto3/urllib3/s3transfer: AWS credentials and HTTP request/response bodies
# - fastmcp: logs full tool call arguments (including artifact content) at DEBUG via
#   fastmcp.server.mixins.mcp_operations — line "Handler called: call_tool <name> with <args>"
_NOISY_LOGGERS: tuple[str, ...] = ("botocore", "boto3", "urllib3", "s3transfer", "fastmcp")


def configure_logging(level: str) -> None:
    """Configure the root logger with a stderr stream handler.

    Third-party AWS SDK and HTTP library loggers (botocore, boto3, urllib3,
    s3transfer) are always clamped to WARNING to prevent AWS temporary
    credentials and full HTTP bodies from appearing in logs, even when
    LOG_LEVEL=DEBUG is configured.

    Args:
        level: Desired log level string (DEBUG, INFO, WARNING, ERROR).
            Falls back to INFO if the value is invalid.
    """
    normalised = level.upper()
    if normalised not in _VALID_LOG_LEVELS:
        normalised = "INFO"
        # Use a temporary handler to emit the warning before full setup
        logging.basicConfig(stream=sys.stderr, level=logging.INFO)
        logging.getLogger(__name__).warning(
            "Invalid LOG_LEVEL '%s'; falling back to INFO. Valid values: %s",
            level,
            ", ".join(sorted(_VALID_LOG_LEVELS)),
        )

    root = logging.getLogger()
    root.setLevel(normalised)

    # Remove any handlers added by basicConfig above
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)

    # Suppress noisy third-party loggers unconditionally — they emit full HTTP
    # bodies including AWS temporary credentials (secretAccessKey, sessionToken)
    # at DEBUG level, which must never appear in the log regardless of LOG_LEVEL.
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    """Configure logging, validate settings, run startup checks, then start the server."""
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    configure_logging(log_level)

    # ── Step 1: Parse and validate configuration ──────────────────────────────
    try:
        settings = load_settings(_env_file=".env", _env_file_encoding="utf-8")
    except ConfigurationError as exc:
        logger.critical("%s", exc.message)
        sys.exit(1)

    # Reconfigure logging with the validated LOG_LEVEL from settings
    configure_logging(settings.log_level)

    # ── Step 2: Construct AWS clients ─────────────────────────────────────────
    s3_client = S3ClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.artifact_bucket,
    )
    vectors_client = VectorsClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
        bucket=settings.vectors_bucket,
        index=settings.vectors_index,
    )
    bedrock_client = BedrockClientImpl(
        region=settings.aws_region,
        profile=settings.aws_profile,
    )

    # ── Step 3: Run startup validation ───────────────────────────────────────
    try:
        validate_startup(
            settings=settings,
            s3=s3_client,
            vectors=vectors_client,
            bedrock=bedrock_client,
        )
    except StartupValidationError as exc:
        logger.critical("Startup validation failed: %s", exc.message)
        sys.exit(1)
    except CredentialError as exc:
        logger.critical("Startup failed — credential error: %s", exc.message)
        sys.exit(1)

    # ── Step 4: Register MCP tools ────────────────────────────────────────────
    server.register_tools(
        settings=settings,
        s3=s3_client,
        vectors=vectors_client,
        bedrock=bedrock_client,
    )

    # ── Step 5: Start the server ──────────────────────────────────────────────
    server.run()


if __name__ == "__main__":
    main()
