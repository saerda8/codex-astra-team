# Codex Astra Team 部署教程

版本 1.5.0。本文件与仓库或发布 ZIP 配套使用，不内嵌容易过期的源代码副本。

本版不规定开头、过程或结论的表达格式，只在实际派工时通知交给谁、做什么。升级时同步技能文件和全局 AGENTS.md 中的协作规则；旧任务已加载的指令可能保留，新任务会读取新版规则。

## 部署步骤

1. 阅读 SKILL.md 和 references/GLOBAL_DEPLOYMENT.md。核验 CODEX_HOME、Python 3.11+、真实模型目录、角色字段和钩子支持；保留用户选定的主模型与档位。
2. 运行 `python scripts/test_strategy.py -q`。备份目标 config.toml、AGENTS.md、hooks.json 及同名角色文件；不要读取认证文件。
3. 按 assets/config.global.fragment.toml 增量合并角色注册，将 assets/agents 九个角色放入用户级 agents 目录。主模型及档位仅在用户明确要求时更改。
4. 将 scripts/astra_turn_guard.py 复制到用户级 hooks 目录，或建立指向已安装技能脚本的包装器。合并 assets/hooks.global.fragment.json，替换 CODEX_HOME 和 Python 路径；其他平台需使用本机路径及引号。保留原安全钩子，不改信任数据库。
5. 将 assets/PROJECT_RULES.md 标记区间合并到用户级 AGENTS.md。GPT-6 Astra / Sol 从 Medium 起先派工，GPT-6 Luna 按 High / XHigh / Max 分档，精简交接、真实值判断、非阻断规则必须一起部署。
6. 按客户端正常流程审核钩子并加载配置。在新任务中执行真实小样例，分别报告文件部署、离线测试与实际加载结果。

角色字段依当前 schema 核验。agent_type 可用时用它选角色；task_name 是标签，不能据旧适配器名字猜字段。

## 验收与更新

简单问答不额外派工；GPT-6 Astra / Sol 的 Medium 及以上明确执行任务实际使用合适角色。没拿到档位时省略，不反推实际后端设置。任何协作误判或工具失败都不能导致硬拦截；原有客户端审批保持有效。

更新时同步技能和 hooks 中的脚本副本。旧任务可能保留旧规则，应明确重新读取；不承诺所有客户端热刷新。

移除时只撤销本次新增角色、规则标记区间及指向本项目的钩子，不删除其他配置。项目级 staging、备份、回滚见 references/DEPLOYMENT.md。
