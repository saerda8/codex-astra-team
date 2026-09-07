# 官方资料与核验边界

资料核对日期：2026-09-06。部署时重新核对当前文档与本机版本，不根据旧版截图猜字段。

| 编号 | 来源 | 本方案引用的内容 |
|---|---|---|
| S1 | `https://learn.chatgpt.com/docs/agent-configuration/subagents` | 独立角色文件、角色参数优先级、子代理设置、托管环境限制与多代理开销 |
| S2 | `https://learn.chatgpt.com/docs/config-file/config-reference` | 主模型、推理参数、agents 默认与并发设置、features.multi_agent、features.hooks |
| S3 | `https://learn.chatgpt.com/docs/hooks` | PreToolUse 事件、spawn_agent/Agent 匹配、deny 响应、信任审核与覆盖边界 |
| S4 | `https://developers.openai.com/codex/app-server` | model/list 的 supportedReasoningEfforts 和分页、config/read |
| S5 | `https://developers.openai.com/api/docs/models/gpt-6-astra` | 模型标识及 low / medium / high / xhigh / max |
| S6 | `https://developers.openai.com/api/docs/models/gpt-5.6-sol` | 模型标识与模型定位；完整可用档位由目标客户端核验 |
| S7 | `https://developers.openai.com/api/docs/models/gpt-5.6-terra` | 模型标识与模型定位；完整可用档位由目标客户端核验 |
| S8 | `https://developers.openai.com/api/docs/models/gpt-5.6-luna` | 模型标识与模型定位；完整可用档位由目标客户端核验 |
| S9 | `https://developers.openai.com/codex/guides/agents-md` | AGENTS 指令文件发现、覆盖关系及会话加载 |
| S10 | `https://developers.openai.com/codex/skills` | 本地 Skill 目录、SKILL.md 与 .agents/skills |
| S11 | `https://openai.com/index/gpt-5-6/` | GPT-5.6 发布说明中 Work / Codex 的 max 设置与可用性说明 |

Codex 文档链接可能跳转到官方 learn.chatgpt.com 对应页面。

特别说明：模型侧 max 支持与某一版 Codex TOML 解析器是否接受 max 是不同问题。核对时官方配置枚举展示存在差异，因此必须检查目标版本并做实际验证。不得把 xhigh 私自重命名为 max。

本包角色职责、并发为二、最大一次修正重试和白名单规则是用户需求及方案设计，不是官方默认或性能保证。静态测试中的模型目录和工具事件是合成样例，不能用来证明账号可用或客户端真实路由。
