from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any


def get_output_dir() -> Path:
    """Resolve and create the base output directory for MCP tool results."""
    env_dir = os.environ.get("ANKI_MCP_OUTPUT_DIR")
    out_dir = (
        Path(env_dir).expanduser().resolve()
        if env_dir
        else Path(tempfile.gettempdir()) / "anki_mcp"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def write_tool_output(
    data: Any, prefix: str = "output", output_file: str | Path | None = None
) -> Path:
    """Serialize structured data to a JSON output file on disk.

    If `output_file` is provided, writes to that exact path.
    Otherwise, generates a timestamped file in `get_output_dir()`.
    """
    if output_file:
        target_path = Path(output_file).expanduser().resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:6]
        target_path = get_output_dir() / f"{prefix}_{timestamp}_{unique_id}.json"

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return target_path


def read_json_file(file_path: str | Path) -> Any:
    """Read and parse a JSON payload from disk with informative error handling."""
    p = Path(file_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Input file not found at: {p}")
    if not p.is_file():
        raise ValueError(f"Specified path is not a file: {p}")

    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in input file '{p}': {e}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to read input file '{p}': {e}") from e


def format_telemetry(
    operation: str,
    summary: dict[str, Any],
    output_file: Path | str | None = None,
    status: str = "success",
) -> dict[str, Any]:
    """Format a standard bounded telemetry response object for MCP clients."""
    result: dict[str, Any] = {
        "status": status,
        "operation": operation,
        "summary": summary,
    }
    if output_file is not None:
        result["output_file"] = str(Path(output_file).resolve())
    return result


def make_response(
    operation: str,
    payload: Any,
    summary: dict[str, Any],
    output_file: Path | str | None = None,
    prefix: str | None = None,
    status: str = "success",
) -> dict[str, Any]:
    """Serialize payload to disk and return a formatted bounded telemetry response."""
    out_path = write_tool_output(
        payload, prefix=prefix or operation, output_file=output_file
    )
    return format_telemetry(
        operation=operation,
        summary=summary,
        output_file=out_path,
        status=status,
    )
