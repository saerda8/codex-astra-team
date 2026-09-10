#!/usr/bin/env python3
"""Turn-scoped Astra delegation guard for Codex hooks."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ASTRA_MODEL = "gpt-6-astra"
FORCED_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
LONG_TASK_MIN_CHARS = 80
ROLE_RUNTIME = {
    "sol_high": ("gpt-5.6-sol", "high"),
    "sol_xhigh": ("gpt-5.6-sol", "xhigh"),
    "terra_max": ("gpt-5.6-terra", "max"),
    "luna_max": ("gpt-5.6-luna", "max"),
    "luna_explorer_max": ("gpt-5.6-luna", "max"),
}
DELEGATE_ROLES = set(ROLE_RUNTIME)
ROLE_DISPLAY = {
    "sol_high": "Sol High",
    "sol_xhigh": "Sol XHigh",
    "terra_max": "Terra Max",
    "luna_max": "Luna Max",
    "luna_explorer_max": "Luna Explorer Max",
}
EFFORT_DISPLAY = {
    "low": "Low", "medium": "Medium", "high": "High", "xhigh": "XHigh",
    "max": "Max", "ultra": "Ultra",
}
SPAWN_NAMES = {"spawn_agent", "Agent", "collaborationspawn_agent"}
COORDINATION_SUFFIXES = (
    "list_agents", "wait_agent", "followup_task", "send_message",
    "interrupt_agent",
)
ACTION_REQUEST = re.compile(
    r"^\s*(继续|开始执行|执行)\s*[。！!]*$|"
    r"(?:请|帮我|给我|你|现在|赶紧|麻烦|我希望).{0,24}"
    r"(?:修复|修改|改|实现|开发|重构|调试|排查|检查|测试|构建|部署|安装|升级|优化|"
    r"删除|创建|生成|写|核对)|"
    r"(?:修复|修改|改|实现|开发|重构|调试|排查|测试|构建|部署|安装|升级|优化|删除|创建|生成|写)"
    r"(?:一下|下|吧|呀|掉|好|完成|起来|出来|这个|该|项目|功能|代码|脚本|钩子)",
    re.IGNORECASE,
)
ISSUE_ALIGNMENT = re.compile(
    r"你.{0,12}(?:问题|现象|情况)|你.{0,12}遇到的是|"
    r"(?:问题|现象|卡点|症结|风险).{0,12}(?:是|在于|表现|集中)|"
    r"(?:要解决|需要解决)的是|失败|报错|误拦|卡住"
)
PRIORITY_ALIGNMENT = re.compile(
    r"优先|最重要|首要|先(?:把|解决|处理|确认)|"
    r"当前(?:先|重点|任务)|这次(?:先|重点)"
)
PLAN_ALIGNMENT = re.compile(
    r"我(?:会|先|准备|负责|打算)|接下来|下一步|"
    r"当下(?:要|先)|现在(?:先|就)|执行方案|"
    r"修正|修复|排查|验证|测试|检查|处理|调整|去掉|保留"
)
ROLE_ALIGNMENT = re.compile(
    r"sol_high|sol_xhigh|terra_max|luna_max|luna_explorer_max|"
    r"Sol|Terra|Luna",
    re.IGNORECASE,
)


def state_dir() -> Path:
    configured = os.environ.get("ASTRA_TURN_GUARD_STATE_DIR")
    path = Path(configured) if configured else Path.home() / ".codex" / "astra-turn-guard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(state_dir() / "state.sqlite3", timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS turns (
            session_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            model TEXT NOT NULL,
            effort TEXT,
            status TEXT NOT NULL,
            agent_id TEXT,
            agent_type TEXT,
            stop_retries INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (session_id, turn_id)
        )
    """)
    reconcile_recorded_children(db)
    return db


def reconcile_recorded_children(db: sqlite3.Connection) -> None:
    """Link SubagentStart rows written with a child turn id to their parent turn."""
    children = db.execute(
        "SELECT rowid, session_id, agent_id, agent_type, updated_at FROM turns "
        "WHERE status='delegated' AND model<>? AND agent_id IS NOT NULL",
        (ASTRA_MODEL,),
    ).fetchall()
    for child_rowid, session_id, agent_id, agent_type, child_time in children:
        parent = db.execute(
            "SELECT rowid, turn_id FROM turns WHERE session_id=? AND model=? "
            "AND status IN ('pending', 'watching') AND rowid<? AND ABS(updated_at-?)<=3600 "
            "ORDER BY rowid DESC LIMIT 1",
            (session_id, ASTRA_MODEL, child_rowid, child_time),
        ).fetchone()
        if parent is None:
            continue
        db.execute(
            "UPDATE turns SET status='delegated', agent_id=?, agent_type=?, updated_at=? "
            "WHERE rowid=?",
            (agent_id, agent_type, time.time(), parent[0]),
        )
        db.execute("UPDATE turns SET status='linked' WHERE rowid=?", (child_rowid,))
    db.commit()


