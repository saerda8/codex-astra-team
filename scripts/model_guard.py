#!/usr/bin/env python3
"""Project-local PreToolUse guard. Python 3.11+. Does not grant permissions."""
from __future__ import annotations
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import tomllib

EXPECTED = {
    "astra_xhigh": ("gpt-6-astra", "xhigh"),
    "sol_high": ("gpt-5.6-sol", "high"),
    "sol_xhigh": ("gpt-5.6-sol", "xhigh"),
    "terra_max": ("gpt-5.6-terra", "max"),
    "luna_max": ("gpt-5.6-luna", "max"),
    "luna_explorer_max": ("gpt-5.6-luna", "max"),
}


def contained(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Expected a project-relative path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Path escapes project")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(payload: object, policy: dict, root: Path) -> tuple[bool, str, str | None]:
    """Return policy acceptance, reason, role. Acceptance is NOT permission approval."""
    if not isinstance(payload, dict):
        return False, "Invalid hook input", None
    if payload.get("hook_event_name") != "PreToolUse":
        return False, "Unexpected hook event", None
    adapter = policy.get("adapter", {})
    if adapter.get("verified") is not True:
        return False, "Tool schema adapter has not been locally verified", None
    if payload.get("tool_name") not in adapter.get("tool_names", []):
        return False, "Unverified tool name", None
    args = payload.get("tool_input")
    if not isinstance(args, dict):
        return False, "Tool input must be an object", None
    allowed_keys = set(adapter.get("allowed_input_fields", []))
    if set(args) - allowed_keys:
        return False, "Unknown tool input fields; re-verify the adapter", None
    role_fields = adapter.get("role_fields")
    if role_fields is None:
        legacy_role_field = adapter.get("role_field")
        role_fields = [legacy_role_field] if isinstance(legacy_role_field, str) else []
    if not isinstance(role_fields, list) or not all(isinstance(field, str) for field in role_fields):
        return False, "Invalid role field adapter", None
    role_values = [args.get(field) for field in role_fields if args.get(field) is not None]
    if len(role_values) != 1:
        return False, "Missing or ambiguous strategy role", None
    role = role_values[0]
    if not isinstance(role, str) or role not in EXPECTED:
        return False, "Unregistered or missing strategy role", None
    model, effort = EXPECTED[role]
    if policy.get("roles", {}).get(role) != {"model": model, "effort": effort}:
        return False, "Policy role table does not match the approved strategy", role
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).resolve().is_relative_to(root.resolve()):
        return False, "Hook working directory is outside the project", role
    for field in adapter.get("model_fields", []):
        if field in args and args[field] is not None and args[field] != model:
            return False, "Conflicting explicit model override", role
    for field in adapter.get("effort_fields", []):
        if field in args and args[field] is not None and args[field] != effort:
            return False, "Conflicting explicit reasoning effort override", role
    locked = policy.get("locked_files", {})
    required = {".codex/config.toml", ".codex/hooks.json", ".codex/hooks/model_guard.py"}
    required.update(f".codex/agents/{name}.toml" for name in EXPECTED)
    if not required.issubset(locked):
        return False, "Incomplete configuration integrity baseline", role
    for relative, expected_hash in locked.items():
        path = contained(root, relative)
        if not path.is_file() or digest(path) != expected_hash:
            return False, "Configuration drift: " + relative, role
    agent = tomllib.loads(contained(root, f".codex/agents/{role}.toml").read_text(encoding="utf-8"))
    if (agent.get("name"), agent.get("model"), agent.get("model_reasoning_effort")) != (role, model, effort):
        return False, "Role configuration differs from the approved strategy", role
    if agent.get("agents", {}).get("enabled") is not False:
        return False, "Nested agent spawning must be disabled", role
    return True, "Role and configuration checks passed", role


def append_audit(policy: dict, root: Path, payload: object, ok: bool, reason: str, role: str | None) -> None:
    path = contained(root, policy.get("audit_path", ".codex-strategy-local/routing-audit.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"time": datetime.now(timezone.utc).isoformat(), "policy_pass": ok,
              "role": role, "reason": reason}
    if isinstance(payload, dict):
        for key in ("session_id", "turn_id", "tool_use_id"):
            value = payload.get(key)
            if isinstance(value, str):
                record[key] = value[:160]
    # One compact append per invocation. Never record the task body or credentials.
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=True) + "\n")


def main() -> int:
    ok, reason, role = False, "Guard initialization failed", None
    policy, payload = {}, None
    root = Path(__file__).resolve().parents[2]
    try:
        text = sys.stdin.read(1_048_577)
        if len(text) > 1_048_576:
            raise ValueError("Hook input exceeds size limit")
        payload = json.loads(text)
        policy = json.loads((root / ".codex/model-policy.json").read_text(encoding="utf-8"))
        if Path(policy.get("project_root", "")).resolve() != root:
            raise ValueError("Policy belongs to a different project")
        ok, reason, role = inspect(payload, policy, root)
        append_audit(policy, root, payload, ok, reason, role)
    except Exception as exc:
        ok = False
        reason = "Strategy guard could not verify this call (" + type(exc).__name__ + ")"
    # Audit only. Collaboration policy must never block project tools.
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
