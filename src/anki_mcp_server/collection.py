from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from anki.collection import Collection
from anki.errors import AnkiError, DBError


def get_default_collection_path() -> Path:
    """Resolve the default Anki collection.anki2 path based on environment variables or OS standard locations."""
    # 1. Environment variable override
    env_path = os.environ.get("ANKI_COLLECTION_PATH")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if p.exists():
            return p
        raise FileNotFoundError(
            f"Anki collection specified in ANKI_COLLECTION_PATH not found: {p}"
        )

    # 2. Known standard OS base directories
    candidate_bases: list[Path] = [
        # Linux standard
        Path.home() / ".local" / "share" / "Anki2",
        # macOS standard
        Path.home() / "Library" / "Application Support" / "Anki2",
    ]

    # Windows standard locations
    if appdata := os.environ.get("APPDATA"):
        candidate_bases.append(Path(appdata) / "Anki2")
    if localappdata := os.environ.get("LOCALAPPDATA"):
        candidate_bases.append(Path(localappdata) / "Anki2")
    candidate_bases.extend(
        [
            Path.home() / "AppData" / "Roaming" / "Anki2",
            Path.home() / "AppData" / "Local" / "Anki2",
        ]
    )

    # Filter to existing unique base directories
    existing_bases: list[Path] = []
    seen: set[Path] = set()
    for base in candidate_bases:
        resolved = base.expanduser().resolve()
        if resolved.exists() and resolved not in seen:
            seen.add(resolved)
            existing_bases.append(resolved)

    ignored_dir_names = {
        "addons",
        "addons21",
        "logs",
        "backup",
        "backups",
        "temp",
        "tmp",
    }

    # Preferred default profile names to check first
    preferred_profiles = ["User 1", "Main", "Default"]

    for base_dir in existing_bases:
        # Check preferred profile names first
        for prof in preferred_profiles:
            candidate = base_dir / prof / "collection.anki2"
            if candidate.is_file():
                return candidate

        # Search all subdirectories for a valid collection.anki2
        try:
            for user_dir in sorted(base_dir.iterdir()):
                if (
                    user_dir.is_dir()
                    and not user_dir.name.startswith((".", "_"))
                    and user_dir.name.lower() not in ignored_dir_names
                ):
                    candidate = user_dir / "collection.anki2"
                    if candidate.is_file():
                        return candidate
        except OSError:
            continue

    raise FileNotFoundError(
        "Could not find an Anki collection (collection.anki2) in standard locations:\n"
        "  - Windows: %APPDATA%\\Anki2\\<Profile>\\collection.anki2\n"
        "  - macOS: ~/Library/Application Support/Anki2/<Profile>/collection.anki2\n"
        "  - Linux: ~/.local/share/Anki2/<Profile>/collection.anki2\n"
        "Please specify the path to your collection via the ANKI_COLLECTION_PATH environment variable."
    )


@contextmanager
def get_collection(
    path: Path | str | None = None,
) -> Generator[Collection, None, None]:
    """Context manager for safely opening and closing an Anki collection.

    Ensures the SQLite connection and locks are cleanly released after every operation.
    """
    col_path = (
        Path(path).expanduser().resolve() if path else get_default_collection_path()
    )
    if not col_path.exists():
        raise FileNotFoundError(f"Anki collection file not found at: {col_path}")

    try:
        col = Collection(str(col_path))
    except DBError as e:
        raise RuntimeError(
            f"Anki collection database at '{col_path}' is currently locked. "
            "The Anki desktop application appears to be open or media is syncing. "
            "Please close the Anki desktop app and retry."
        ) from e
    except AnkiError as e:
        raise RuntimeError(f"Failed to open Anki collection: {e}") from e

    try:
        yield col
    finally:
        col.close()
