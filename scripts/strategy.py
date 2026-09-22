#!/usr/bin/env python3
"""Offline staging, static verification, integrity baseline, and safe rollback.
No model calls, package installation, login changes, or live config merging.
Python 3.11+; run from the packaged skill, not from its installed guard copy.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import tomllib
from model_guard import EXPECTED, contained, digest

BUNDLE = Path(__file__).resolve().parents[1]
RELS = [".codex/config.toml", ".codex/hooks.json", ".codex/model-policy.json",
        ".codex/hooks/model_guard.py", "AGENTS.md", "AGENTS.override.md",
        ".gitignore", "docs/CODEX_ASTRA_WORKFLOW.md"] + [
        f".codex/agents/{name}.toml" for name in EXPECTED]


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object: " + str(path))
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def state(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("Refusing a symlink target: " + str(path))
    if not path.exists():
        return {"exists": False}
    if not path.is_file():
        raise ValueError("Target is not a file: " + str(path))
    return {"exists": True, "sha256": digest(path), "mode": stat.S_IMODE(path.stat().st_mode)}


def target(root: Path, relative: str) -> Path:
    raw = root / relative
    current = raw
    while current != root:
        if current.is_symlink():
            raise ValueError("Refusing symlink in deployment path: " + relative)
        current = current.parent
    return contained(root, relative)


def stage(root: Path, out: Path) -> None:
    if out.exists():
        raise ValueError("Staging directory exists; choose a new empty path")
    # Never stage into an auto-loaded configuration or skill directory.
    if out == root or any(out.is_relative_to(root / name) for name in (".codex", ".agents")):
        raise ValueError("Stage outside auto-loaded configuration directories")
    out.mkdir(parents=True)
    for src in (BUNDLE / "assets").rglob("*"):
        if src.is_file():
            dest = out / src.relative_to(BUNDLE / "assets")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
    (out / "model_guard.py").write_bytes((BUNDLE / "scripts/model_guard.py").read_bytes())
    args = [sys.executable, str(root / ".codex/hooks/model_guard.py")]
    command = subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)
    write_json(out / "hooks.fragment.json", {"hooks": {"PreToolUse": [{
        "matcher": "^(spawn_agent|Agent)$", "hooks": [{"type": "command",
        "command": command, "timeout": 10,
        "statusMessage": "Checking model strategy"}]}]}})
    current_adapter = {
        "verified": False, "evidence_ref": "",
        "tool_names": ["spawn_agent"], "role_fields": ["task_name"],
        "model_fields": ["model"], "effort_fields": ["reasoning_effort"],
        "allowed_input_fields": ["task_name", "message", "fork_turns", "model", "reasoning_effort"]}
    legacy_adapter = {
        "verified": False, "evidence_ref": "",
        "tool_names": ["spawn_agent"], "role_fields": ["agent_type"],
        "model_fields": ["model"], "effort_fields": ["reasoning_effort"],
        "allowed_input_fields": ["agent_type", "message", "items", "fork_context", "model", "reasoning_effort"]}
    write_json(out / "adapter.example.json", current_adapter)
    write_json(out / "adapter.current-codex.example.json", current_adapter)
    write_json(out / "adapter.agent-type.example.json", legacy_adapter)
    print(json.dumps({"status": "STAGED_NOT_INSTALLED", "directory": str(out)}, indent=2))


def static_errors(root: Path) -> list[str]:
    errors = []
    try:
        conf = tomllib.loads(target(root, ".codex/config.toml").read_text(encoding="utf-8"))
        checks = [(conf.get("model") in {"gpt-6-astra", "gpt-6-sol"}, "main model"),
                  (conf.get("model_reasoning_effort") in {"medium", "high", "xhigh", "max", "ultra"}, "main effort"),
                  (conf.get("features", {}).get("multi_agent") is True, "multi-agent flag"),
                  (conf.get("features", {}).get("hooks") is True, "hooks flag")]
        agents = conf.get("agents", {})
        checks += [(agents.get("enabled") is True, "agents enabled"),
                   (agents.get("max_concurrent_threads_per_session") == 2, "concurrency"),
                   (agents.get("default_subagent_model") == "gpt-5.6-luna", "default child model"),
                   (agents.get("default_subagent_reasoning_effort") == "max", "default child effort")]
        for passed, label in checks:
            if not passed:
                errors.append("Unexpected " + label)
    except (OSError, ValueError, TypeError) as exc:
        errors.append("Main config unreadable: " + type(exc).__name__)
    for name, (model, effort) in EXPECTED.items():
        try:
            obj = tomllib.loads(target(root, f".codex/agents/{name}.toml").read_text(encoding="utf-8"))
            if (obj.get("name"), obj.get("model"), obj.get("model_reasoning_effort")) != (name, model, effort):
                errors.append("Role mismatch: " + name)
            if not obj.get("description") or not obj.get("developer_instructions"):
                errors.append("Missing role instructions: " + name)
            if obj.get("agents", {}).get("enabled") is not False:
                errors.append("Nested agents not disabled: " + name)
            if name == "luna_explorer_max" and obj.get("sandbox_mode") != "read-only":
                errors.append("Explorer is not configured read-only")
        except (OSError, ValueError, TypeError) as exc:
            errors.append("Unreadable role " + name + ": " + type(exc).__name__)
    try:
        hooks = load(target(root, ".codex/hooks.json"))
        groups = hooks.get("hooks", {}).get("PreToolUse", [])
        if not any(g.get("matcher") == "^(spawn_agent|Agent)$" and
                   any(h.get("type") == "command" and "model_guard.py" in h.get("command", "")
                       for h in g.get("hooks", [])) for g in groups):
            errors.append("Expected hook entry not found")
    except (OSError, ValueError, TypeError) as exc:
        errors.append("Hook config unreadable: " + type(exc).__name__)
    return errors


def seal(root: Path, adapter_path: Path) -> None:
    errors = static_errors(root)
    if errors:
        raise ValueError("Static checks failed: " + "; ".join(errors))
    adapter = load(adapter_path)
    if adapter.get("verified") is not True:
        raise ValueError("Verify actual tool schema before sealing")
    evidence = adapter.get("evidence_ref")
    if not isinstance(evidence, str) or not contained(root, evidence).is_file():
        raise ValueError("A local schema-verification evidence file is required")
    role_fields = adapter.get("role_fields")
    if role_fields is None and isinstance(adapter.get("role_field"), str):
        role_fields = [adapter["role_field"]]
    if (not adapter.get("tool_names") or not isinstance(role_fields, list)
            or not role_fields or len(set(role_fields)) != len(role_fields)):
        raise ValueError("Incomplete tool adapter")
    fields = adapter.get("allowed_input_fields", [])
    required = role_fields + adapter.get("model_fields", []) + adapter.get("effort_fields", [])
    if not all(isinstance(f, str) and f in fields for f in required):
        raise ValueError("Adapter fields must be listed explicitly")
    locked_rels = [".codex/config.toml", ".codex/hooks.json", ".codex/hooks/model_guard.py"]
    locked_rels += [f".codex/agents/{name}.toml" for name in EXPECTED]
    instruction = "AGENTS.override.md" if (root / "AGENTS.override.md").exists() else "AGENTS.md"
    if (root / instruction).is_file():
        locked_rels.append(instruction)
    policy = {"schema_version": 1, "project_root": str(root),
              "roles": {n: {"model": m, "effort": e} for n, (m, e) in EXPECTED.items()},
              "adapter": adapter,
              "locked_files": {p: digest(target(root, p)) for p in locked_rels},
              "audit_path": ".codex-strategy-local/routing-audit.jsonl"}
    write_json(target(root, ".codex/model-policy.json"), policy)
    print("SEALED_STATIC_BASELINE_NOT_RUNTIME_PROOF")


def verify(root: Path) -> bool:
    errors = static_errors(root)
    policy_path = root / ".codex/model-policy.json"
    try:
        policy = load(policy_path)
        if policy.get("project_root") != str(root):
            errors.append("Policy project root mismatch")
        expected_roles = {n: {"model": m, "effort": e} for n, (m, e) in EXPECTED.items()}
        if policy.get("roles") != expected_roles:
            errors.append("Policy role matrix mismatch")
        required_files = {".codex/config.toml", ".codex/hooks.json", ".codex/hooks/model_guard.py"}
        required_files.update(f".codex/agents/{n}.toml" for n in EXPECTED)
        if not required_files.issubset(policy.get("locked_files", {})):
            errors.append("Incomplete configuration integrity baseline")
        if policy.get("adapter", {}).get("verified") is not True:
            errors.append("Tool adapter not verified")
        for p, sha in policy.get("locked_files", {}).items():
            if digest(target(root, p)) != sha:
                errors.append("Integrity mismatch: " + p)
        if not policy.get("locked_files"):
            errors.append("No integrity baseline")
    except (OSError, ValueError, TypeError) as exc:
        errors.append("Policy unreadable: " + type(exc).__name__)
    print(json.dumps({"status": "STATIC_PASS" if not errors else "STATIC_FAIL",
                      "errors": errors, "runtime_verified": False}, indent=2))
    return not errors


def catalog_check(path: Path) -> bool:
    obj = load(path)
    obj = obj.get("result", obj)
    if obj.get("nextCursor"):
        raise ValueError("Model catalog is paginated; collect all pages first")
    models = {}
    for item in obj.get("data", []):
        model = item.get("model")
        if model:
            models[model] = {entry.get("reasoningEffort") for entry in item.get("supportedReasoningEfforts", [])}
    required = set(EXPECTED.values()) | {("gpt-6-astra", "high"), ("gpt-6-sol", "high")}
    missing = [{"model": m, "effort": e} for m, e in sorted(required) if e not in models.get(m, set())]
    print(json.dumps({"status": "CATALOG_PASS" if not missing else "CATALOG_BLOCKED",
                      "missing": missing, "actual_calls_verified": False}, indent=2))
    return not missing


def backup(root: Path, folder: Path) -> None:
    if folder.exists():
        raise ValueError("Backup directory already exists")
    before = {relative: state(target(root, relative)) for relative in RELS}
    folder.mkdir(parents=True)
    for relative, info in before.items():
        if info["exists"]:
            dest = folder / "files" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(target(root, relative).read_bytes())
    write_json(folder / "manifest.json", {"project_root": str(root), "before": before,
               "created": datetime.now(timezone.utc).isoformat(), "after": None})
    print("BACKUP_CREATED " + str(folder))


def finalize(root: Path, folder: Path) -> None:
    manifest = load(folder / "manifest.json")
    if manifest.get("project_root") != str(root):
        raise ValueError("Backup project mismatch")
    if manifest.get("after") is not None:
        raise ValueError("Backup already finalized; do not replace its post-deploy baseline")
    manifest["after"] = {p: state(target(root, p)) for p in manifest["before"]}
    write_json(folder / "manifest.json", manifest)
    print("POST_DEPLOY_BASELINE_RECORDED")


def rollback(root: Path, folder: Path) -> None:
    manifest = load(folder / "manifest.json")
    if manifest.get("project_root") != str(root) or manifest.get("after") is None:
        raise ValueError("A finalized backup for this project is required")
    if set(manifest["before"]) - set(RELS) or set(manifest["after"]) != set(manifest["before"]):
        raise ValueError("Invalid backup target set")
    changed = [p for p in manifest["before"] if manifest["before"][p] != manifest["after"][p]]
    # Validate all targets and backup bytes before modifying anything.
    for relative in changed:
        if state(target(root, relative)) != manifest["after"][relative]:
            raise ValueError("Later edits detected; rollback stopped before writes: " + relative)
        before = manifest["before"][relative]
        if before["exists"]:
            saved = contained(folder, "files/" + relative)
            if not saved.is_file() or digest(saved) != before["sha256"]:
                raise ValueError("Backup integrity failure: " + relative)
    for relative in changed:
        dest = target(root, relative)
        before = manifest["before"][relative]
        if before["exists"]:
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".astra-restore-", dir=dest.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(contained(folder, "files/" + relative).read_bytes())
                os.chmod(tmp, before["mode"])
                os.replace(tmp, dest)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        elif dest.exists():
            dest.unlink()
    print("RESTORED_TRACKED_CHANGES; restart and verify Codex")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("stage", "verify", "seal", "backup", "finalize-backup", "rollback"):
        sub = subs.add_parser(command)
        sub.add_argument("--project", type=Path, required=True)
        if command in ("stage", "backup", "finalize-backup", "rollback"):
            sub.add_argument("--out" if command == "stage" else "--backup", type=Path, required=True)
        if command == "seal":
            sub.add_argument("--adapter", type=Path, required=True)
    sub = subs.add_parser("catalog-check")
    sub.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "catalog-check":
            return 0 if catalog_check(args.catalog.resolve()) else 2
        root = args.project.resolve()
        if not root.is_dir() or root == Path(root.anchor) or root == Path.home().resolve():
            raise ValueError("Use a specific existing project directory, not home or filesystem root")
        if args.command == "stage":
            stage(root, args.out.resolve())
        elif args.command == "verify":
            return 0 if verify(root) else 2
        elif args.command == "seal":
            seal(root, args.adapter.resolve())
        elif args.command == "backup":
            backup(root, args.backup.resolve())
        elif args.command == "finalize-backup":
            finalize(root, args.backup.resolve())
        elif args.command == "rollback":
            rollback(root, args.backup.resolve())
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
