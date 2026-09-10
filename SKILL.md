---
name: codex-astra-team
description: Use when installing, upgrading, auditing, or repairing an Astra-led multi-model Codex strategy across all projects or within one project.
---

# Astra / Sol 多模型策略部署器

## 固定策略

保留用户的以下设定，不自行降低档位或替换模型：

| 角色 | 模型 | 推理强度 |
|---|---|---|
| 主会话 | gpt-6-astra | 当前回合实际档位 |
| astra_xhigh | gpt-6-astra | xhigh |
| sol_high | gpt-5.6-sol | high |
| sol_xhigh | gpt-5.6-sol | xhigh |
| terra_max | gpt-5.6-terra | max |
| luna_max | gpt-5.6-luna | max |
| luna_explorer_max | gpt-5.6-luna | max，只读 |

让 Astra 直接负责核心方案、关键机制、重大取舍与关键验收。让 Sol 独立完成既定方案内的复杂实现、模块设计、排查与日常验收。不要把 Astra 变成只能最后救火的角色，也不要让它包办普通执行。只由主会话创建子代理；并发上限为两个；子代理关闭进一步派生。

运行触发条件固定为：主会话是 `gpt-6-astra` 且推理档位为 low、medium、high、xhigh、max 或 ultra。从 Astra Low 起进入协作路由，以便额度较低的 Plus、Teams 五小时制账号尽早把执行工作交给 Sol、Terra、Luna。普通解释、追问、确认或状态问题直接回答，不触发协作、不调用 `spawn_agent`，也不恢复旧任务；非 Astra 主会话不触发本策略。

未明确确认主会话是 `gpt-6-astra` 且档位符合条件时，禁止输出 `本次路由：Astra`，禁止按 Astra 规则强制派工；按当前真实模型及通用规则正常执行。

保持 Codex 默认表达方式；本技能不规定开头、中间过程、结论或其他回复的格式、标题、措辞、顺序及示例。实际派工时只额外用一句话说明交给谁、做什么；使用已核实的角色和档位，不猜测，不把计划写成已经执行，不要求在进度或结尾重复。


## 可见路由与协作建议

节省额度优先：本节优先于“每个执行任务都派工、尽量多派、不能让 worker 闲置”等数量要求。
- 小任务（简单问答、已定位的局部修改、单次检查）由当前主模型直接完成，不为流程额外创建助手或调用 MCP；Astra Low 起适用协作策略，不代表每件事都新建助手。
- 大任务优先交给一个匹配角色完成完整的实现和相关测试；已有助手适合时复用。新助手只传必要目标、证据、允许范围和验收标准，独立任务不继承整段历史。只有确有独立并行工作才增加第二个助手。
- 主模型不重复助手正在做的调查；结果到达后只审查必要差异并完成一次与风险相称的验收。已有有效测试证据可复用，有新修改、失败或疑点才重跑。
- 已读且未变化的技能与文档不重复加载；独立读取合并一次，日志先筛选、汇总再输出，禁止把完整历史、工具目录或巨型日志塞回上下文。
- 等待优先使用完成通知或阻塞式等待；无新证据不反复查询，不为汇报状态启动其他任务。进度说明只报新发现。
- MCP 同样计入启动和协调成本，小任务可直接做；有合适且可用的 MCP 时用于独立执行部分，不为凑调用增加一层派工。上述优化不改变用户选择的模型/档位、权限或非阻断原则。

明确执行型任务触发后应优先真正派工，而不是只做角色判断或写一个标签。Astra 仍负责核心决策、总控和关键验收，并尽量把独立调查、实现、测试或复核之一交给匹配角色；协作建议不能阻断项目本身继续执行。


### 派工通知


### 对话与执行的边界

普通解释、追问、确认或状态问题（例如“环境存在异常就拿不到岗位详情吗？”“这两者有因果关系吗？”）只做回答，不进入协作、不派助手、不恢复旧任务。明确的修复、修改、实现、排查或测试请求才进入协作流程。`UserPromptSubmit` 默认静默，仅记录状态；`additionalContext` 不得注入命令，检查脚本不得输出硬拦截。

全局部署安装 `scripts/astra_turn_guard.py` 并合并 `assets/hooks.global.fragment.json`。脚本按 `session_id + turn_id` 记录普通交流、长短任务和真实派工；`PreToolUse` 只在较长任务尚未安排协作时提醒一次，不能拒绝任何工具；`Stop` 始终放行。工具启动失败时允许明确报告阻碍并正常结束，不得要求重复派工。