def transcript_records(path_value: Any) -> list[dict[str, Any]]:
    if not isinstance(path_value, str) or not path_value:
        return []
    path = Path(path_value)
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - 4 * 1024 * 1024))
        data = handle.read().decode("utf-8", errors="ignore")
    records = []
    for line in data.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def transcript_effort(path_value: Any, turn_id: str) -> str | None:
    records = transcript_records(path_value)
    for record in reversed(records):
        payload = record.get("payload", {})
        if record.get("type") == "turn_context" and payload.get("turn_id") == turn_id:
            effort = payload.get("effort") or payload.get("reasoning_effort")
            return effort if isinstance(effort, str) else None
    return None


def normalize_tool_name(value: Any) -> str:
    return "".join(char for char in str(value).lower() if char.isalnum() or char == "_")


def transcript_has_visible_preamble(payload: dict[str, Any]) -> bool:
    turn_id = str(payload.get("turn_id", ""))
    for record in transcript_records(payload.get("transcript_path")):
        item = record.get("payload", {})
        if record.get("type") != "response_item" or not isinstance(item, dict):
            continue
        metadata = item.get("internal_chat_message_metadata_passthrough", {})
        if not isinstance(metadata, dict) or metadata.get("turn_id") != turn_id:
            continue
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        if item.get("phase") != "commentary":
            continue
        content = item.get("content", [])
        text = "".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
        issue = ISSUE_ALIGNMENT.search(text)
        plan = PLAN_ALIGNMENT.search(text)
        if (
            len(text.strip()) >= 48
            and issue
            and plan
            and ROLE_ALIGNMENT.search(text)
            and issue.start() < plan.start()
        ):
            return True
    return False


def transcript_spawn_success(payload: dict[str, Any]) -> tuple[str, str] | None:
    turn_id = str(payload.get("turn_id", ""))
    calls: dict[str, str] = {}
    for record in transcript_records(payload.get("transcript_path")):
        item = record.get("payload", {})
        if record.get("type") != "response_item" or not isinstance(item, dict):
            continue
        metadata = item.get("internal_chat_message_metadata_passthrough", {})
        if isinstance(metadata, dict) and metadata.get("turn_id") != turn_id:
            continue
        if item.get("type") == "function_call":
            name = normalize_tool_name(f"{item.get('namespace', '')}{item.get('name', '')}")
            if not name.endswith("spawn_agent"):
                continue
            arguments = item.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            role = arguments.get("agent_type") if isinstance(arguments, dict) else None
            if role in DELEGATE_ROLES and isinstance(item.get("call_id"), str):
                calls[item["call_id"]] = role
        elif item.get("type") == "function_call_output" and item.get("call_id") in calls:
            output = item.get("output", {})
            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except json.JSONDecodeError:
                    continue
            task_name = output.get("task_name") if isinstance(output, dict) else None
            if isinstance(task_name, str) and task_name.startswith("/root/"):
                return task_name, calls[item["call_id"]]
    return None


