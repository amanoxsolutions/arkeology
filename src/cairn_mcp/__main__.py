"""Entry point for cairn-mcp server.

Configures logging, validates configuration and AWS prerequisites,
then delegates to the FastMCP server.
"""

import logging
import os
import sys

from pydantic import ValidationError

from cairn_mcp import server
from cairn_mcp.clients.bedrock import BedrockClientImpl
from cairn_mcp.clients.s3 import S3ClientImpl
from cairn_mcp.clients.vectors import VectorsClientImpl
from cairn_mcp.config import _VALID_LOG_LEVELS, Settings
from cairn_mcp.errors import CredentialError, StartupValidationError
from cairn_mcp.startup import validate_startup

logger = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    """Configure the root logger with a stderr stream handler.

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


def main() -> None:
    """Configure logging, validate settings, run startup checks, then start the server."""
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    configure_logging(log_level)

    # ── Step 1: Parse and validate configuration ──────────────────────────────
    try:
        settings = Settings(_env_file=".env", _env_file_encoding="utf-8")
    except ValidationError as exc:
        errors = exc.errors()
        messages = []
        for err in errors:
            field = " → ".join(str(loc) for loc in err["loc"]) if err.get("loc") else "unknown"
            messages.append(f"  {field}: {err['msg']}")
        print(
            "Configuration error — fix the following before starting cairn-mcp:\n"
            + "\n".join(messages),
            file=sys.stderr,
        )
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
        print(f"Startup validation failed: {exc.message}", file=sys.stderr)
        sys.exit(1)
    except CredentialError as exc:
        print(f"Startup failed — credential error: {exc.message}", file=sys.stderr)
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
