from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, runtime_checkable

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


@runtime_checkable
class CollectionAdapter(Protocol):
    """Protocol defining the collection operations seam."""

    @contextmanager
    def session(self) -> Generator[Collection, None, None]:
        """Provide a safe, scoped Anki Collection instance with cleanup."""
        ...


class NativeAnkiAdapter:
    """Production adapter interacting directly with an on-disk Anki SQLite collection."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = path

    @contextmanager
    def session(self) -> Generator[Collection, None, None]:
        col_path = (
            Path(self._path).expanduser().resolve()
            if self._path
            else get_default_collection_path()
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


class IsolatedAnkiAdapter:
    """Ephemeral collection adapter creating isolated scratch fixtures for hermetic testing."""

    _base_template_dir: Path | None = None

    def __init__(self, scratch_dir: Path | str | None = None) -> None:
        self._scratch_dir = Path(scratch_dir) if scratch_dir else None
        self._col_path: Path | None = None

    @classmethod
    def _get_or_create_base_template(cls) -> Path:
        if cls._base_template_dir is None or not cls._base_template_dir.exists():
            cls._base_template_dir = Path(tempfile.mkdtemp(prefix="anki_mcp_template_"))
            col = Collection(str(cls._base_template_dir / "collection.anki2"))
            col.close()
        return cls._base_template_dir

    def setup(self) -> Path:
        base_dir = self._get_or_create_base_template()
        target_dir = self._scratch_dir or Path(
            tempfile.mkdtemp(prefix="anki_mcp_isolated_")
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "collection.anki2"

        src_file = base_dir / "collection.anki2"

        # Try cross-platform CoW reflink, falling back to copy on NTFS / tmpfs
        cloned = False
        if os.name != "nt":
            res = subprocess.run(
                ["cp", "-a", "--reflink=always", str(src_file), str(target_file)],
                capture_output=True,
                check=False,
            )
            cloned = res.returncode == 0

        if not cloned:
            shutil.copy2(src_file, target_file)

        self._col_path = target_file
        return self._col_path

    def cleanup(self) -> None:
        if self._col_path and self._col_path.parent.exists():
            shutil.rmtree(self._col_path.parent, ignore_errors=True)
        self._col_path = None

    @contextmanager
    def session(self) -> Generator[Collection, None, None]:
        if not self._col_path or not self._col_path.exists():
            self.setup()
        assert self._col_path is not None

        try:
            col = Collection(str(self._col_path))
        except DBError as e:
            raise RuntimeError(
                f"Isolated collection database at '{self._col_path}' is locked."
            ) from e
        except AnkiError as e:
            raise RuntimeError(f"Failed to open isolated collection: {e}") from e

        try:
            yield col
        finally:
            col.close()


_current_adapter: CollectionAdapter = NativeAnkiAdapter()


def set_collection_adapter(adapter: CollectionAdapter) -> None:
    """Configure the active collection adapter across the operations seam."""
    global _current_adapter
    _current_adapter = adapter


def get_collection_adapter() -> CollectionAdapter:
    """Retrieve the current active collection adapter."""
    return _current_adapter


@contextmanager
def get_collection(
    path: Path | str | None = None,
) -> Generator[Collection, None, None]:
    """Context manager for safely accessing an Anki collection.

    If an explicit `path` is passed, opens that path directly via NativeAnkiAdapter.
    Otherwise, delegates to the currently active CollectionAdapter at the operations seam.
    """
    if path is not None:
        with NativeAnkiAdapter(path).session() as col:
            yield col
    else:
        with _current_adapter.session() as col:
            yield col