def transcript_followup_success(
    db: sqlite3.Connection, payload: dict[str, Any]
) -> tuple[str, str] | None:
    turn_id = str(payload.get("turn_id", ""))
    calls = set()
    records = transcript_records(payload.get("transcript_path"))
    for record in records:
        item = record.get("payload", {})
        if record.get("type") != "response_item" or not isinstance(item, dict):
            continue
        metadata = item.get("internal_chat_message_metadata_passthrough", {})
        if isinstance(metadata, dict) and metadata.get("turn_id") != turn_id:
            continue
        name = normalize_tool_name(f"{item.get('namespace', '')}{item.get('name', '')}")
        if item.get("type") == "function_call" and name.endswith("followup_task"):
            if isinstance(item.get("call_id"), str):
                calls.add(item["call_id"])
    for record in records:
        item = record.get("payload", {})
        if record.get("type") != "event_msg" or not isinstance(item, dict):
            continue
        if item.get("type") != "sub_agent_activity" or item.get("event_id") not in calls:
            continue
        if item.get("kind") not in {"interacted", "started"}:
            continue
        agent_id = item.get("agent_thread_id")
        row = db.execute(
            "SELECT agent_type FROM turns WHERE agent_id=? AND agent_type IS NOT NULL "
            "ORDER BY rowid DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        if row and row[0] in DELEGATE_ROLES:
            return str(agent_id), str(row[0])
    return None


def record_transcript_delegation(db: sqlite3.Connection, payload: dict[str, Any]) -> bool:
    evidence = transcript_spawn_success(payload) or transcript_followup_success(db, payload)
    if evidence is None:
        return False
    task_name, role = evidence
    session_id = str(payload.get("session_id", ""))
    turn_id = str(payload.get("turn_id", ""))
    db.execute(
        "UPDATE turns SET status='delegated', agent_id=?, agent_type=?, updated_at=? "
        "WHERE session_id=? AND turn_id=?",
        (task_name, role, time.time(), session_id, turn_id),
    )
    db.commit()
    return True


def get_turn(db: sqlite3.Connection, session_id: str, turn_id: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT model, effort, status, agent_id, agent_type, stop_retries "
        "FROM turns WHERE session_id=? AND turn_id=?",
        (session_id, turn_id),
    ).fetchone()
    if row is None:
        return None
    keys = ("model", "effort", "status", "agent_id", "agent_type", "stop_retries")
    return dict(zip(keys, row))


def requires_collaboration(prompt: Any) -> bool:
    return isinstance(prompt, str) and ACTION_REQUEST.search(prompt) is not None


def is_long_task(prompt: Any) -> bool:
    return isinstance(prompt, str) and len(prompt.strip()) >= LONG_TASK_MIN_CHARS


def upsert_pending(
    db: sqlite3.Connection, payload: dict[str, Any], status: str = "pending"
) -> None:
    session_id = str(payload.get("session_id", ""))
    turn_id = str(payload.get("turn_id", ""))
    effort = transcript_effort(payload.get("transcript_path"), turn_id)
    db.execute("""
        INSERT INTO turns(session_id, turn_id, model, effort, status, updated_at)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id, turn_id) DO UPDATE SET
            model=excluded.model,
            effort=COALESCE(excluded.effort, turns.effort),
            status=excluded.status,
            agent_id=NULL,
            agent_type=NULL,
            stop_retries=0,
            updated_at=excluded.updated_at
    """, (
        session_id, turn_id, str(payload.get("model", "")), effort, status, time.time(),
    ))
    db.commit()


def resolve_turn(db: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("session_id", ""))
    turn_id = str(payload.get("turn_id", ""))
    turn = get_turn(db, session_id, turn_id)
    if turn is None:
        upsert_pending(db, payload)
        turn = get_turn(db, session_id, turn_id)
    assert turn is not None
    if not turn.get("effort"):
        effort = transcript_effort(payload.get("transcript_path"), turn_id)
        if effort:
            db.execute(
                "UPDATE turns SET effort=?, updated_at=? WHERE session_id=? AND turn_id=?",
                (effort, time.time(), session_id, turn_id),
            )
            db.commit()
            turn["effort"] = effort
    return turn


def handle_prompt(payload: dict[str, Any], db: sqlite3.Connection) -> dict[str, Any]:
    if payload.get("agent_type") or payload.get("model") != ASTRA_MODEL:
        return {}
    prompt = payload.get("prompt")
    action = requires_collaboration(prompt)
    effort = transcript_effort(payload.get("transcript_path"), str(payload.get("turn_id", "")))
    if not effort:
        effort = payload.get("effort") or payload.get("reasoning_effort")
    eligible = effort is None or (isinstance(effort, str) and effort.lower() in FORCED_EFFORTS)
    status = ("pending" if is_long_task(prompt) else "watching") if eligible and action else "exempt"
    upsert_pending(db, payload, status)
    if action and eligible:
        role_values = "；".join(ROLE_DISPLAY.values())
        if isinstance(effort, str) and effort:
            runtime_message = (
                f"当前回合真实运行值：Astra {EFFORT_DISPLAY.get(effort.lower(), effort)}。"
                "此值仅供路由判断，不要求在回复中展示。"
            )
        else:
            runtime_message = (
                "当前回合未取得可验证的真实档位，"
                "用户可见回复省略整段模型与档位信息，不得自行猜测。"
            )
        return {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                runtime_message
                + "不得使用全局默认值、角色名或历史文字推测。"
                + f"子角色用户可见名称与档位：{role_values}。"
                "实际派工时用一句话告知交给谁、做什么；只陈述真实派工。"
                "其余输出保持 Codex 默认表达，不规定开头、过程、结论的格式或示例，不要求重复分工。"
            ),
        }}
    return {}


