# 使用方式

从根目录 CODEX_ASTRA_TEAM_DEPLOY.md 开始，配合完整仓库或发布ZIP部署。MD不内嵌另一份源码。

默认全局增量合并，仅在用户明确需要隔离时使用 DEPLOYMENT.md 的项目级 staging。按当前工具schema确认角色字段，agent_type可用时用它选角色，task_name仅作标签。

本包不安装MCP服务、不包含作者的账号或worker。已有合适MCP时可使用，没有时正常继续。新任务中验证真实加载，不承诺旧任务或所有客户端热刷新。
