from __future__ import annotations

import ast
import glob
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from archscope.service.registry import RegisteredProject


CHECKER_VERSION = "0.1.0"


@dataclass(frozen=True)
class SourceFile:
    path: Path
    relative: str
    import_name: str
    owners: tuple[str, ...]


def _source_roots(project: "RegisteredProject", model: dict[str, Any]) -> list[Path]:
    roots: list[Path] = []
    for value in model["project"]["source_roots"]:
        root = (project.root / value).resolve()
        if not root.is_relative_to(project.root):
            raise ValueError(f"SOURCE_PATH_ESCAPE: {value}")
        roots.append(root)
    return roots


def _import_name(path: Path, roots: list[Path]) -> str:
    for root in roots:
        if path.is_relative_to(root):
            relative = path.relative_to(root).with_suffix("")
            parts = list(relative.parts)
            if parts and parts[-1] == "__init__":
                parts.pop()
            return ".".join(parts)
    return ""


def compute_code_digest(project: "RegisteredProject", model: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for root in _source_roots(project, model):
        if not root.is_dir():
            digest.update(f"missing:{root.relative_to(project.root).as_posix()}".encode("utf-8"))
            continue
        for source in sorted(root.rglob("*.py")):
            resolved = source.resolve()
            if not resolved.is_relative_to(project.root):
                continue
            digest.update(resolved.relative_to(project.root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(resolved.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


class ArchitectureChecker:
    def __init__(self, project: "RegisteredProject", document: Any):
        self.project = project
        self.document = document
        self.model = document.model
        self.diagnostics: list[dict[str, Any]] = []
        self.roots = _source_roots(project, self.model)

    def _diagnostic(
        self,
        diagnostic_id: str,
        message: str,
        *,
        status: str = "FAIL",
        module_id: str | None = None,
        target_module_id: str | None = None,
        path: str | None = None,
        line: int | None = None,
        rule_id: str | None = None,
    ) -> None:
        self.diagnostics.append({
            "diagnostic_id": diagnostic_id,
            "status": status,
            "message": message,
            "module_id": module_id,
            "target_module_id": target_module_id,
            "path": path,
            "line": line,
            "rule_id": rule_id,
        })

    def _binding_matches(self) -> dict[str, set[Path]]:
        matches: dict[str, set[Path]] = {}
        for module in self.model["modules"]:
            binding = module.get("binding")
            if not binding:
                continue
            module_files: set[Path] = set()
            for pattern in binding["files"]:
                absolute_pattern = self.project.root / Path(pattern)
                for value in glob.glob(str(absolute_pattern), recursive=True):
                    path = Path(value).resolve()
                    if not path.is_relative_to(self.project.root):
                        self._diagnostic(
                            "SOURCE_PATH_ESCAPE",
                            f"Binding path escapes the project root: {pattern}",
                            module_id=module["id"],
                            path=str(path),
                        )
                    elif path.is_file() and path.suffix == ".py":
                        module_files.add(path)
            matches[module["id"]] = module_files
            if not module_files:
                self._diagnostic(
                    "BINDING_EMPTY",
                    f"Source binding for module {module['id']} matched no Python files",
                    module_id=module["id"],
                )
        return matches

    def _inventory(self, matches: dict[str, set[Path]]) -> list[SourceFile]:
        files: list[SourceFile] = []
        found_root = False
        for root in self.roots:
            if not root.is_dir():
                self._diagnostic("SOURCE_ROOT_MISSING", f"Source root does not exist: {root.relative_to(self.project.root).as_posix()}")
                continue
            found_root = True
            for candidate in sorted(root.rglob("*.py")):
                path = candidate.resolve()
                relative = candidate.relative_to(self.project.root).as_posix()
                if not path.is_relative_to(self.project.root):
                    self._diagnostic("SOURCE_PATH_ESCAPE", f"Source file escapes the project root: {relative}", path=relative)
                    continue
                owners = tuple(sorted(module_id for module_id, module_files in matches.items() if path in module_files))
                if not owners:
                    self._diagnostic("UNOWNED_SOURCE", f"Source file has no module owner: {relative}", path=relative)
                elif len(owners) > 1:
                    self._diagnostic("FILE_OWNERSHIP_CONFLICT", f"Source file belongs to multiple modules: {', '.join(owners)}", path=relative)
                files.append(SourceFile(path=path, relative=relative, import_name=_import_name(path, self.roots), owners=owners))
        if found_root and not files:
            self._diagnostic("EMPTY_SOURCE_SCAN", "No Python files were found in the source roots")
        return files

    @staticmethod
    def _top_level_symbols(tree: ast.AST) -> set[str]:
        result: set[str] = set()
        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                result.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        result.add(target.id)
            elif isinstance(node, ast.ImportFrom):
                result.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
            elif isinstance(node, ast.Import):
                result.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        return result

    def _parse(self, files: list[SourceFile]) -> dict[Path, ast.AST]:
        trees: dict[Path, ast.AST] = {}
        for source in files:
            try:
                trees[source.path] = ast.parse(source.path.read_text(encoding="utf-8"), filename=source.relative)
            except (OSError, UnicodeError, SyntaxError) as exc:
                self._diagnostic(
                    "PYTHON_PARSE_ERROR",
                    f"Cannot statically parse {source.relative}: {exc}",
                    module_id=source.owners[0] if len(source.owners) == 1 else None,
                    path=source.relative,
                    line=getattr(exc, "lineno", None),
                )
        return trees

    def _check_entries(self, files: list[SourceFile], trees: dict[Path, ast.AST]) -> None:
        by_import = {source.import_name: source for source in files if source.import_name}
        for module in self.model["modules"]:
            binding = module.get("binding")
            if not binding:
                continue
            for entry in binding["entries"]:
                module_name, separator, symbol = entry["symbol"].partition(":")
                source = by_import.get(module_name)
                if not separator or source is None or source.path not in trees:
                    self._diagnostic("ENTRY_MODULE_MISSING", f"Public entry module does not exist: {entry['symbol']}", module_id=module["id"])
                    continue
                if symbol not in self._top_level_symbols(trees[source.path]):
                    self._diagnostic(
                        "ENTRY_SYMBOL_MISSING",
                        f"Public entry symbol does not exist: {entry['symbol']}",
                        module_id=module["id"],
                        path=source.relative,
                    )

    @staticmethod
    def _resolve_relative(source: SourceFile, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        package = source.import_name if source.path.name == "__init__.py" else source.import_name.rpartition(".")[0]
        parts = package.split(".") if package else []
        ascend = max(0, node.level - 1)
        if ascend:
            parts = parts[:-ascend] if ascend <= len(parts) else []
        if node.module:
            parts.extend(node.module.split("."))
        return ".".join(parts)

    @staticmethod
    def _target_owner(import_path: str, by_import: dict[str, SourceFile]) -> tuple[str | None, str | None]:
        candidates = [name for name in by_import if import_path == name or import_path.startswith(name + ".")]
        if not candidates:
            return None, None
        name = max(candidates, key=len)
        source = by_import[name]
        return (source.owners[0] if len(source.owners) == 1 else None), name

    def _decision(self, source: str, target: str) -> tuple[str, str | None]:
        rules = [rule for rule in self.model["policies"]["dependencies"] if rule["from"] == source and rule["to"] == target]
        denied = sorted((rule for rule in rules if rule["decision"] == "deny"), key=lambda item: item["id"])
        if denied:
            return "deny", denied[0]["id"]
        allowed = sorted((rule for rule in rules if rule["decision"] == "allow"), key=lambda item: item["id"])
        if allowed:
            return "allow", allowed[0]["id"]
        return "deny", None

    def _check_imports(self, files: list[SourceFile], trees: dict[Path, ast.AST]) -> None:
        by_import = {source.import_name: source for source in files if source.import_name}
        modules = {module["id"]: module for module in self.model["modules"]}
        for source in files:
            if len(source.owners) != 1 or source.path not in trees:
                continue
            source_owner = source.owners[0]
            for node in ast.walk(trees[source.path]):
                import_paths: list[str] = []
                if isinstance(node, ast.Import):
                    import_paths.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    import_paths.append(self._resolve_relative(source, node))
                elif isinstance(node, ast.Call):
                    is_dynamic = isinstance(node.func, ast.Name) and node.func.id == "__import__"
                    is_dynamic = is_dynamic or isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
                    if is_dynamic:
                        self._diagnostic(
                            "UNVERIFIED_DYNAMIC_IMPORT",
                            "Dynamic import detected; the static checker cannot verify its target",
                            status="UNVERIFIED",
                            module_id=source_owner,
                            path=source.relative,
                            line=getattr(node, "lineno", None),
                        )
                for import_path in filter(None, import_paths):
                    target_owner, matched_import = self._target_owner(import_path, by_import)
                    if target_owner is None or target_owner == source_owner:
                        continue
                    decision, rule_id = self._decision(source_owner, target_owner)
                    target_public = set(modules[target_owner].get("binding", {}).get("public_imports", []))
                    if decision != "allow":
                        self._diagnostic(
                            "DEPENDENCY_DENIED",
                            f"Module {source_owner} is not allowed to import {target_owner}: {import_path}",
                            module_id=source_owner,
                            target_module_id=target_owner,
                            path=source.relative,
                            line=getattr(node, "lineno", None),
                            rule_id=rule_id,
                        )
                    elif import_path not in target_public and matched_import not in target_public:
                        self._diagnostic(
                            "PRIVATE_IMPORT",
                            f"Module {source_owner} imports a private module of {target_owner}: {import_path}",
                            module_id=source_owner,
                            target_module_id=target_owner,
                            path=source.relative,
                            line=getattr(node, "lineno", None),
                            rule_id=rule_id,
                        )

    def run(self, *, strict: bool) -> dict[str, Any]:
        matches = self._binding_matches()
        files = self._inventory(matches)
        trees = self._parse(files)
        self._check_entries(files, trees)
        self._check_imports(files, trees)
        self.diagnostics.sort(key=lambda item: (
            item.get("path") or "", item.get("line") or 0, item["diagnostic_id"], item.get("module_id") or ""
        ))
        fail_count = sum(item["status"] == "FAIL" for item in self.diagnostics)
        unverified_count = sum(item["status"] == "UNVERIFIED" for item in self.diagnostics)
        status = "FAIL" if fail_count else "UNVERIFIED" if unverified_count else "PASS"
        if strict and unverified_count and not fail_count:
            status = "FAIL"
        module_states: dict[str, str] = {}
        for module in self.model["modules"]:
            module_id = module["id"]
            related = [item for item in self.diagnostics if item.get("module_id") == module_id or item.get("target_module_id") == module_id]
            if any(item["status"] == "FAIL" for item in related):
                module_states[module_id] = "FAIL"
            elif any(item["status"] == "UNVERIFIED" for item in related):
                module_states[module_id] = "UNVERIFIED"
            elif module["kind"] == "leaf":
                module_states[module_id] = "PASS"
            else:
                module_states[module_id] = "NOT_APPLICABLE"
        for module in self.model["modules"]:
            if module["kind"] != "composite":
                continue
            children = [item["id"] for item in self.model["modules"] if item.get("parent") == module["id"]]
            states = [module_states[child] for child in children]
            module_states[module["id"]] = "FAIL" if "FAIL" in states else "UNVERIFIED" if "UNVERIFIED" in states else "PASS"
        return {
            "status": status,
            "strict": strict,
            "checker_version": CHECKER_VERSION,
            "diagnostics": self.diagnostics,
            "module_states": module_states,
            "coverage": {
                "language": "python",
                "source_file_count": len(files),
                "parsed_file_count": len(trees),
                "unsupported_dynamic_imports": unverified_count,
                "limitations": ["Reflection, runtime aliases, and arbitrary object internals are outside this version's static guarantees"],
            },
        }
