#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "boto3",
#   "pyyaml",
# ]
# ///
"""migrate.py — bulk import existing repo documentation into cairn-mcp.

This script reads a CAIRN_IMPORT.yaml manifest and writes each listed artifact
to S3 and S3 Vectors using the same AWS env vars as the cairn-mcp server.

It does NOT import from the cairn_mcp package — it replicates the required
logic inline so the script is self-contained in the skills/ bundle.

Usage:
    uv run skills/migration/scripts/migrate.py --manifest CAIRN_IMPORT.yaml --dry-run
    uv run skills/migration/scripts/migrate.py --manifest CAIRN_IMPORT.yaml

Environment variables (same as cairn-mcp server):
    ARTIFACT_BUCKET             S3 bucket for artifact content (required)
    VECTORS_BUCKET              S3 Vectors bucket name (required)
    VECTORS_INDEX               S3 Vectors index name (required)
    AWS_REGION                  AWS region (required)
    BEDROCK_EMBEDDING_MODEL     Embedding model ID (default: amazon.titan-embed-text-v2:0)
    BEDROCK_EMBEDDING_DIMENSIONS  Embedding dimensions (default: 1024)
    WRITE_PREFIX                S3 key prefix for writes (default: artifacts)
    BEDROCK_TEXT_MODEL          Text generation model for descriptions
                                (default: amazon.nova-lite-v1:0)
"""

import argparse
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

import boto3
import yaml

# ---------------------------------------------------------------------------
# Logging — all output except the final JSON result goes to stderr
# ---------------------------------------------------------------------------

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(levelname)s %(message)s",
)
logger = logging.getLogger("migrate")

# ---------------------------------------------------------------------------
# Slug logic — replicated from cairn_mcp.artifact._slugify / generate_artifact_id
# ---------------------------------------------------------------------------

_MAX_SLUG_LEN = 60


def _slugify(text: str, fallback: str) -> str:
    """Normalise text into a URL/S3-safe slug."""
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", errors="ignore").decode("ascii")
    )
    lower = ascii_text.lower()
    replaced = re.sub(r"[^a-z0-9]+", "-", lower)
    stripped = replaced.strip("-")
    truncated = stripped[:_MAX_SLUG_LEN].rstrip("-")
    return truncated if truncated else fallback


def generate_artifact_id(*, tier: int, artifact_type: str, date: str, title: str) -> str:
    """Generate a deterministic artifact ID.

    Tier 2: {type_slug}-{date}-{title_slug}
    Tier 3: {type_slug}-{title_slug}
    """
    type_slug = artifact_type.replace("_", "-")
    title_slug = _slugify(title, "artifact")
    if tier == 3:
        return f"{type_slug}-{title_slug}"
    return f"{type_slug}-{date}-{title_slug}"


def section_slug(heading: str) -> str:
    """Normalise a section heading into a URL/S3-safe slug."""
    return _slugify(heading, "section")


# ---------------------------------------------------------------------------
# Section parsing — replicated from cairn_mcp.artifact.parse_sections
# ---------------------------------------------------------------------------


