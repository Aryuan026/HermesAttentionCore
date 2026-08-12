from __future__ import annotations

import importlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


_TOKEN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PYTHON_REF = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def adapter_config_path() -> Path:
    configured = os.environ.get("HERMES_ATTENTION_ADAPTERS", "").strip()
    hermes_home = Path(
        os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
    ).expanduser()
    return Path(configured) if configured else hermes_home / "attention" / "adapters.json"


def _normalize_spec(value: Mapping[str, Any]) -> dict[str, str]:
    spec = {
        "name": str(value.get("name") or "").strip(),
        "module": str(value.get("module") or "").strip(),
        "factory": str(value.get("factory") or "build_poll").strip(),
    }
    if not _TOKEN.fullmatch(spec["name"]):
        raise ValueError("adapter name must be a lowercase token")
    if not _PYTHON_REF.fullmatch(spec["module"]):
        raise ValueError("adapter module must be a Python module path")
    if not _PYTHON_REF.fullmatch(spec["factory"]) or "." in spec["factory"]:
        raise ValueError("adapter factory must be a Python identifier")
    return spec


def read_adapter_specs(path: Path | None = None) -> list[dict[str, str]]:
    source = path or adapter_config_path()
    if not source.exists():
        return []
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("attention adapter config must be a JSON array")
    specs = [_normalize_spec(item) for item in value if isinstance(item, Mapping)]
    if len(specs) != len(value):
        raise ValueError("every attention adapter entry must be an object")
    names = [item["name"] for item in specs]
    if len(names) != len(set(names)):
        raise ValueError("attention adapter names must be unique")
    return specs


def write_adapter_specs(
    specs: Sequence[Mapping[str, Any]],
    path: Path | None = None,
) -> None:
    target = path or adapter_config_path()
    normalized = [_normalize_spec(item) for item in specs]
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, prefix=".adapters-", delete=False
    ) as handle:
        json.dump(normalized, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    os.replace(temporary, target)


def register_adapter(
    *,
    name: str,
    module: str,
    factory: str = "build_poll",
    path: Path | None = None,
) -> dict[str, Any]:
    spec = _normalize_spec({"name": name, "module": module, "factory": factory})
    existing = read_adapter_specs(path)
    updated = [item for item in existing if item["name"] != spec["name"]]
    updated.append(spec)
    updated.sort(key=lambda item: item["name"])
    write_adapter_specs(updated, path)
    return {"registered": True, "adapter": spec}


def remove_adapter(name: str, path: Path | None = None) -> dict[str, Any]:
    normalized = str(name or "").strip()
    existing = read_adapter_specs(path)
    updated = [item for item in existing if item["name"] != normalized]
    if len(updated) == len(existing):
        return {"removed": False, "reason": "not_found"}
    write_adapter_specs(updated, path)
    return {"removed": True, "name": normalized}


def load_adapter_polls(
    stores: Any, path: Path | None = None
) -> list[tuple[str, Callable[[], Any]]]:
    """Build isolated polls; import/factory failures stay inside heartbeat results."""
    polls: list[tuple[str, Callable[[], Any]]] = []
    try:
        specs = read_adapter_specs(path)
    except Exception as error:
        def fail_registry(exc: Exception = error) -> Any:
            raise exc

        return [("adapter-registry", fail_registry)]
    for spec in specs:
        def run(current: Mapping[str, str] = spec) -> Any:
            module = importlib.import_module(current["module"])
            factory = getattr(module, current["factory"], None)
            if not callable(factory):
                raise ValueError(
                    f"attention adapter {current['name']} has no callable "
                    f"{current['factory']}"
                )
            poll = factory(stores)
            if not callable(poll):
                raise ValueError(
                    f"attention adapter {current['name']} factory returned no callable"
                )
            return poll()

        polls.append((spec["name"], run))
    return polls