def sustained_work(db: sqlite3.Connection, payload: dict[str, Any]) -> bool:
    """Count distinct local tool calls, not prompt length or duplicate events."""
    db.execute("CREATE TABLE IF NOT EXISTS work_calls (session_id TEXT, turn_id TEXT, call_id TEXT, PRIMARY KEY(session_id, turn_id, call_id))")
    call_id = payload.get("tool_use_id")
    if not call_id:
        return False
    key = (str(payload.get("session_id", "")), str(payload.get("turn_id", "")))
    db.execute("INSERT OR IGNORE INTO work_calls VALUES (?, ?, ?)", (*key, str(call_id)))
    db.commit()
    return db.execute("SELECT COUNT(*) FROM work_calls WHERE session_id=? AND turn_id=?", key).fetchone()[0] >= 6


def handle_pre_tool(payload: dict[str, Any], db: sqlite3.Connection) -> dict[str, Any]:
    if payload.get("agent_type") or payload.get("model") != ASTRA_MODEL:
        return {}
    turn = resolve_turn(db, payload)
    if turn.get("status") != "delegated" and record_transcript_delegation(db, payload):
        turn = resolve_turn(db, payload)
    if turn.get("status") not in {"pending", "watching"}:
        return {}
    normalized_tool = normalize_tool_name(payload.get("tool_name", ""))
    if normalized_tool.endswith("spawn_agent") or any(
        normalized_tool.endswith(name) for name in COORDINATION_SUFFIXES
    ):
        return {}
    if int(turn.get("stop_retries", 0)) == 0:
        if turn["status"] == "watching" and not sustained_work(db, payload):
            return {}
        session_id = str(payload.get("session_id", ""))
        turn_id = str(payload.get("turn_id", ""))
        db.execute(
            "UPDATE turns SET stop_retries=1, updated_at=? WHERE session_id=? AND turn_id=?",
            (time.time(), session_id, turn_id),
        )
        db.commit()
        if transcript_has_visible_preamble(payload):
            message = "这是较长任务，问题和计划已说明；建议再安排合适角色协作。"
        else:
            message = "这是较长任务，可按任务需要安排合适角色协作。"
        return {"systemMessage": message + "小任务直接完成，不为流程创建助手。大任务优先让一个匹配角色完成实现和相关测试；复用已有助手，独立新任务仅传精简交接。主会话不重复调查，只做必要审查与一次验收；等待完成通知，不反复轮询。角色按任务选择 Luna Max、Terra Max 或 Sol High。这只是提醒，当前工具仍会继续执行。"}
    return {}


def handle_subagent_start(payload: dict[str, Any], db: sqlite3.Connection) -> dict[str, Any]:
    role = payload.get("agent_type")
    if role not in DELEGATE_ROLES:
        return {}
    session_id = str(payload.get("session_id", ""))
    event_turn_id = str(payload.get("turn_id", ""))
    parent = db.execute(
        "SELECT turn_id FROM turns WHERE session_id=? AND model=? AND status IN ('pending', 'watching') "
        "AND turn_id=?",
        (session_id, ASTRA_MODEL, event_turn_id),
    ).fetchone()
    if parent is None:
        parent = db.execute(
            "SELECT turn_id FROM turns WHERE session_id=? AND model=? AND status IN ('pending', 'watching') "
            "ORDER BY rowid DESC LIMIT 1",
            (session_id, ASTRA_MODEL),
        ).fetchone()
    if parent is None:
        return {}
    db.execute(
        "UPDATE turns SET status='delegated', agent_id=?, agent_type=?, updated_at=? "
        "WHERE session_id=? AND turn_id=?",
        (str(payload.get("agent_id", "")), str(role), time.time(), session_id, parent[0]),
    )
    db.commit()
    return {}


def handle_stop(payload: dict[str, Any], db: sqlite3.Connection) -> dict[str, Any]:
    if payload.get("agent_type") or payload.get("model") != ASTRA_MODEL:
        return {}
    turn = resolve_turn(db, payload)
    if turn.get("status") != "delegated" and record_transcript_delegation(db, payload):
        resolve_turn(db, payload)
    return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be an object")
        event = payload.get("hook_event_name")
        with connect() as db:
            if event == "UserPromptSubmit":
                output = handle_prompt(payload, db)
            elif event == "PreToolUse":
                output = handle_pre_tool(payload, db)
            elif event == "SubagentStart":
                output = handle_subagent_start(payload, db)
            elif event == "Stop":
                output = handle_stop(payload, db)
            else:
                output = {}
        if output:
            print(json.dumps(output, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"systemMessage": f"Astra 协作闸门运行失败：{exc}"}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