def parse_sections(content: str) -> list[tuple[str, str]]:
    """Split Markdown on H2 headings. Returns list of (heading, body) tuples."""
    pattern = re.compile(r"^## (.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return []
    sections = []
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[body_start:body_end].strip()
        sections.append((heading, body))
    return sections


# ---------------------------------------------------------------------------
# Date recovery via git log
# ---------------------------------------------------------------------------


def _extract_frontmatter_date(content: str) -> str | None:
    """Return date: field from YAML frontmatter if present."""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None
    fm_text = match.group(1)
    date_match = re.search(r"^date:\s*['\"]?(\d{4}-\d{2}-\d{2})", fm_text, re.MULTILINE)
    if date_match:
        return date_match.group(1)
    return None


def _extract_filename_date(path: str) -> str | None:
    """Return YYYY-MM-DD if embedded in filename."""
    basename = Path(path).stem
    match = re.search(r"(\d{4}-\d{2}-\d{2})", basename)
    return match.group(1) if match else None


def _git_date(path: str, tier: int) -> str | None:
    """Recover date via git log. Returns ISO date string or None."""
    try:
        if tier == 2:
            result = subprocess.run(
                ["git", "log", "--diff-filter=A", "--format=%ad", "--date=short", "--", path],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            result = subprocess.run(
                ["git", "log", "--format=%ad", "--date=short", "-1", "--", path],
                capture_output=True,
                text=True,
                check=False,
            )
        date_str = result.stdout.strip()
        if date_str:
            # Take first line only (head -1 equivalent)
            return date_str.splitlines()[0]
        return None
    except Exception as exc:
        logger.warning("git log failed for %s: %s", path, exc)
        return None


def resolve_date(path: str, tier: int, date_override: str | None, content: str) -> tuple[str, str]:
    """Resolve the artifact date and return (date_str, date_source).

    Priority order:
      1. date_override (from manifest entry)
      2. frontmatter date: field
      3. YYYY-MM-DD pattern in filename
      4. git log (first commit for tier 2, last commit for tier 3)
      5. today (fallback)
    """
    if date_override:
        return date_override, "override"

    fm_date = _extract_frontmatter_date(content)
    if fm_date:
        return fm_date, "frontmatter"

    fn_date = _extract_filename_date(path)
    if fn_date:
        return fn_date, "filename"

    git_d = _git_date(path, tier)
    if git_d:
        source = "git_first_commit" if tier == 2 else "git_last_commit"
        return git_d, source

    today = datetime.date.today().isoformat()
    logger.warning(
        "No git history or date found for %s — using today (%s) as fallback", path, today
    )
    return today, "fallback"


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------


def extract_title(content: str, path: str, title_override: str | None) -> str:
    """Extract title from H1 heading, override, or cleaned filename."""
    if title_override:
        return title_override

    match = re.search(r"^# (.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    # Clean filename: strip path, extension, date prefix, underscores/hyphens
    stem = Path(path).stem
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}[-_]?", "", stem)
    stem = stem.replace("-", " ").replace("_", " ")
    return stem.strip().title() or "Untitled"


# ---------------------------------------------------------------------------
# Description generation via Bedrock (Amazon Nova Lite)
# ---------------------------------------------------------------------------


def generate_description(
    *,
    bedrock_client: Any,
    text_model: str,
    title: str,
    artifact_type: str,
    content: str,
) -> str:
    """Generate a ≤ 280-char description using Amazon Nova Lite.

    Falls back to first 280 chars of content on any error.
    """
    preview = content[:500].strip()
    prompt = (
        f"Write a concise search-optimised description of at most 280 characters "
        f"for this {artifact_type} document. Focus on the specific decision, outcome, "
        f"or finding — avoid 'This document describes...' preamble. "
        f"Title: {title}. Content preview: {preview}"
    )

    try:
        body = json.dumps(
            {
                "messages": [{"role": "user", "content": [{"text": prompt}]}],
                "inferenceConfig": {"maxTokens": 128, "temperature": 0.3},
            }
        )
        response = bedrock_client.invoke_model(modelId=text_model, body=body)
        response_body = json.loads(response["body"].read())
        # Nova Lite response format
        text = response_body["output"]["message"]["content"][0]["text"].strip()
        # Trim to last word boundary ≤ 280 chars
        if len(text) > 280:
            text = text[:280].rsplit(" ", 1)[0]
        return text
    except Exception as exc:
        logger.warning("Bedrock description generation failed (%s) — using content fallback", exc)
        # Fallback: first 280 chars trimmed to last word
        fallback = content.replace("\n", " ").strip()[:280]
        if len(content.replace("\n", " ").strip()) > 280:
            fallback = fallback.rsplit(" ", 1)[0]
        return fallback or title


# ---------------------------------------------------------------------------
# Embedding via Bedrock (Titan Text Embeddings v2)
# ---------------------------------------------------------------------------


def embed_text(
    *,
    bedrock_client: Any,
    model_id: str,
    dimensions: int,
    text: str,
) -> list[float]:
    """Generate an embedding vector via Bedrock."""
    body = json.dumps({"inputText": text, "dimensions": dimensions})
    response = bedrock_client.invoke_model(modelId=model_id, body=body)
    response_body = json.loads(response["body"].read())
    return response_body["embedding"]


# ---------------------------------------------------------------------------
# Embedding text builders — same format as write.py
# ---------------------------------------------------------------------------


def _section_embed_text(
    title: str,
    artifact_type: str,
    feature_tags: list[str],
    section_heading: str,
    section_body: str,
) -> str:
    lines = [f"Title: {title}", f"Type: {artifact_type}"]
    if feature_tags:
        lines.append(f"Tags: {', '.join(feature_tags)}")
    lines.append("")
    lines.append(f"## {section_heading}")
    lines.append(section_body)
    return "\n".join(lines)


def _document_embed_text(
    title: str,
    artifact_type: str,
    feature_tags: list[str],
    description: str,
) -> str:
    lines = [f"Title: {title}", f"Type: {artifact_type}"]
    if feature_tags:
        lines.append(f"Tags: {', '.join(feature_tags)}")
    lines.append(f"Description: {description}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write one artifact to S3 + S3 Vectors
# ---------------------------------------------------------------------------


def write_artifact(
    *,
    s3_client: Any,
    vectors_client: Any,
    bedrock_client: Any,
    artifact_bucket: str,
    vectors_bucket: str,
    vectors_index: str,
    write_prefix: str,
    embedding_model: str,
    embedding_dimensions: int,
    artifact_id: str,
    artifact_type: str,
    team: str,
    project: str,
    tier: int,
    date: str,
    title: str,
    description: str,
    content: str,
    visibility: str,
    feature_tags: list[str],
    status: str = "active",
) -> int:
    """Write an artifact to S3 and index its sections in S3 Vectors.

    Returns the number of section vectors indexed.
    Raises on any unrecoverable error.
    """
    s3_key = f"{write_prefix}/{artifact_id}"

    # ── S3 metadata (all string values) ──────────────────────────────────────
    s3_metadata = {
        "type": artifact_type,
        "team": team,
        "project": project,
        "tier": str(tier),
        "date": date,
        "status": status,
        "title": title,
        "visibility": visibility,
        "feature_tags": ",".join(feature_tags),
        "author_role": "",
        "description": description,
        "source_artifacts": "",
    }

    # ── Write to S3 ──────────────────────────────────────────────────────────
    s3_client.put_object(
        Bucket=artifact_bucket,
        Key=s3_key,
        Body=content.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
        Metadata=s3_metadata,
    )
    logger.info("S3 PutObject: %s", s3_key)

    # ── Vector metadata ───────────────────────────────────────────────────────
    vector_metadata: dict[str, Any] = {
        "artifact_id": s3_key,
        "scope": write_prefix,
        "type": artifact_type,
        "team": team,
        "project": project,
        "tier": tier,
        "date": date,
        "status": status,
        "title": title,
        "visibility": visibility,
        "author_role": "",
        "description": description,
    }
    if feature_tags:
        vector_metadata["feature_tags"] = feature_tags

    # ── Parse sections and embed ──────────────────────────────────────────────
    sections = parse_sections(content)
    new_keys = []

    if sections:
        for heading, body in sections:
            embed_input = _section_embed_text(title, artifact_type, feature_tags, heading, body)
            vec = embed_text(
                bedrock_client=bedrock_client,
                model_id=embedding_model,
                dimensions=embedding_dimensions,
                text=embed_input,
            )
            vec_key = f"{s3_key}#{section_slug(heading)}"
            vectors_client.put_vectors(
                vectorBucketName=vectors_bucket,
                indexName=vectors_index,
                vectors=[{"key": vec_key, "data": {"float32": vec}, "metadata": vector_metadata}],
            )
            new_keys.append(vec_key)
            logger.debug("Vector upserted: %s", vec_key)
    else:
        embed_input = _document_embed_text(title, artifact_type, feature_tags, description)
        vec = embed_text(
            bedrock_client=bedrock_client,
            model_id=embedding_model,
            dimensions=embedding_dimensions,
            text=embed_input,
        )
        vectors_client.put_vectors(
            vectorBucketName=vectors_bucket,
            indexName=vectors_index,
            vectors=[{"key": s3_key, "data": {"float32": vec}, "metadata": vector_metadata}],
        )
        new_keys.append(s3_key)
        logger.debug("Document-level vector upserted: %s", s3_key)

    return len(new_keys)


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_manifest(manifest_path: str) -> dict[str, Any]:
    """Load and validate the CAIRN_IMPORT.yaml manifest."""
    with open(manifest_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("Manifest must be a YAML mapping at the top level")
    if "global" not in data:
        raise ValueError("Manifest is missing required 'global' section")
    if "artifacts" not in data:
        raise ValueError("Manifest is missing required 'artifacts' section")
    return data


# ---------------------------------------------------------------------------
# Entry processing
# ---------------------------------------------------------------------------


def process_entry(
    *,
    entry: dict[str, Any],
    global_cfg: dict[str, Any],
    bedrock_client: Any,
    text_model: str,
    embedding_model: str,
    embedding_dimensions: int,
    dry_run: bool,
    s3_client: Any,
    vectors_client: Any,
    artifact_bucket: str,
    vectors_bucket: str,
    vectors_index: str,
    write_prefix: str,
) -> dict[str, Any]:
    """Process one manifest entry. Returns the result dict."""
    path = entry["path"]
    artifact_type = entry["type"]
    tier = int(entry["tier"])
    visibility = entry.get("visibility") or global_cfg.get("visibility", "shared")
    title_override = entry.get("title") or None
    description_override = entry.get("description_override") or None
    date_override = entry.get("date_override") or None
    feature_tags: list[str] = entry.get("feature_tags") or []
    team = global_cfg["team"]
    project = global_cfg["project"]

    # Read file
    file_path = Path(path)
    if not file_path.exists():
        logger.warning("File not found, skipping: %s", path)
        return {
            "path": path,
            "artifact_id": None,
            "error": f"File not found: {path}",
        }

    content = file_path.read_text(encoding="utf-8")

    # Title
    title = extract_title(content, path, title_override)

    # Date
    date_str, date_source = resolve_date(path, tier, date_override, content)

    # Artifact ID
    artifact_id = generate_artifact_id(
        tier=tier, artifact_type=artifact_type, date=date_str, title=title
    )
    s3_key = f"{write_prefix}/{artifact_id}"

    # Description
    if description_override:
        description = description_override
    else:
        description = generate_description(
            bedrock_client=bedrock_client,
            text_model=text_model,
            title=title,
            artifact_type=artifact_type,
            content=content,
        )

    # Section count
    sections = parse_sections(content)
    sections_count = len(sections) if sections else 1

    result: dict[str, Any] = {
        "artifact_id": artifact_id,
        "title": title,
        "type": artifact_type,
        "tier": tier,
        "date": date_str,
        "date_source": date_source,
        "description": description,
        "sections_count": sections_count,
        "s3_key": s3_key,
        "would_write": True,
    }

    if dry_run:
        return result

    # Write
    try:
        indexed = write_artifact(
            s3_client=s3_client,
            vectors_client=vectors_client,
            bedrock_client=bedrock_client,
            artifact_bucket=artifact_bucket,
            vectors_bucket=vectors_bucket,
            vectors_index=vectors_index,
            write_prefix=write_prefix,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            team=team,
            project=project,
            tier=tier,
            date=date_str,
            title=title,
            description=description,
            content=content,
            visibility=visibility,
            feature_tags=feature_tags,
        )
        logger.info("Written: %s (%d sections indexed)", artifact_id, indexed)
        result["written"] = True
        result["error"] = None
    except Exception as exc:
        logger.error("Failed to write %s: %s", artifact_id, exc)
        result["written"] = False
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_clients(aws_region: str, aws_profile: str | None) -> tuple[Any, Any, Any]:
    """Build boto3 clients for S3, S3 Vectors, and Bedrock."""
    session_kwargs: dict[str, Any] = {"region_name": aws_region}
    if aws_profile:
        session_kwargs["profile_name"] = aws_profile

    session = boto3.Session(**session_kwargs)
    s3_client = session.client("s3")
    vectors_client = session.client("s3vectors")
    bedrock_client = session.client(
        "bedrock-runtime", region_name=aws_region
    )
    return s3_client, vectors_client, bedrock_client


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="migrate",
        description="Bulk import existing repo documentation into cairn-mcp.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview — no writes
  uv run skills/migration/scripts/migrate.py --manifest CAIRN_IMPORT.yaml --dry-run

  # Full import
  uv run skills/migration/scripts/migrate.py --manifest CAIRN_IMPORT.yaml

Environment variables (same as cairn-mcp server):
  ARTIFACT_BUCKET             S3 bucket for artifact content (required)
  VECTORS_BUCKET              S3 Vectors bucket name (required)
  VECTORS_INDEX               S3 Vectors index name (required)
  AWS_REGION                  AWS region (required)
  WRITE_PREFIX                S3 key prefix (default: artifacts)
  BEDROCK_EMBEDDING_MODEL     Embedding model ID
  BEDROCK_EMBEDDING_DIMENSIONS  Embedding dimensions (default: 1024)
  BEDROCK_TEXT_MODEL          Text generation model for descriptions
                              (default: amazon.nova-lite-v1:0)
""",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="PATH",
        help="Path to CAIRN_IMPORT.yaml manifest file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Output JSON preview to stdout without writing to S3 or S3 Vectors. "
            "Descriptions are still generated so you can review quality."
        ),
    )
    args = parser.parse_args()

    # ── Environment variables ─────────────────────────────────────────────────
    artifact_bucket = os.environ.get("ARTIFACT_BUCKET", "")
    vectors_bucket = os.environ.get("VECTORS_BUCKET", "")
    vectors_index = os.environ.get("VECTORS_INDEX", "")
    aws_region = os.environ.get("AWS_REGION", "")
    write_prefix = os.environ.get("WRITE_PREFIX", "artifacts").strip("/")
    embedding_model = os.environ.get(
        "BEDROCK_EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0"
    )
    embedding_dimensions = int(os.environ.get("BEDROCK_EMBEDDING_DIMENSIONS", "1024"))
    text_model = os.environ.get("BEDROCK_TEXT_MODEL", "amazon.nova-lite-v1:0")
    aws_profile = os.environ.get("AWS_PROFILE") or None

    missing = [
        name
        for name, val in [
            ("ARTIFACT_BUCKET", artifact_bucket),
            ("VECTORS_BUCKET", vectors_bucket),
            ("VECTORS_INDEX", vectors_index),
            ("AWS_REGION", aws_region),
        ]
        if not val
    ]
    if missing:
        print(  # noqa: T201 — stderr for errors
            f"ERROR: Required environment variables not set: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not write_prefix:
        print("ERROR: WRITE_PREFIX must not be empty", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    # ── Load manifest ─────────────────────────────────────────────────────────
    try:
        manifest = load_manifest(args.manifest)
    except Exception as exc:
        print(f"ERROR: Failed to load manifest: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    global_cfg: dict[str, Any] = manifest.get("global", {})
    entries: list[dict[str, Any]] = manifest.get("artifacts", [])

    if not global_cfg.get("team") or not global_cfg.get("project"):
        print(  # noqa: T201
            "ERROR: Manifest global section must specify 'team' and 'project'",
            file=sys.stderr,
        )
        sys.exit(1)

    # Override write_prefix from manifest if specified
    manifest_prefix = global_cfg.get("write_prefix", "").strip()
    if manifest_prefix:
        write_prefix = manifest_prefix.strip("/")

    logger.info(
        "Loaded manifest: %d entries | team=%s project=%s write_prefix=%s dry_run=%s",
        len(entries),
        global_cfg["team"],
        global_cfg["project"],
        write_prefix,
        args.dry_run,
    )

    # ── Build AWS clients ─────────────────────────────────────────────────────
    try:
        s3_client, vectors_client, bedrock_client = build_clients(aws_region, aws_profile)
    except Exception as exc:
        print(f"ERROR: Failed to initialise AWS clients: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    # ── Process entries ───────────────────────────────────────────────────────
    results = []
    for i, entry in enumerate(entries):
        logger.info(
            "[%d/%d] Processing: %s", i + 1, len(entries), entry.get("path", "<no path>")
        )
        try:
            result = process_entry(
                entry=entry,
                global_cfg=global_cfg,
                bedrock_client=bedrock_client,
                text_model=text_model,
                embedding_model=embedding_model,
                embedding_dimensions=embedding_dimensions,
                dry_run=args.dry_run,
                s3_client=s3_client,
                vectors_client=vectors_client,
                artifact_bucket=artifact_bucket,
                vectors_bucket=vectors_bucket,
                vectors_index=vectors_index,
                write_prefix=write_prefix,
            )
        except Exception as exc:
            logger.error("Unexpected error processing %s: %s", entry.get("path"), exc)
            result = {
                "path": entry.get("path"),
                "artifact_id": None,
                "error": str(exc),
                "written": False,
            }
        results.append(result)

    # ── Output JSON to stdout ─────────────────────────────────────────────────
    print(json.dumps(results, indent=2, default=str))  # noqa: T201 — JSON to stdout

    # Summary to stderr
    if not args.dry_run:
        written = sum(1 for r in results if r.get("written"))
        failed = sum(1 for r in results if r.get("error") and not r.get("written"))
        logger.info("Done: %d written, %d failed", written, failed)
    else:
        logger.info("Dry run complete: %d entries previewed (no writes)", len(results))


if __name__ == "__main__":
    main()