Astra 主会话不以 MCP 派工代替模型角色派发。固定顺序是 Astra → Sol/Terra/Luna；已启动的模型角色可按任务需要调用 MCP Worker。MCP 与模型角色不是两套同时抢占主会话的同级门禁。

### MCP 的边界

MCP 是条件性能力：已加载、健康且适合当前子任务的 MCP 必须调用，由 Sol/Terra/Luna 按职责使用；没有、不可用、失败或不适合时不阻断，由当前模型角色继续完成。不得新增或启用强制 MCP 门禁，也不得因 MCP 缺失阻止角色派工、验收或正常收尾。

## 执行流程

默认先读取 `references/GLOBAL_DEPLOYMENT.md`；只有用户明确要求项目隔离时才使用 `references/DEPLOYMENT.md`。核对外部接口时读取 `references/SOURCES.md`；安装和启动说明见 `references/USAGE.md`。

1. 确认真实用户级 Codex 配置、客户端版本、Python 3.11+、权限、认证方式与生效配置层。默认全局部署；只检查登录状态，禁止读取凭证。没有目标环境权限时交付待安装状态，不声称已部署到用户机器。
2. 用真实客户端能力核对模型与推理档位。取得完整 `model/list` 结果后运行 `scripts/strategy.py catalog-check`；不得伪造目录、把 max 映射成 xhigh、或更换计费方式来通过检查。
3. 运行 `scripts/test_strategy.py` 做离线自检。离线测试只证明脚本逻辑，不证明 Codex 兼容性或账号可用性。
4. 用 `scripts/strategy.py stage` 在非自动加载目录生成候选文件。全局部署按 `GLOBAL_DEPLOYMENT.md` 分别备份并增量合并；项目隔离部署才使用脚本的项目级 `backup`。不清理未提交修改。
5. 根据指南增量合并候选文件：主配置、六个角色、`astra_turn_guard.py`、四类全局钩子、项目长期规则、忽略项与使用说明。脚本故意不自动覆盖现有 TOML，由部署代理保留其他配置并审查差异。
6. 从当前运行时核实 `spawn_agent` 参数结构和钩子输入。当前运行时已经验证角色字段，派发必须使用已验证的 `agent_type` 选择固定角色；`task_name` 只能作为标签。其他运行时若没有角色字段，必须报告协作能力缺失，不得用标签假装派工，只保留不阻断的审计记录。
7. 调用 `seal` 建立已部署文件的完整性基线，再调用 `verify`。策略锁文件 `.codex/model-policy.json` 是本包自建格式，不是 Codex 原生字段。
8. 通过正常流程完成项目及钩子信任审核，重新加载新会话。做真实正向、负向派发、权限和模型路由验证，并核对每个 Astra Low 以上任务是否优先创建了匹配的非 Astra 子智能体及可见路由回执。不得绕过审批或用合成事件替代真实生效测试。
9. 记录后置基线 `finalize-backup`，交付状态、证据、变更清单和回滚路径。发现后续用户改动时停止自动回滚。

## 必须运行的脚本

在本技能根目录内执行，以下路径变量由你替换为已经确认的绝对路径：

```text
python scripts/test_strategy.py
python scripts/strategy.py catalog-check --catalog <完整模型目录JSON>
python scripts/strategy.py stage --project <目标项目> --out <新的候选目录>
python scripts/strategy.py backup --project <目标项目> --backup <新的备份目录>
python scripts/strategy.py seal --project <目标项目> --adapter <已核验适配器JSON>
python scripts/strategy.py verify --project <目标项目>
python scripts/strategy.py finalize-backup --project <目标项目> --backup <同一备份目录>
```

禁止只修改 `AGENTS.md` 后报告部署完成。禁止把语法通过、静态检查通过、模型可见、钩子真实运行混为同一个验证结果。保留原审批与沙箱规则；通过派发检查时脚本返回空对象，不额外批准工具调用。

## 完成标准

区分文件生成、配置合并、静态检查和运行时验证的证据，不规定报告格式。只有真实加载、实际模型/档位证据、钩子负向测试和工作样例均通过，才能标记“已验证生效”。若运行时拿不到档位证据，明确写“档位路由未验证”。不得承诺固定节省比例。
创建阶段的离线测试记录见 `references/BUILD_VALIDATION.md`；部署时仍需重新测试并取得真实运行证据。
