from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from archscope.model import ArchitectureError, load_architecture
from archscope.service.registry import ProjectRegistryError, control_artifact_path

if TYPE_CHECKING:
    from archscope.service.registry import RegisteredProject


_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class HistoryError(ValueError):
    def __init__(self, diagnostic_id: str, message: str):
        super().__init__(message)
        self.diagnostic_id = diagnostic_id


class ArchitectureArchive:
    """Immutable, digest-addressed copies of architecture revisions used as evidence."""

    @staticmethod
    def _path(project: RegisteredProject, digest: str) -> Path:
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise HistoryError("ARCHIVE_REVISION_INVALID", "Invalid architecture revision digest")
        try:
            return control_artifact_path(project, "architectures", f"{digest}.arch")
        except ProjectRegistryError as exc:
            raise HistoryError("ARCHIVE_PATH_ESCAPE", str(exc)) from exc

    @classmethod
    def load(cls, project: RegisteredProject, digest: str, schema_path: Path) -> Any:
        path = cls._path(project, digest)
        if path.is_symlink():
            raise HistoryError("ARCHIVE_CORRUPT", "Archived architecture must not be a symbolic link")
        if not path.is_file():
            raise HistoryError("ARCHIVE_NOT_FOUND", f"Architecture revision was not archived: {digest}")
        try:
            document = load_architecture(path, schema_path)
        except ArchitectureError as exc:
            raise HistoryError("ARCHIVE_CORRUPT", f"Cannot validate archived architecture: {exc}") from exc
        if document.digest != digest or document.model["project"]["id"] != project.project_id:
            raise HistoryError("ARCHIVE_CORRUPT", "Archived architecture digest or project ID does not match")
        return document

    @classmethod
    def list(cls, project: RegisteredProject, schema_path: Path) -> list[dict[str, str]]:
        try:
            root = control_artifact_path(project, "architectures")
        except ProjectRegistryError:
            return []
        if not root.is_dir():
            return []
        revisions: list[tuple[float, dict[str, str]]] = []
        for path in root.glob("*.arch"):
            try:
                document = cls.load(project, path.stem, schema_path)
                revisions.append((path.stat().st_mtime, {"digest": document.digest, "name": document.model["project"]["name"]}))
            except (HistoryError, OSError):
                continue
        return [item for _, item in sorted(revisions, key=lambda pair: pair[0], reverse=True)]

    @classmethod
    def save(cls, project: RegisteredProject, document: Any, schema_path: Path) -> Path:
        path = cls._path(project, document.digest)
        temporary = path.parent / f".{uuid.uuid4().hex}.arch.tmp"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                cls.load(project, document.digest, schema_path)
                return path
            temporary.write_text(document.path.read_text(encoding="utf-8"), encoding="utf-8")
            frozen = load_architecture(temporary, schema_path)
            if frozen.digest != document.digest or frozen.model["project"]["id"] != project.project_id:
                raise HistoryError("ARCHIVE_SOURCE_CHANGED", "Architecture changed during archival; read the current revision again")
            try:
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(temporary.read_text(encoding="utf-8"))
            except FileExistsError:
                pass
            cls.load(project, document.digest, schema_path)
            return path
        except ArchitectureError as exc:
            raise HistoryError("ARCHIVE_SOURCE_CHANGED", f"Architecture changed during archival: {exc}") from exc
        except (OSError, UnicodeError) as exc:
            raise HistoryError("ARCHIVE_IO_ERROR", f"Cannot save architecture snapshot: {exc}") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
