from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from yaml.events import AliasEvent
from yaml.nodes import MappingNode

from archscope.paths import default_schema_path


class ArchitectureError(ValueError):
    def __init__(self, diagnostics: list[dict[str, Any]]):
        self.diagnostics = diagnostics
        message = diagnostics[0]["message"] if diagnostics else "Invalid architecture"
        super().__init__(message)


class RestrictedLoader(yaml.SafeLoader):
    """YAML loader for the .arch v0.1 restricted subset."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "aliases and anchors are not allowed in .arch files",
                event.start_mark,
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[str, Any]:
        if not isinstance(node, MappingNode):
            return super().construct_mapping(node, deep=deep)
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=False)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate key: {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


@dataclass(frozen=True)
class ArchitectureDocument:
    path: Path
    model: dict[str, Any]
    digest: str
    diagnostics: tuple[dict[str, Any], ...]

    @property
    def modules_by_id(self) -> dict[str, dict[str, Any]]:
        return {module["id"]: module for module in self.model["modules"]}

    @property
    def domains_by_id(self) -> dict[str, dict[str, Any]]:
        return {domain["id"]: domain for domain in self.model["domains"]}


def _diagnostic(
    diagnostic_id: str,
    message: str,
    *,
    path: str = "$",
    module_id: str | None = None,
    status: str = "FAIL",
) -> dict[str, Any]:
    return {
        "diagnostic_id": diagnostic_id,
        "rule_id": diagnostic_id,
        "phase": "draft",
        "module_id": module_id,
        "arch_path": path,
        "code_location": None,
        "message": message,
        "status": status,
        "action": "Correct the architecture specification and reload it.",
    }


def _schema_diagnostics(model: Any, schema_path: Path) -> list[dict[str, Any]]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    diagnostics: list[dict[str, Any]] = []
    for index, error in enumerate(sorted(validator.iter_errors(model), key=lambda item: list(item.path))):
        location = "$" + "".join(f"[{part!r}]" for part in error.absolute_path)
        diagnostics.append(
            _diagnostic(
                f"SCHEMA_{index + 1:03d}",
                error.message,
                path=location,
            )
        )
    return diagnostics


def _semantic_diagnostics(model: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    modules = model.get("modules", [])
    domains = model.get("domains", [])
    module_map: dict[str, dict[str, Any]] = {}
    domain_ids: set[str] = set()

    for index, domain in enumerate(domains):
        domain_id = domain.get("id")
        if domain_id in domain_ids:
            diagnostics.append(_diagnostic("DUPLICATE_DOMAIN", f"Duplicate domain ID: {domain_id}", path=f"$.domains[{index}].id"))
        domain_ids.add(domain_id)

    for index, module in enumerate(modules):
        module_id = module.get("id")
        if module_id in module_map:
            diagnostics.append(_diagnostic("DUPLICATE_MODULE", f"Duplicate module ID: {module_id}", path=f"$.modules[{index}].id", module_id=module_id))
        module_map[module_id] = module

    for index, module in enumerate(modules):
        module_id = module["id"]
        parent = module.get("parent")
        if parent:
            parent_module = module_map.get(parent)
            if parent_module is None:
                diagnostics.append(_diagnostic("UNKNOWN_PARENT", f"Parent module does not exist: {parent}", path=f"$.modules[{index}].parent", module_id=module_id))
            elif parent_module.get("kind") != "composite":
                diagnostics.append(_diagnostic("PARENT_NOT_COMPOSITE", f"Parent module must be composite: {parent}", path=f"$.modules[{index}].parent", module_id=module_id))

        port_ids: set[str] = set()
        for port_index, port in enumerate(module.get("ports", [])):
            port_id = port["id"]
            if port_id in port_ids:
                diagnostics.append(_diagnostic("DUPLICATE_PORT", f"Duplicate module port: {module_id}.{port_id}", path=f"$.modules[{index}].ports[{port_index}].id", module_id=module_id))
            port_ids.add(port_id)
            if port["domain"] not in domain_ids:
                diagnostics.append(_diagnostic("UNKNOWN_DOMAIN", f"Port references unknown domain: {port['domain']}", path=f"$.modules[{index}].ports[{port_index}].domain", module_id=module_id))

    for module in modules:
        seen: set[str] = set()
        current = module
        while current.get("parent"):
            parent_id = current["parent"]
            if parent_id in seen or parent_id == module["id"]:
                diagnostics.append(_diagnostic("PARENT_CYCLE", f"Module parent cycle involves {module['id']} and {parent_id}", module_id=module["id"]))
                break
            seen.add(parent_id)
            current = module_map.get(parent_id, {})
            if not current:
                break

    def get_port(endpoint: dict[str, str]) -> dict[str, Any] | None:
        target = module_map.get(endpoint.get("module"))
        if not target:
            return None
        return next((port for port in target.get("ports", []) if port["id"] == endpoint.get("port")), None)

    for index, module in enumerate(modules):
        for port_index, port in enumerate(module.get("ports", [])):
            delegate = port.get("delegate")
            if not delegate:
                continue
            target = get_port(delegate)
            if target is None:
                diagnostics.append(_diagnostic("INVALID_DELEGATE", f"Delegated port does not exist: {delegate.get('module')}.{delegate.get('port')}", path=f"$.modules[{index}].ports[{port_index}].delegate", module_id=module["id"]))
            elif target["direction"] != port["direction"] or target["domain"] != port["domain"]:
                diagnostics.append(_diagnostic("DELEGATE_MISMATCH", f"Delegated port direction or domain mismatch: {module['id']}.{port['id']}", path=f"$.modules[{index}].ports[{port_index}].delegate", module_id=module["id"]))

    for index, flow in enumerate(model.get("flows", [])):
        source = get_port(flow["from"])
        target = get_port(flow["to"])
        if source is None or target is None:
            diagnostics.append(_diagnostic("FLOW_ENDPOINT_MISSING", f"Flow {flow['id']} references a missing port", path=f"$.flows[{index}]"))
            continue
        if source["direction"] != "out" or target["direction"] != "in" or source["domain"] != target["domain"]:
            diagnostics.append(_diagnostic("FLOW_ENDPOINT_MISMATCH", f"Flow {flow['id']} has a direction or domain mismatch", path=f"$.flows[{index}]"))

    for index, dependency in enumerate(model.get("policies", {}).get("dependencies", [])):
        if dependency["from"] not in module_map or dependency["to"] not in module_map:
            diagnostics.append(_diagnostic("DEPENDENCY_MODULE_MISSING", f"Dependency rule {dependency['id']} references an unknown module", path=f"$.policies.dependencies[{index}]"))

    return diagnostics


def load_architecture(path: str | Path, schema_path: str | Path | None = None) -> ArchitectureDocument:
    arch_path = Path(path).expanduser().resolve()
    schema = Path(schema_path).expanduser().resolve() if schema_path else default_schema_path().resolve()
    try:
        text = arch_path.read_text(encoding="utf-8")
        model = yaml.load(text, Loader=RestrictedLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ArchitectureError([_diagnostic("ARCH_PARSE_ERROR", str(exc))]) from exc

    diagnostics = _schema_diagnostics(model, schema)
    if isinstance(model, dict) and not diagnostics:
        diagnostics.extend(_semantic_diagnostics(model))
    if diagnostics:
        raise ArchitectureError(diagnostics)

    canonical = json.dumps(model, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ArchitectureDocument(path=arch_path, model=model, digest=digest, diagnostics=tuple())
