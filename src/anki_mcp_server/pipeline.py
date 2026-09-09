from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anki.collection import Collection

from anki_mcp_server.collection import get_collection
from anki_mcp_server.io_utils import format_telemetry, read_json_file, write_tool_output


def _project_summary(data: Any) -> dict[str, Any]:
    """Convention-driven auto-projection of domain payloads into bounded telemetry summaries."""
    if isinstance(data, list):
        summary: dict[str, Any] = {"total_matches": len(data)}
        if not data:
            return summary

        sample = data[:5]
        first = data[0]
        if isinstance(first, dict):
            if "note_id" in first:
                summary["sample_note_ids"] = [item["note_id"] for item in sample]
            elif "card_id" in first:
                summary["sample_card_ids"] = [item["card_id"] for item in sample]
            elif "name" in first:
                summary["sample_names"] = [item["name"] for item in sample]
            elif "id" in first:
                summary["sample_ids"] = [item["id"] for item in sample]
        elif isinstance(first, (int, str)):
            summary["sample_items"] = sample

        return summary

    if isinstance(data, dict):
        # Extract lightweight scalar values, avoid serializing deep lists into telemetry
        summary = {}
        for k, v in data.items():
            if isinstance(v, (int, str, bool, float)) or v is None:
                summary[k] = v
            elif isinstance(v, list):
                summary[f"{k}_count"] = len(v)
                if v and isinstance(v[0], (int, str)):
                    summary[f"sample_{k}"] = v[:5]
        return summary

    return {"result": str(data)}


def execute_tool(
    operation: str,
    action: Callable[[Collection, Any], Any],
    input_file: str | None = None,
    output_file: str | None = None,
    prefix: str | None = None,
    summary_fn: Callable[[Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deep execution pipeline encapsulating file parsing, collection session, and telemetry emission."""
    t0 = time.perf_counter()

    parsed_input = read_json_file(input_file) if input_file else None

    with get_collection() as col:
        result = action(col, parsed_input)

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)

    # Determine summary
    if summary_fn is not None:
        summary = summary_fn(result)
    elif isinstance(result, dict) and "summary" in result and "payload" in result:
        summary = result["summary"]
        result = result["payload"]
    else:
        summary = _project_summary(result)

    summary["duration_ms"] = duration_ms

    out_path = write_tool_output(
        result,
        prefix=prefix or operation,
        output_file=output_file,
    )

    return format_telemetry(
        operation=operation,
        summary=summary,
        output_file=Path(out_path),
        status="success",
    )
