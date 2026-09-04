# Study Platform

面向学生的容器化学习服务后端。当前 MVP 提供账户、日程/DDL/课表、番茄钟、媒体目录、积分账本，以及可插拔校园系统连接器；桌宠作为未来客户端，只消费稳定 API 和领域事件，不侵入核心业务。

## 架构边界

- `core`：模块化单体，是用户、日历、任务、番茄钟、媒体和积分的唯一业务真相来源。
- `worker`：从 Redis 消费异步任务/领域事件，适合通知、积分结算和同步编排。
- `campus`：隔离学校登录及解析差异，只输出统一课表/作业 DTO；禁止直接写核心数据库。
- `postgres`：持久业务数据；`redis`：队列、锁、缓存；`minio`：自有音频/封面对象存储。
- `caddy`：唯一公开入口，自动 TLS；数据库和内部服务不暴露宿主机端口。

这是一套适合早期多人协作的“模块化单体 + 独立自动化适配器”，避免在业务尚未稳定时承担微服务分布式事务成本；各运行单元已经独立容器化，未来可按负载拆分。

## 快速启动（Debian 12/13）

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker

cp .env.example .env
# 修改 .env 中三个密码/密钥；生产环境把 DOMAIN 改为已解析到服务器的域名
docker compose up -d --build
docker compose exec api alembic upgrade head
curl http://localhost/health/ready
```

本地 API 文档：`http://localhost/docs`。生产域名下 Caddy 自动申请证书。

## API MVP

| 范围 | 端点 | 说明 |
|---|---|---|
| 系统 | `GET /health/live`, `/health/ready` | 容器与依赖探针 |
| 用户 | `POST /api/v1/auth/register`, `/login` | JWT 登录 |
| 日历 | `GET/POST/PUT/DELETE /api/v1/events`, `GET /api/v1/calendar` | 事件 CRUD、时间筛选；统一返回导入事件、个人日程和任务 DDL |
| 任务 | `GET/POST /api/v1/tasks` | 作业/待办，支持截止时间 |
| 番茄钟 | `POST /api/v1/focus/start`, `/{id}/finish` | 服务端记录会话，客户端负责倒计时显示 |
| 媒体 | `GET /api/v1/media/tracks` | 白噪音/学习音乐元数据 |
| 积分 | `GET /api/v1/rewards/balance` | 不可变积分账本余额 |
| 校园连接器 | `POST /sync/preview` | 标准化课表/作业预览（当前 mock） |

除注册、登录和探针外，端点需 `Authorization: Bearer <token>`。校园账户凭据不能进入日志或核心库；正式连接器应优先使用学校 OAuth/CAS 短期令牌，并在服务端密钥库加密。

## 开发

```bash
uv sync
cp .env.example .env
make test
make lint
make dev
```

新增学校时实现 `services/campus/campus/connectors/base.py` 的协议，并添加固定 HTML/JSON fixture 测试。详见 [架构决策](docs/architecture.md) 和 [协作指南](CONTRIBUTING.md)。

## 尚未冒充“完成”的部分

- 音乐版权与真实文件上传策略需要项目方确认；仓库只提供元数据/对象存储边界。
- 校园爬虫必须按具体学校系统实现，mock 只证明接口和隔离边界。
- 通知、重复日程、CalDAV/ICS、积分商城与桌宠协议属于后续迭代。

日历导入可使用 `POST /api/v1/events/sync`（或 `/api/v1/calendar/sync`），请求体为
`{"source": "campus", "items": [{"external_id": "...", "title": "...", "kind": "course", "starts_at": "...", "ends_at": "..."}]}`。
同步按用户、来源和外部 ID 幂等更新；`kind: "task"` 会归一化为 `deadline`，也支持只提供 `due_at`。

## 许可

许可证尚待团队确认。在选择 MIT、Apache-2.0 或 AGPL-3.0 等许可证前，仓库代码默认保留全部权利。引入音乐、插画和学校页面解析 fixture 时还需单独核验版权与隐私许可。
