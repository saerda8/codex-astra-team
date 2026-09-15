#!/usr/bin/env python3
"""Offline synthetic-fixture tests; do not call models or touch user configs."""
import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import strategy
import model_guard

class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.stage = self.base / 'stage'
        with contextlib.redirect_stdout(io.StringIO()):
            strategy.stage(self.root, self.stage)
        (self.root / '.codex/agents').mkdir(parents=True)
        (self.root / '.codex/hooks').mkdir()
        for src in (self.stage/'agents').glob('*.toml'):
            shutil.copy2(src,self.root/'.codex/agents'/src.name)
        shutil.copy2(self.stage/'config.fragment.toml',self.root/'.codex/config.toml')
        shutil.copy2(self.stage/'hooks.fragment.json',self.root/'.codex/hooks.json')
        shutil.copy2(self.stage/'model_guard.py',self.root/'.codex/hooks/model_guard.py')
        (self.root/'AGENTS.md').write_text('Synthetic test rules',encoding='utf-8')
        (self.root/'schema-evidence.txt').write_text('Synthetic fixture, not runtime evidence.',encoding='utf-8')
        self.adapter=json.loads((self.stage/'adapter.current-codex.example.json').read_text())
        self.adapter.update(verified=True,evidence_ref='schema-evidence.txt')
        self.ap=self.base/'adapter.json'
        self.ap.write_text(json.dumps(self.adapter))
        with contextlib.redirect_stdout(io.StringIO()): strategy.seal(self.root,self.ap)
        self.policy=json.loads((self.root/'.codex/model-policy.json').read_text())
        self.payload={'hook_event_name':'PreToolUse','tool_name':'spawn_agent',
                      'cwd':str(self.root),'tool_input':{'task_name':'luna_max','message':'test'}}
    def tearDown(self): self.tmp.cleanup()
    def evaluate(self,payload=None,policy=None):
        return model_guard.inspect(self.payload if payload is None else payload,
                                   self.policy if policy is None else policy,self.root)
    def test_valid(self): self.assertTrue(self.evaluate()[0])
    def test_each_role(self):
        for role in model_guard.EXPECTED:
            self.payload['tool_input']['task_name']=role
            self.assertTrue(self.evaluate()[0],role)
    def test_missing_role(self):
        self.payload['tool_input'].pop('task_name'); self.assertFalse(self.evaluate()[0])
    def test_unknown_role(self):
        self.payload['tool_input']['task_name']='default'; self.assertFalse(self.evaluate()[0])
    def test_downgrade(self):
        self.payload['tool_input']['reasoning_effort']='medium'; self.assertFalse(self.evaluate()[0])
    def test_model_override(self):
        self.payload['tool_input']['model']='gpt-6-astra'; self.assertFalse(self.evaluate()[0])
    def test_matching_override(self):
        self.payload['tool_input'].update(model='gpt-5.6-luna',reasoning_effort='max')
        self.assertTrue(self.evaluate()[0])
    def test_current_codex_task_name_role_field(self):
        policy = copy.deepcopy(self.policy)
        policy['adapter'].pop('role_field', None)
        policy['adapter']['role_fields'] = ['task_name']
        policy['adapter']['allowed_input_fields'] = [
            'task_name', 'message', 'fork_turns', 'model', 'reasoning_effort'
        ]
        payload = copy.deepcopy(self.payload)
        payload['tool_input'] = {
            'task_name': 'luna_max',
            'message': 'test',
            'fork_turns': 'all',
            'model': 'gpt-5.6-luna',
            'reasoning_effort': 'max',
        }
        self.assertTrue(self.evaluate(payload, policy)[0])
    def test_legacy_agent_type_role_field(self):
        policy = copy.deepcopy(self.policy)
        policy['adapter']['role_fields'] = ['agent_type']
        policy['adapter']['allowed_input_fields'] = [
            'agent_type', 'message', 'items', 'fork_context', 'model', 'reasoning_effort'
        ]
        payload = copy.deepcopy(self.payload)
        payload['tool_input'] = {'agent_type': 'luna_max', 'message': 'test'}
        self.assertTrue(self.evaluate(payload, policy)[0])
    def test_ambiguous_role_fields_are_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy['adapter']['role_fields'] = ['task_name', 'agent_type']
        policy['adapter']['allowed_input_fields'].append('agent_type')
        payload = copy.deepcopy(self.payload)
        payload['tool_input']['agent_type'] = 'luna_max'
        self.assertFalse(self.evaluate(payload, policy)[0])
    def test_stage_writes_current_and_legacy_adapter_examples(self):
        current = json.loads((self.stage/'adapter.current-codex.example.json').read_text())
        legacy = json.loads((self.stage/'adapter.agent-type.example.json').read_text())
        self.assertEqual(current['role_fields'], ['task_name'])
        self.assertEqual(legacy['role_fields'], ['agent_type'])
        self.assertFalse(current['verified'])
        self.assertFalse(legacy['verified'])
    def test_global_deployment_assets_are_present(self):
        bundle = Path(__file__).resolve().parents[1]
        global_fragment = (bundle/'assets/config.global.fragment.toml').read_text(encoding='utf-8')
        global_guide = (bundle/'references/GLOBAL_DEPLOYMENT.md').read_text(encoding='utf-8')
        hook_fragment = json.loads((bundle/'assets/hooks.global.fragment.json').read_text(encoding='utf-8'))
        self.assertIn('[agents.astra_xhigh]', global_fragment)
        self.assertIn('config_file = "./agents/astra_xhigh.toml"', global_fragment)
        self.assertIn('必须使用已验证的 `agent_type`', global_guide)
        for event in ('UserPromptSubmit', 'PreToolUse', 'SubagentStart', 'Stop'):
            self.assertIn(event, hook_fragment['hooks'])

    def test_strategy_hooks_never_contain_hard_block_outputs(self):
        bundle = Path(__file__).resolve().parents[1]
        for relative in ('scripts/astra_turn_guard.py', 'scripts/model_guard.py'):
            source = (bundle / relative).read_text(encoding='utf-8')
            self.assertNotIn('"permissionDecision": "deny"', source, relative)
            self.assertNotIn('"decision": "block"', source, relative)
    def test_astra_medium_or_higher_routes_execution_work(self):
        bundle = Path(__file__).resolve().parents[1]
        rules = (bundle/'assets/PROJECT_RULES.md').read_text(encoding='utf-8')
        guide = (bundle/'references/GLOBAL_DEPLOYMENT.md').read_text(encoding='utf-8')
        trigger = 'medium、high、xhigh、max 或 ultra'
        self.assertIn(trigger, rules)
        self.assertIn('Astra Medium 及以上的明确执行型任务必须先真正派工', rules)
        self.assertIn(trigger, guide)
        self.assertNotIn('极小任务可由主会话直接完成', rules)
        self.assertNotIn('Astra low 或非 Astra 主会话不强制触发', rules)

    def test_medium_execution_has_no_small_or_core_task_exemption(self):
        bundle = Path(__file__).resolve().parents[1]
        for relative in ('SKILL.md', 'assets/PROJECT_RULES.md', 'references/GLOBAL_DEPLOYMENT.md'):
            rules = (bundle / relative).read_text(encoding='utf-8')
            self.assertIn('Astra Medium 及以上的明确执行任务不论大小都要真实派工', rules)
            self.assertNotIn('小任务可直接做', rules)
            self.assertNotIn('纯核心执行型任务按风险决定是否需要独立只读复核', rules)

    def test_non_astra_never_claims_astra_route(self):
        bundle = Path(__file__).resolve().parents[1]
        documents = '\n'.join((bundle / relative).read_text(encoding='utf-8') for relative in (
            'SKILL.md',
            'assets/PROJECT_RULES.md',
            'references/GLOBAL_DEPLOYMENT.md',
            'references/DEPLOYMENT.md',
        ))
        self.assertIn(
            '未明确确认主会话是 `gpt-6-astra` 且档位符合条件时，禁止输出 `本次路由：Astra`，禁止按 Astra 规则强制派工',
            documents,
        )

    def test_output_style_is_not_prescribed(self):
        bundle = Path(__file__).resolve().parents[1]
        for relative in ('SKILL.md', 'assets/PROJECT_RULES.md', 'references/GLOBAL_DEPLOYMENT.md', 'references/DEPLOYMENT.md'):
            document = (bundle / relative).read_text(encoding='utf-8')
            self.assertIn('实际派工时只额外用一句话说明交给谁、做什么', document)
            self.assertNotIn('每条实质进度末尾和最终回复末尾', document)
            self.assertNotIn('开工时显示主会话', document)
            self.assertNotIn('先提炼用户描述的实际问题', document)
    def test_plain_conversation_does_not_trigger_collaboration(self):
        bundle = Path(__file__).resolve().parents[1]
        documents = '\n'.join((bundle / relative).read_text(encoding='utf-8') for relative in (
            'SKILL.md',
            'assets/PROJECT_RULES.md',
            'references/GLOBAL_DEPLOYMENT.md',
            'references/DEPLOYMENT.md',
        ))
        for phrase in (
            '普通解释、追问、确认或状态问题',
            '明确的修复、修改、实现、排查或测试请求',
            '直接回答，不触发协作',
            '明确的修复、修改、实现、排查或测试请求才进入协作流程',
            '不进入协作、不派助手、不恢复旧任务',
            '`UserPromptSubmit` 默认静默',
            '`additionalContext` 不得注入命令',
            '检查脚本不得输出硬拦截',
        ):
            self.assertIn(phrase, documents)

    def test_mcp_required_when_healthy_and_appropriate_but_non_blocking_on_failure(self):
        bundle = Path(__file__).resolve().parents[1]
        documents = '\n'.join((bundle / relative).read_text(encoding='utf-8') for relative in (
            'SKILL.md',
            'assets/PROJECT_RULES.md',
            'references/GLOBAL_DEPLOYMENT.md',
            'references/DEPLOYMENT.md',
        ))
        for phrase in (
            'MCP 是条件性能力',
            '已加载、健康且适合当前子任务的 MCP 必须调用',
            '没有、不可用、失败或不适合时不阻断',
            '当前模型角色继续完成',
            '不得新增强制 MCP 门禁',
        ):
            self.assertIn(phrase, documents)
    def test_unknown_field(self):
        self.payload['tool_input']['config']={'model':'other'}; self.assertFalse(self.evaluate()[0])
    def test_unverified_adapter(self):
        self.policy['adapter']['verified']=False; self.assertFalse(self.evaluate()[0])
    def test_wrong_event(self):
        self.payload['hook_event_name']='Stop'; self.assertFalse(self.evaluate()[0])
    def test_wrong_tool(self):
        self.payload['tool_name']='other'; self.assertFalse(self.evaluate()[0])
    def test_other_project(self):
        self.payload['cwd']=str(self.base); self.assertFalse(self.evaluate()[0])
    def test_config_drift(self):
        with (self.root/'.codex/agents/luna_max.toml').open('a') as f: f.write('\n# later edit\n')
        self.assertFalse(self.evaluate()[0])
    def test_missing_integrity(self):
        self.policy['locked_files'].pop('.codex/config.toml'); self.assertFalse(self.evaluate()[0])
    def test_corrupt_input_is_audited_without_blocking_cli(self):
        p=subprocess.run([sys.executable,str(self.root/'.codex/hooks/model_guard.py')],input='bad JSON',text=True,capture_output=True)
        self.assertEqual(json.loads(p.stdout), {})
    def test_success_does_not_grant_permission(self):
        p=subprocess.run([sys.executable,str(self.root/'.codex/hooks/model_guard.py')],input=json.dumps(self.payload),text=True,capture_output=True)
        self.assertEqual(json.loads(p.stdout),{})
        audit=(self.root/'.codex-strategy-local/routing-audit.jsonl').read_text()
        self.assertNotIn('message',audit)
    def test_verify_is_static_only(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output): self.assertTrue(strategy.verify(self.root))
        self.assertFalse(json.loads(output.getvalue())['runtime_verified'])
    def test_unverified_adapter_cannot_seal(self):
        self.adapter['verified']=False; self.ap.write_text(json.dumps(self.adapter))
        with self.assertRaises(ValueError): strategy.seal(self.root,self.ap)
    def test_stage_refuses_overwrite(self):
        with self.assertRaises(ValueError): strategy.stage(self.root,self.stage)
    def test_stage_refuses_live_config_directory(self):
        with self.assertRaises(ValueError): strategy.stage(self.root,self.root/'.codex/stage')
    def test_catalog_requires_max(self):
        p=self.base/'catalog.json'
        p.write_text(json.dumps({'data':[{'model':'gpt-5.6-luna','supportedReasoningEfforts':[{'reasoningEffort':'xhigh'}]}],'nextCursor':None}))
        with contextlib.redirect_stdout(io.StringIO()): self.assertFalse(strategy.catalog_check(p))
    def test_catalog_all_combinations(self):
        p=self.base/'catalog.json'
        models={}
        for m,e in set(model_guard.EXPECTED.values())|{('gpt-6-astra','high')}:
            models.setdefault(m,[]).append({'reasoningEffort':e})
        p.write_text(json.dumps({'result':{'data':[{'model':m,'supportedReasoningEfforts':es} for m,es in models.items()],'nextCursor':None}}))
        with contextlib.redirect_stdout(io.StringIO()): self.assertTrue(strategy.catalog_check(p))
    def test_catalog_requires_all_pages(self):
        p=self.base/'catalog.json'; p.write_text('{"data":[],"nextCursor":"next"}')
        with self.assertRaises(ValueError): strategy.catalog_check(p)
    def test_safe_backup_rollback(self):
        folder=self.base/'backup'
        original=(self.root/'AGENTS.md').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            strategy.backup(self.root,folder)
            (self.root/'AGENTS.md').write_text('New rules')
            (self.root/'.gitignore').write_text('/.codex-strategy-local/\n')
            strategy.finalize(self.root,folder)
            strategy.rollback(self.root,folder)
        self.assertEqual((self.root/'AGENTS.md').read_bytes(),original)
        self.assertFalse((self.root/'.gitignore').exists())
    def test_rollback_refuses_later_edit_without_partial_writes(self):
        folder=self.base/'backup'
        with contextlib.redirect_stdout(io.StringIO()):
            strategy.backup(self.root,folder)
            (self.root/'AGENTS.md').write_text('Deployed')
            (self.root/'.gitignore').write_text('Deployed ignore')
            strategy.finalize(self.root,folder)
        (self.root/'.gitignore').write_text('User later edit')
        with self.assertRaises(ValueError): strategy.rollback(self.root,folder)
        self.assertEqual((self.root/'AGENTS.md').read_text(),'Deployed')
    def test_seal_refuses_missing_schema_evidence(self):
        self.adapter['evidence_ref']='missing.txt'; self.ap.write_text(json.dumps(self.adapter))
        with self.assertRaises(ValueError): strategy.seal(self.root,self.ap)
    def test_traversal(self):
        with self.assertRaises(ValueError): model_guard.contained(self.root,'../escape')
    def test_finalize_cannot_replace_baseline(self):
        folder=self.base/'backup'
        with contextlib.redirect_stdout(io.StringIO()):
            strategy.backup(self.root,folder); strategy.finalize(self.root,folder)
        with self.assertRaises(ValueError): strategy.finalize(self.root,folder)


class AstraTurnGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.state = self.base / 'state'
        self.transcript = self.base / 'rollout.jsonl'
        self.script = Path(__file__).with_name('astra_turn_guard.py')
        self.session = 'session-test'
        self.turn = 'turn-test'

    def tearDown(self):
        self.temp.cleanup()

    def write_turn(self, model='gpt-6-astra', effort='medium'):
        record = {'type': 'turn_context', 'payload': {
            'turn_id': self.turn, 'model': model, 'effort': effort,
        }}
        self.transcript.write_text(json.dumps(record) + '\n', encoding='utf-8')

    def append_record(self, record):
        with self.transcript.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record) + '\n')

    def append_commentary(self, text):
        self.append_record({'type': 'response_item', 'payload': {
            'type': 'message', 'role': 'assistant', 'phase': 'commentary',
            'content': [{'type': 'output_text', 'text': text}],
            'internal_chat_message_metadata_passthrough': {'turn_id': self.turn},
        }})

    def append_preamble(self):
        self.append_commentary(
            '你遇到的问题是：协作闸门已经触发，但主会话还没有真正派出助手，'
            '这会让后续本地操作被误拦。当前先解决真实派工识别，优先保证不破坏'
            '未派工时的保护。我会让 luna_max 核对回归场景，自己负责修改共享判断'
            '并跑完相关测试，确认后再收尾。'
        )

    def run_guard(self, event, **extra):
        payload = {
            'session_id': self.session,
            'turn_id': self.turn,
            'transcript_path': str(self.transcript),
            'cwd': str(self.base),
            'hook_event_name': event,
            'model': 'gpt-6-astra',
            'permission_mode': 'default',
        }
        payload.update(extra)
        env = os.environ.copy()
        env['ASTRA_TURN_GUARD_STATE_DIR'] = str(self.state)
        completed = subprocess.run(
            [sys.executable, str(self.script)], input=json.dumps(payload),
            text=True, capture_output=True, env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout) if completed.stdout.strip() else {}

    def register_turn(self, effort='medium', preamble=True):
        self.write_turn(effort=effort)
        output = self.run_guard('UserPromptSubmit', prompt='继续')
        if preamble:
            self.append_preamble()
        return output

    def test_prompt_registers_action_turn_with_actual_runtime_context(self):
        output = self.register_turn()
        self.assertIn('Astra Medium', output['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('permissionDecision', output['hookSpecificOutput'])

    def test_plain_question_is_silent_and_exempt(self):
        self.write_turn()
        output = self.run_guard(
            'UserPromptSubmit',
            prompt='环境存在异常就拿不到岗位详情吗？这两者有因果关系吗？',
        )
        self.assertEqual(output, {})
        self.assertEqual(
            self.run_guard('Stop', stop_hook_active=False, last_assistant_message='直接回答'),
            {},
        )

    def test_action_prompt_provides_context_and_remains_non_blocking(self):
        self.write_turn()
        output = self.run_guard('UserPromptSubmit', prompt='请修复这个协作钩子并补测试')
        self.assertIn('Astra Medium', output['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('permissionDecision', output['hookSpecificOutput'])
        output = self.run_guard(
            'PreToolUse', tool_name='apply_patch',
            tool_input={'command': 'patch'}, tool_use_id='tool-1',
        )
        self.assertEqual(output, {})

    def test_advisory_policy_never_blocks_project_work_or_stop(self):
        self.write_turn()
        prompt_output = self.run_guard('UserPromptSubmit', prompt='请修复这个项目并运行测试')
        self.assertIn('Astra Medium', prompt_output['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('permissionDecision', prompt_output['hookSpecificOutput'])
        self.assertEqual(
            self.run_guard(
                'PreToolUse', tool_name='apply_patch',
                tool_input={'patch': 'test'}, tool_use_id='tool-advisory',
            ),
            {},
        )
        self.assertEqual(
            self.run_guard('Stop', stop_hook_active=False, last_assistant_message='done'),
            {},
        )

    def test_continue_reminds_after_sustained_work_only_once(self):
        self.write_turn()
        self.run_guard("UserPromptSubmit", prompt="继续")
        for index in range(1, 6):
            self.assertEqual(self.run_guard("PreToolUse", tool_name="exec_command", tool_input={}, tool_use_id=str(index)), {})
        reminder = self.run_guard("PreToolUse", tool_name="exec_command", tool_input={}, tool_use_id="6")
        self.assertIn("systemMessage", reminder)
        self.assertNotIn("permissionDecision", reminder.get("hookSpecificOutput", {}))
        self.assertEqual(self.run_guard("PreToolUse", tool_name="exec_command", tool_input={}, tool_use_id="7"), {})
        self.assertEqual(self.run_guard("Stop", stop_hook_active=False, last_assistant_message="done"), {})

    def test_short_prompt_real_delegation_suppresses_reminder(self):
        import sqlite3
        self.register_turn()
        self.run_guard("SubagentStart", agent_id="real-child", agent_type="luna_max")
        with contextlib.closing(sqlite3.connect(self.state / "state.sqlite3")) as db:
            state = db.execute("SELECT status, agent_id FROM turns WHERE session_id=? AND turn_id=?", (self.session, self.turn)).fetchone()
        self.assertEqual(state, ("delegated", "real-child"))
        for index in range(8):
            self.assertEqual(self.run_guard("PreToolUse", tool_name="exec_command", tool_input={}, tool_use_id=str(index)), {})

    def test_duplicate_events_and_other_turns_do_not_inflate_work(self):
        self.write_turn()
        self.run_guard("UserPromptSubmit", prompt="继续")
        for _ in range(8):
            self.assertEqual(self.run_guard("PreToolUse", tool_name="exec_command", tool_input={}, tool_use_id="same"), {})
        self.turn = "fresh-turn"
        self.run_guard("UserPromptSubmit", prompt="继续")
        for index in range(5):
            self.assertEqual(self.run_guard("PreToolUse", tool_name="exec_command", tool_input={}, tool_use_id=str(index)), {})

    def test_short_task_has_no_advisory_reminder(self):
        self.write_turn()
        prompt_output = self.run_guard('UserPromptSubmit', prompt='改一下')
        self.assertIn('Astra Medium', prompt_output['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('systemMessage', prompt_output)
        self.assertEqual(
            self.run_guard(
                'PreToolUse', tool_name='exec_command',
                tool_input={'cmd': 'read only'}, tool_use_id='tool-short',
            ),
            {},
        )

    def test_long_task_gets_one_non_blocking_reminder(self):
        self.write_turn()
        prompt = (
            '请排查这个较长的协作任务，核对当前回合、消息记录、角色派发和失败收尾，'
            '修复误判并补充回归测试，同时保持现有业务代码、权限和安全规则完全不变，'
            '最后给出可以复核的结果。'
        )
        self.assertGreaterEqual(len(prompt), 80)
        prompt_output = self.run_guard('UserPromptSubmit', prompt=prompt)
        self.assertNotIn('permissionDecision', prompt_output['hookSpecificOutput'])
        first = self.run_guard(
            'PreToolUse', tool_name='exec_command',
            tool_input={'cmd': 'read only'}, tool_use_id='tool-long-1',
        )
        self.assertNotIn('permissionDecision', first.get('hookSpecificOutput', {}))
        self.assertIn('systemMessage', first)
        self.assertEqual(
            self.run_guard(
                'PreToolUse', tool_name='exec_command',
                tool_input={'cmd': 'read only'}, tool_use_id='tool-long-2',
            ),
            {},
        )

    def test_long_astra_task_exposes_actual_ultra_to_start_and_finish(self):
        self.write_turn(effort='ultra')
        prompt = (
            '请排查这个较长的协作任务，核对当前回合、消息记录、角色派发和失败收尾，'
            '修复误判并补充回归测试，同时保持现有业务代码、权限和安全规则完全不变，'
            '最后给出可以复核的结果。'
        )
        output = self.run_guard('UserPromptSubmit', prompt=prompt)
        context = output['hookSpecificOutput']['additionalContext']
        self.assertIn('Astra Ultra', context)
        self.assertIn('实际派工时用一句话', context)
        self.assertIn('Sol High', context)
        self.assertIn('Luna Explorer Max', context)
        self.assertNotIn('sol_high', context)
        self.assertNotIn('gpt-5.6-', context)
        self.assertNotIn('permissionDecision', output['hookSpecificOutput'])
        first = self.run_guard(
            'PreToolUse', tool_name='exec_command',
            tool_input={'cmd': 'read only'}, tool_use_id='tool-first',
        )
        self.assertIn('systemMessage', first)
        self.assertNotIn('permissionDecision', first.get('hookSpecificOutput', {}))
        for tool_name, tool_input in (
            ('apply_patch', {'patch': 'test'}),
            ('collaboration.spawn_agent', {'agent_type': 'unknown'}),
            ('collaboration.followup_task', {'target': '/root/existing'}),
        ):
            self.assertEqual(
                self.run_guard(
                    'PreToolUse', tool_name=tool_name,
                    tool_input=tool_input, tool_use_id=f'tool-{tool_name}',
                ),
                {},
                tool_name,
            )
        self.assertEqual(
            self.run_guard(
                'Stop', stop_hook_active=False,
                last_assistant_message='工具不可用，已说明当前阻碍。',
            ),
            {},
        )

    def test_empty_legacy_template_does_not_block_work(self):
        self.register_turn(preamble=False)
        self.append_commentary('我的理解：\n执行方案：\n本次路由：\n开始执行。')
        output = self.run_guard(
            'PreToolUse', tool_name='spawn_agent',
            tool_input={'agent_type': 'luna_max'}, tool_use_id='tool-1',
        )
        self.assertEqual(output, {})

    def test_actual_boss_alignment_allows_spawn_and_followup(self):
        self.register_turn(preamble=False)
        self.append_commentary(
            '你遇到的是：文字发完后，图片还没开始发送，列表就先显示“图片发送失败”；'
            '随后图片实际发送成功，岗位又正常删除。\n\n'
            '这次优先修这个提前报失败的标签：去掉把“尚未完成”当成“失败”的状态转换，'
            '不改实际发送流程；由sol_high复核刷新、暂停后的续发是否受影响。'
        )
        for tool_name in ('collaboration.spawn_agent', 'collaboration.followup_task'):
            output = self.run_guard(
                'PreToolUse', tool_name=tool_name,
                tool_input={'agent_type': 'sol_high'}, tool_use_id=f'tool-{tool_name}',
            )
            self.assertEqual(output, {}, tool_name)

    def test_meaningful_legacy_labels_still_allow_spawn(self):
        self.register_turn(preamble=False)
        self.append_commentary(
            '我的理解：图片未完成被误标成失败，导致标签早于实际图片发送出现。\n'
            '执行方案：修正状态转换并验证续发，先派只读复核；不修改钩子或发送流程。\n'
            '本次路由：Astra high → luna_explorer_max（复核图片状态）\n开始执行。'
        )
        self.assertEqual(
            self.run_guard(
                'PreToolUse', tool_name='collaboration.spawn_agent',
                tool_input={'agent_type': 'luna_explorer_max'}, tool_use_id='tool-1',
            ),
            {},
        )

    def test_failed_spawn_with_explicit_report_can_stop(self):
        self.register_turn()
        self.append_record({'type': 'response_item', 'payload': {
            'type': 'function_call', 'namespace': 'collaboration', 'name': 'spawn_agent',
            'call_id': 'tool-failed', 'arguments': {'agent_type': 'sol_high'},
            'internal_chat_message_metadata_passthrough': {'turn_id': self.turn},
        }})
        self.append_record({'type': 'response_item', 'payload': {
            'type': 'function_call_output', 'call_id': 'tool-failed',
            'output': {'isError': True, 'error': 'Transport closed'},
            'internal_chat_message_metadata_passthrough': {'turn_id': self.turn},
        }})
        self.assertEqual(
            self.run_guard(
                'Stop', stop_hook_active=False,
                last_assistant_message='协作未启动：spawn_agent 启动失败，Transport closed。',
            ),
            {},
        )

    def test_medium_astra_does_not_block_local_work_before_delegate(self):
        self.register_turn()
        output = self.run_guard('PreToolUse', tool_name='Bash', tool_input={'command': 'echo x'}, tool_use_id='tool-1')
        self.assertEqual(output, {})

    def test_low_astra_does_not_route_execution_work(self):
        output = self.register_turn(effort='low')
        self.assertEqual(output, {})
        output = self.run_guard('PreToolUse', tool_name='Bash', tool_input={'command': 'echo x'}, tool_use_id='tool-1')
        self.assertEqual(output, {})

    def test_unknown_effort_does_not_block_astra(self):
        output = self.run_guard('UserPromptSubmit', prompt='继续')
        context = output['hookSpecificOutput']['additionalContext']
        self.assertIn('用户可见回复省略整段模型与档位信息', context)
        self.assertNotIn('无法获取', context)
        self.assertNotIn('permissionDecision', output['hookSpecificOutput'])
        self.append_preamble()
        self.assertEqual(
            self.run_guard('PreToolUse', tool_name='Bash', tool_input={'command': 'echo x'}, tool_use_id='tool-1'),
            {},
        )

    def test_role_policy_is_advisory_not_blocking(self):
        self.register_turn()
        good = self.run_guard('PreToolUse', tool_name='spawn_agent', tool_input={'agent_type': 'luna_max'}, tool_use_id='tool-1')
        bad = self.run_guard('PreToolUse', tool_name='spawn_agent', tool_input={'agent_type': 'astra_xhigh'}, tool_use_id='tool-2')
        self.assertEqual(good, {})
        self.assertEqual(bad, {})

    def test_subagent_start_proves_delegation_and_unlocks_work(self):
        self.register_turn()
        self.run_guard('SubagentStart', agent_id='agent-1', agent_type='sol_high')
        output = self.run_guard('PreToolUse', tool_name='apply_patch', tool_input={'command': 'patch'}, tool_use_id='tool-2')
        self.assertEqual(output, {})

    def test_child_turn_subagent_start_unlocks_parent_turn_controls(self):
        self.register_turn()
        self.run_guard(
            'SubagentStart', turn_id='child-turn', model='gpt-5.6-luna',
            agent_id='agent-1', agent_type='luna_explorer_max',
        )
        for tool_name in (
            'apply_patch', 'collaboration.list_agents',
            'collaboration.wait_agent', 'collaboration.followup_task',
        ):
            output = self.run_guard(
                'PreToolUse', tool_name=tool_name,
                tool_input={'command': 'x'}, tool_use_id=f'tool-{tool_name}',
            )
            self.assertEqual(output, {}, tool_name)

    def test_collaboration_spawn_agent_name_is_recognized(self):
        self.register_turn()
        output = self.run_guard(
            'PreToolUse', tool_name='collaboration.spawn_agent',
            tool_input={'agent_type': 'sol_high'}, tool_use_id='tool-1',
        )
        self.assertEqual(output, {})

    def test_spawn_is_not_blocked_before_problem_alignment(self):
        self.register_turn(preamble=False)
        output = self.run_guard(
            'PreToolUse', tool_name='collaboration.spawn_agent',
            tool_input={'agent_type': 'sol_high'}, tool_use_id='tool-1',
        )
        self.assertEqual(output, {})
        self.append_preamble()
        allowed = self.run_guard(
            'PreToolUse', tool_name='collaboration.spawn_agent',
            tool_input={'agent_type': 'sol_high'}, tool_use_id='tool-2',
        )
        self.assertEqual(allowed, {})

    def test_successful_spawn_output_unlocks_before_delayed_subagent_start(self):
        self.register_turn()
        self.append_record({'type': 'response_item', 'payload': {
            'type': 'function_call', 'name': 'spawn_agent', 'namespace': 'collaboration',
            'arguments': json.dumps({'agent_type': 'luna_explorer_max'}),
            'call_id': 'call-1',
            'internal_chat_message_metadata_passthrough': {'turn_id': self.turn},
        }})
        self.append_record({'type': 'response_item', 'payload': {
            'type': 'function_call_output', 'call_id': 'call-1',
            'output': json.dumps({'task_name': '/root/verify'}),
            'internal_chat_message_metadata_passthrough': {'turn_id': self.turn},
        }})
        output = self.run_guard(
            'PreToolUse', tool_name='apply_patch',
            tool_input={'command': 'patch'}, tool_use_id='tool-2',
        )
        self.assertEqual(output, {})

    def test_failed_spawn_output_does_not_block_local_work(self):
        self.register_turn()
        self.append_record({'type': 'response_item', 'payload': {
            'type': 'function_call', 'name': 'spawn_agent', 'namespace': 'collaboration',
            'arguments': json.dumps({'agent_type': 'luna_explorer_max'}),
            'call_id': 'call-1',
            'internal_chat_message_metadata_passthrough': {'turn_id': self.turn},
        }})
        self.append_record({'type': 'response_item', 'payload': {
            'type': 'function_call_output', 'call_id': 'call-1',
            'output': json.dumps({'error': {'message': 'credits exhausted'}}),
            'internal_chat_message_metadata_passthrough': {'turn_id': self.turn},
        }})
        output = self.run_guard(
            'PreToolUse', tool_name='apply_patch',
            tool_input={'command': 'patch'}, tool_use_id='tool-2',
        )
        self.assertEqual(output, {})

    def test_coordination_controls_do_not_deadlock_pending_turn(self):
        self.register_turn()
        for tool_name in (
            'collaborationlist_agents', 'collaborationwait_agent',
            'collaborationfollowup_task', 'collaborationinterrupt_agent',
        ):
            output = self.run_guard(
                'PreToolUse', tool_name=tool_name,
                tool_input={}, tool_use_id=f'tool-{tool_name}',
            )
            self.assertEqual(output, {}, tool_name)
        output = self.run_guard(
            'PreToolUse', tool_name='apply_patch',
            tool_input={'command': 'patch'}, tool_use_id='tool-edit',
        )
        self.assertEqual(output, {})

    def test_successful_followup_reuse_satisfies_stop_gate(self):
        self.register_turn()
        self.run_guard(
            'SubagentStart', turn_id='child-turn', model='gpt-5.6-luna',
            agent_id='agent-1', agent_type='luna_explorer_max',
        )
        self.turn = 'turn-2'
        self.register_turn()
        self.append_record({'type': 'response_item', 'payload': {
            'type': 'function_call', 'name': 'followup_task', 'namespace': 'collaboration',
            'arguments': json.dumps({'target': '/root/existing'}),
            'call_id': 'call-followup',
            'internal_chat_message_metadata_passthrough': {'turn_id': self.turn},
        }})
        self.append_record({'type': 'event_msg', 'payload': {
            'type': 'sub_agent_activity', 'event_id': 'call-followup',
            'agent_thread_id': 'agent-1', 'agent_path': '/root/existing',
            'kind': 'interacted',
        }})
        output = self.run_guard(
            'Stop', stop_hook_active=False, last_assistant_message='done',
        )
        self.assertEqual(output, {})

    def test_stop_never_forces_retry_or_blocks_completion(self):
        self.register_turn()
        first = self.run_guard('Stop', stop_hook_active=False, last_assistant_message='done')
        second = self.run_guard('Stop', stop_hook_active=True, last_assistant_message='done')
        self.assertEqual(first, {})
        self.assertEqual(second, {})

    def test_non_astra_root_is_ignored(self):
        self.write_turn(model='gpt-5.6-sol', effort='ultra')
        output = self.run_guard('UserPromptSubmit', model='gpt-5.6-sol', prompt='继续')
        self.assertEqual(output, {})


if __name__=='__main__': unittest.main(verbosity=2)
