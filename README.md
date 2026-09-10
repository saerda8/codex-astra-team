# Codex Astra Team

Codex 多模型协作技能：Astra 负责关键判断，Sol / Terra / Luna 完成独立执行任务。小任务直接做，大任务优先一个助手完成实现和测试，减少重复读取、轮询和验收。

社区项目，与 OpenAI 无隶属关系。不提供额度扩容，也不保证固定节省比例。模型和推理档位必须在使用者客户端现场核验。

## 功能

- Astra Low 起适用协作策略，小任务不为流程创建助手。
- Sol High / XHigh、Terra Max、Luna Max 角色模板。
- 实际派工时告知交给谁、做什么；不规定其他回复的格式。
- 非阻断钩子：只记录和提醒，不拒绝工具、不阻止结束。
- “继续”等短指令结合实际工具次数观察，重复事件不重复计数。
- 候选配置、静态检查、完整性基线、备份及保护后续修改的回滚。

## 安装

需要 Python 3.11+ 和支持相应角色、模型及钩子事件的 Codex。平台和账号支持可能不同。

下载[最新发布包](https://github.com/saerda8/codex-astra-team/releases/latest)或克隆仓库，将完整内容放入客户端识别的技能目录，用户级通常为 `~/.codex/skills/codex-astra-team`。自定义 CODEX_HOME 时使用对应目录。

向 Codex 发送：

> 使用 codex-astra-team 技能，按 CODEX_ASTRA_TEAM_DEPLOY.md 和 references/GLOBAL_DEPLOYMENT.md 部署。保留我当前主模型、档位及现有配置，备份后增量合并；协作检查只能提醒。核对真实角色字段及模型能力，缺少支持时说明，不猜测、不自动换模型。

安装技能不等于完成配置。模板中的 Astra High 仅为示例；不要整份覆盖 config.toml、AGENTS.md 或 hooks.json。

教程：[部署说明](CODEX_ASTRA_TEAM_DEPLOY.md)。实现范围和限制：[项目状态](PROJECT_STATUS.md)。

## 验证

```sh
python scripts/test_strategy.py -q
```

测试使用临时目录和合成事件，不调用模型，不证明账号或客户端加载成功。真实验收需包含小任务、真实派工和失败后正常收尾。

## 源码结构

| 路径 | 用途 |
|---|---|
| SKILL.md | 技能入口 |
| assets/ | 可合并的配置、六个角色及规则 |
| scripts/astra_turn_guard.py | 非阻断回合观察和提醒 |
| scripts/model_guard.py | 项目配置审计，不决定工具权限 |
| scripts/strategy.py | 候选配置、校验、备份、回滚 |
| references/ | 部署与验证说明 |

不包含作者本机 MCP 服务、账号、密钥、聊天记录或其他项目代码。

## 贡献与许可

欢迎提交最小复现和小范围 PR。请注明客户端版本与事件类型，脱敏日志，不提交认证文件或聊天全文。

[MIT License](LICENSE)。外部文档仅作参考，不构成官方兼容性承诺。
