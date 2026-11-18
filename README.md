# Pharma Semantic Layer Quickstart

基于 **dbt + Cube** 的医药行业数据分析语义层参考实现。以销售星型模型为起点，包含医院和产品维度、人员岗位关系、历史架构、数据权限与预聚合，可作为搭建同类项目的基础。

## 快速开始

需要 Docker Engine / Docker Desktop 和 Docker Compose v2。所有数据为合成数据；Python 及数据库依赖在容器中安装，无需配置本机 Python 或外部业务系统。

在项目根目录执行：

~~~sh
cp .env.example .env
sh run.sh up
~~~

启动命令会初始化 PostgreSQL、执行 dbt build，并启动 Cube 和测试页面。首次启动需要下载镜像和依赖，终端最后输出页面地址。

打开 [http://127.0.0.1:32770](http://127.0.0.1:32770)，使用默认的王经理身份查询 2026 年 1 月，销售额为 **180**。切换张三本人查询，销售额为 **130**。

~~~sh
sh run.sh check       # 代码检查、格式检查、错误路径测试
sh run.sh test        # dbt、数据质量、真实查询、权限、历史架构和预聚合验收
~~~

## 包含的能力

| 能力 | 实现 |
|---|---|
| 分层数仓与星型模型 | raw → staging → intermediate → marts；交易事实关联医院、产品，按销售日期分析 |
| 语义层 | YAML 定义指标、维度、关联与 Sales / Organization View，使用 Cube REST 查询 |
| 组织与历史架构 | 人员任职、岗位树、岗位医院产品关系；支持当前、指定版本、逐期历史口径 |
| 数据权限 | JWT 身份、当前岗位授权、完整对象范围校验；Cube Python query_rewrite 强制过滤 |
| 查询与性能验证 | 月度预聚合、未匹配查询回源；可选筛选页面和数字员工工具适配 |

人员重名、兼岗、空岗、调岗和多对多关系作为正确性验收场景。数字员工页展示工具调用流程，未接入大模型。

## 模型与代码

~~~mermaid
flowchart LR
  Hospital[医院维度] -->|一对多| Fact[销售事实]
  Product[产品维度] -->|一对多| Fact
  Fact --> Sales[Sales View<br/>指标、时间分析、预聚合]
  Employee[人员任职] --> Tree[版本化岗位树]
  Tree --> Bridge[岗位医院产品关系]
  Bridge -.->|访问范围| Fact
  Grant[当前岗位授权] --> Policy[Cube Python 权限规则]
  Bridge --> Policy
  Policy -->|强制过滤| Sales
~~~

~~~text
项目根目录/
├── db/init/                  合成源数据、账号与岗位授权
├── dbt/                      8 个 staging、6 个 intermediate、6 个 Mart
├── cube/
│   ├── cube.py               Cube 原生配置与钩子注册
│   ├── security/policy.py    业务权限、架构口径与查询过滤
│   ├── security/database.py  连接、参数绑定与请求内只读事务
│   └── model/                4 个 YAML Cube、2 个业务 View
├── demo/                     可选客户端、工具适配与诊断页面
├── tests/                    数据、权限、查询、刷新与错误路径验收
├── docs/                     架构、改造入口、请求样例与设计依据
├── .env.example              本机运行配置模板
└── run.sh                    统一运行和验证命令
~~~

主要业务权限集中在 [policy.py](cube/security/policy.py)；Cube 注册入口在 [cube.py](cube/cube.py)。销售模型见 [SalesFacts.yml](cube/model/cubes/SalesFacts.yml)，星型关系与配套关系表的粒度见[架构](docs/architecture.md)。

## 配置与使用

| 默认地址 | 用途 |
|---|---|
| http://127.0.0.1:32770 | 筛选查询、人员识别与工具调用 |
| http://127.0.0.1:32771/cubejs-api/v1 | Cube REST，使用有效 JWT |
| 127.0.0.1:32772 | PostgreSQL：库 shared_sales，用户 example，密码 example-only，关闭 SSL |

.env 可设置项目名、三个端口、Cube 签名密钥和日志等级，详见 [.env.example](.env.example)。数据库名和表名集中于 Compose、dbt 和 SQL 配置。所有端口仅绑定本机。

~~~sh
sh run.sh token E001  # 签发两分钟有效的合成身份令牌，便于直接查询 Cube
sh run.sh build       # 源数据变化后，重建 dbt 模型并恢复服务
sh run.sh down        # 停止并删除本套容器；同时清除 tmpfs 中的合成数据库
~~~

**数据库使用 tmpfs，down 和重建数据库容器都会清空数据。** up 保留正在运行的数据库容器。公开的账号、签名密钥及 X-Demo-Viewer 身份切换用于本机复现。

实际查询参数与预期结果见[REST 与工具示例](docs/examples.md)；一条业务请求如何得到结果见[请求链路](docs/request-walkthrough.md)。

## 在此基础上开发

[适配自己的项目](docs/customization.md)列出替换源数据、增加指标、接入企业身份、调整授权和配置预聚合的代码入口。[Review 指南](docs/review-guide.md)给出源码审阅顺序。

本项目遵循星型建模方法。医药业务的岗位授权、完整月快照和历史口径是本参考实现的明确选择，具体假设见[架构](docs/architecture.md)；Veeva 关系对象的参考边界见[映射说明](docs/research/veeva-object-mapping.md)。

当前技术版本：Cube Core 1.7.1、dbt Core 1.9.10 / dbt-postgres 1.9.1、PostgreSQL 16。验收包括 118 项 dbt 数据测试、18 个销售场景，以及实时撤权、停用、版本切换和 Rollup 对账。GitHub Actions 配置在 [.github/workflows/validate.yml](.github/workflows/validate.yml)。

清单过滤最多覆盖连续 24 个月、50,000 个月份/医院/产品组合；客户端结果达到 1,000 行时明确报错。事实与覆盖同时增长时的 PostgreSQL 设计建议见[规模与查询成本](docs/customization.md#postgresql-规模与查询成本)。日级组织变更及生产部署需独立验证。工程修改约定见[示例工程约定](docs/standards/example.md)。
