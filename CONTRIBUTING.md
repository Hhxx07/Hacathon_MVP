# 协作指南

1. 从 `main` 创建 `feat/<scope>-<short-name>` 或 `fix/...` 分支。
2. 每个 PR 只解决一个边界内问题；数据库变更必须包含 Alembic 迁移。
3. 领域模块只能通过公开 service/DTO 或领域事件协作，禁止跨模块直接改表。
4. 校园 connector 不得把密码、Cookie、完整页面或学生隐私写入日志和测试 fixture。
5. 提交前运行 `make lint && make test`；Compose 变更再运行 `docker compose config`。

推荐 CODEOWNERS 后续按团队账号细化：核心、校园连接器、基础设施至少两人交叉审阅。

