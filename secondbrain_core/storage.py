from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_markdown(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise ValueError("record is missing YAML front matter")
    first_line_end = text.find("\n")
    if first_line_end < 0:
        raise ValueError("invalid front matter opening")
    closing = text.find("\n---", first_line_end + 1)
    if closing < 0:
        raise ValueError("record is missing YAML front matter closing marker")
    metadata = yaml.safe_load(text[first_line_end + 1 : closing]) or {}
    body = text[closing + len("\n---") :].lstrip("\n")
    if not isinstance(metadata, dict):
        raise ValueError("front matter must contain a mapping")
    return metadata, body


def render_markdown(metadata: dict[str, Any], body: str) -> str:
    header = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{header}\n---\n\n{body.rstrip()}\n"


def read_record(path: Path) -> tuple[dict[str, Any], str, str]:
    text = path.read_text(encoding="utf-8")
    metadata, body = parse_markdown(text)
    return metadata, body, text


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_record(path: Path, metadata: dict[str, Any], body: str) -> str:
    text = render_markdown(metadata, body)
    atomic_write(path, text)
    return text


def append_event(path: Path, event_type: str, fields: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"\n## {utc_now()} · {event_type}", ""]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"- {key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"- {key}: {value}")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def append_audit(body: str, message: str) -> str:
    marker = "## 审核记录"
    if marker not in body:
        body = body.rstrip() + f"\n\n{marker}\n"
    return body.rstrip() + f"\n- {utc_now()}：{message}\n"
