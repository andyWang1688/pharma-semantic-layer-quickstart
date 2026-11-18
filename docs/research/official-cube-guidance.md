# Cube 官方依据：权限、Python 配置、SQL API 与 AI 接入

> 实测记录说明：下文Directory是先前版本的模型名称。当前已统一为Organization View，模型已改为YAML，配置保留cube.py；原生成员校验结论继续适用。当前代码与查询见[架构](../architecture.md)及[直接请求](../examples.md)。

核查日期：2026-11-17。此文记录实际读取的 Cube 官方文档、官方发布说明及官方仓库维护者答复。示例固定版本为 Cube Core 1.7.1；当前在线文档可能包含后续版本功能，不能用在线文档证明固定版本的所有细节。

## 1. 结论与推荐等级

| 问题 | 有依据的结论 | 等级 |
|---|---|---|
| 行权限应该放在哪里？ | 当前官方 RLS 指南将 access policies 作为管理行权限的入口；规则可声明在模型中。 | 官方首要文档路径 |
| queryRewrite 是否不规范？ | 官方仍完整支持，并明确称为 security hook；在同一数据库内为不同用户定义 RLS 的场景，官方 multitenancy 文档明确给出 queryRewrite 的经验建议。 | 有明确适用范围的官方建议 |
| access policies 是 Cloud 专属吗？ | 不是。官方 GA 公告明确 Core 从 1.2.0 起可用；Core 需要自行映射 groups，并直接使用 securityContext。 | 官方公开产品能力 |
| JS 模型 + cube.py 配置是否标准？ | 是官方支持的组合。当前 admin 文档明确 Python/JS 配置等价，并写道 “when in doubt, use Python”。 | 官方支持，且有显式建议 |
| 是否必须另写一套权限 HTTP 服务？ | 未找到官方要求。官方提供 securityContext、check_auth、extend_context、query_rewrite 等扩展点；外部 HTTP 授权服务属于应用部署选择。 | 自定义架构选择 |
| AI 是否必须先拿 H+P 再作为授权参数发给 Cube？ | 未找到此项官方要求。官方 AI 路径是发现语义模型、在同一权限下查询。人员消歧可以查询人员维度，但 H+P 权限不能由模型输出代替服务端规则。 | 人员工作流与 H+P 属业务设计 |
| 是否存在“唯一最标准”的医药历史架构方案？ | 官方资料没有规定医药人员/辖区/H+P/历史快照的通用表结构和算法。需要明确业务时间及授权语义后选择 Cube 原生机制。 | 领域建模，不应冒称官方范式 |

**评审时应区别“官方推荐的入口”“官方支持的扩展点”“本 demo 的业务设计”。** 官方支持 queryRewrite，并不等于官方推荐此前 demo 中的“工具服务 → Cube → HTTP 回调工具服务”部署结构。

## 2. 行权限：access policies 与 queryRewrite

### 2.1 当前官方 RLS 指南的入口是 access policies

来源：[Row-level security][S1]。

原文：

> “You can use access policies to manage both member-level and row-level security based on groups and user attributes.”

同页同时指出：

> “By default, all rows are public, meaning that no filtering is applied to data model facts when they are accessed by any users.”

含义：只建事实、维度、View 并不会自动获得行权限。必须明确配置限制。

来源：[Access policies][S2]。

原文：

> “Access policies provide a holistic mechanism to manage member-level, row-level security, and data masking for different user groups.”

> “You can define access control rules in data model files, allowing for an organized and maintainable approach to security.”

官方同时说明 policies 与 query_rewrite 可以叠加：

> “Row-level filters in access policies are combined together with filters defined using the query_rewrite configuration option. Both will apply to the request.”

因此两者不是互斥产品模式，也不能把 queryRewrite 称为绕过官方权限体系。对可声明的规则，可优先用模型中的 policy；对确实需要过程处理的逻辑，可使用有明确边界的 custom hook。

### 2.2 queryRewrite 是正式扩展点

来源：[Configuration options — query_rewrite][S3]。

原文：

> “This is a security hook to check your query just before it gets processed. You can use this very generic API to implement any type of custom security checks your app needs and rewrite input query accordingly.”

> “Called on each request.”

> “For example, you can use query_rewrite to add row-level security filter, if needed.”

官方给出 Python 示例：

```python
from cube import config

@config('query_rewrite')
def query_rewrite(query: dict, ctx: dict) -> dict:
    context = ctx['securityContext']
    if 'filter_by_region' in context:
        query['filters'].append({
            'member': 'regions.id',
            'operator': 'equals',
            'values': [context['region_id']],
        })
    return query
```

这段是官方 API 用法说明，不是适合直接照抄的完整拒绝默认授权策略。生产规则仍需处理无身份、缺少范围、撤权和错误情况。

官方还注明：

> “Currently, there's no built-in way to access the data model metadata in query_rewrite.”

这里说的是钩子内部没有内置的模型元数据读取方式，不是 Cube 没有成员校验能力。未知字段和 View 未包含字段由 Cube 原生编译器处理；demo 不应因此复制一份字段名称名单。原生 `public`、`includes`、成员策略和不同 REST 路径的验证边界见 [专项核查](native-member-access.md)。

### 2.3 同一数据库 RLS：官方明确给出的 queryRewrite 适用建议

来源：[Multitenancy — queryRewrite vs Multitenant Compile Context][S13]：

> “As a rule of thumb, the queryRewrite should be used in scenarios when you want to define row-level security within the same database for different users of such database.”

同页 “Same DB Instance with per Tenant Row Level Security” 明确描述通过 queryRewrite 增加 tenant filter，并说明：

> “However, resources such as query queue and pre-aggregations are shared between all tenants.”

因此在本例的“同一销售库、不同用户可见不同行”范围内，选择 queryRewrite 有具体的官方建议，不只是“技术上能实现”。这段建议比较的是 queryRewrite 与按用户/租户编译不同模型的 COMPILE_CONTEXT，并没有宣称 access policies 不适合 RLS，也没有规定医药历史/H+P 的算法。

基于此，本 demo 可保留用户指定的 Python query_rewrite，并采用共享模型、共享销售 Rollup、请求时增加过滤。不能为每个工号创建模型/聚合，再声称这是上述 shared RLS 模式。

### 2.4 产品和版本边界

来源：[Data access policies GA 公告，2025-02-05][S4]：

> “Data access policies are available both in Cube Core, starting from v1.2.0, and Cube Cloud.”

来源：[Access policies — Custom mapping / Using securityContext][S2]：

> “If you are using Cube Core or authenticating against Core Data APIs directly, you might need to map the security context to groups manually.”

> “The userAttributes object is only available in Cube Cloud platform.”

因此本地 Core 应使用 `context_to_groups`，policy 中用 `securityContext`，不应复制 Cloud 专属的 `userAttributes` 示例。

来源：[Cube v1.7.0 官方 release][S5]：

> “The context_to_roles (contextToRoles) configuration option has been removed. It was deprecated in v1.6.4. Use context_to_groups (contextToGroups) instead.”

官方仓库维护者在 [issue #11273][S6] 解释 v1.7.0 将 policy 的 `role/roles` 术语统一为 `group/groups`，属于术语变更而非扩权。评审固定 1.7.1 时要使用 `group` 和 `context_to_groups`，不能直接照搬 2025 年 GA 公告里的旧 `role` 语法。

## 3. 身份与上下文的官方边界

来源：[Security context][S7]：

> “A security context is a verified set of claims about the current user that the Cube server can use to ensure that users only have access to the data that they are authorized to access.”

> “Your authentication server issues JWTs to your client application, which, when sent as part of the request, are verified and decoded by Cube to get security context claims to evaluate access control rules.”

因此登录人来自已验证身份，不能把 AI 想查的人员 ID 当作登录身份。查询对象和分析架构属于请求意图，不应自动赋予另一人的权限。

来源：[Configuration options — check_auth / extend_context][S3]：

> “Default implementation parses the JSON Web Token in the Authorization header, verifies it, and sets its payload to the securityContext.”

> “This function [extend_context] is used to extend the security context with additional data. Called on each request.”

这提供了官方认可的上下文扩展入口，但没有规定 H+P 清单必须写进 JWT，或者必须从独立 Python HTTP 服务加载。选择签名属性、Cube 内部查询、已有授权服务等方式时，必须说明撤权、缓存、版本和依赖，不能都叫“Cube 官方最佳实践”。

`extend_context` 另有正式边界：它用于 API 请求，不应用到 refresh worker；若扩展上下文影响模型编译，应按官方 `context_to_app_id` 要求隔离编译上下文。单纯行过滤与动态改变模型 SQL 应分别设计，不能为共享销售 Rollup 随意引入每用户模型编译。

## 4. Python 配置不是模拟 DSL

来源：[Administration — cube.py and cube.js files][S14]：

> “Configuration options can be defined either using Python, in a cube.py file, or using JavaScript, in a cube.js file in the root folder of a Cube project.”

> “Both ways are equivalent; when in doubt, use Python.”

同页关于依赖的当前建议：

> “It's recommended to use requirements.txt and package.json files to specify dependencies for your Python and JavaScript code, respectively.”

> “To automate the installation of dependencies, build and use a custom Docker image.”

因此 demo 的 Cube 配置若直接读取 PostgreSQL，应该声明并安装 Cube 自己运行时所需的 Python 数据库依赖；不应依赖另一个无关业务镜像恰好已经带有依赖。标准库可用时不需要为了演示额外引入第三方包。

来源：[Introducing Python for configuration，2023-10-03][S8]：

> “Cube supports Python programming language in the cube.py file to define configuration options!”

> “We are committed to supporting both Python and JavaScript going forward. Please consider using Python for new Cube projects to benefit from its concise syntax, better readability, and great ecosystem.”

官方示例包括 `@config('check_auth')`、`@config('query_rewrite')` 等。本 demo 当前使用原生 YAML 模型和 cube.py 配置，Cube 直接读取 YAML；无需额外设计 Python 生成模型的过程。

老公告里的平台限制是 2023 年状态，不能当作 2026 年当前限制。固定 1.7.1 Docker 镜像的 Python 依赖应按 [v1.7.0 release][S5] 的 Python 3.13 变更处理；不能把另一镜像中 Python 3.12 的二进制数据库包直接拷入 Cube 镜像。

## 5. SQL API：不能只测试 REST 就宣称全入口覆盖

来源：[SQL API Authentication and Authorization][S9]：

> “Cube's SQL API can also use the Security Context for Dynamic data model creation or queryRewrite property in your configuration file.”

官方 SQL 身份入口是 `checkSqlAuth` / `check_sql_auth`。SQL API 的 `__user` 和 user switching 是另外的受控能力，不能让 AI 自由切换成被查询人。

来源：[Querying data APIs][S10]：

> “Queries with pushdown can also be modified before execution with query_rewrite; however, only applying additional filters is supported.”

同页对 regular queries 和包含 regular queries 的 post-processing queries 也明确支持 query_rewrite。

来源：[Query pushdown in Cube’s semantic layer，2024-05-29][S11]：

> “With or without query pushdown, all security controls that Cube provides still work.”

> “You can apply additional filters in query rewrite, implement multitenancy, and control the visibility of data model entities with public parameters.”

可得出的结论是官方设计允许统一 RLS，不是推断 SQL 绕过权限。但是自定义 hook 若假设固定 REST JSON 成员形态、修改措施维度、依赖客户端签名的请求字段，仍必须在目标 API 和 pushdown 路径实际验证。不能把官方产品能力当作自定义代码全路径正确的证明。

评审建议：明确 demo 暴露的入口；若只演示 REST，文档写清楚。若宣称 SQL/MCP 可直接接入，应补 SQL 普通聚合、嵌套、pushdown、无分组和身份切换的权限验证。

## 6. AI 官方路径：模型发现与数据查询

来源：[Cube MCP server][S12]：

> “Every tool runs as the authenticated user. Queries respect the same permissions as the rest of Cube, including row-level security.”

该页的 query/discovery 工具为：

| 官方工具 | 官方说明 | 对本场景的含义 |
|---|---|---|
| `searchDataModel` | “Searches the semantic model by similarity — views and their measures and dimensions — to discover what is queryable.” | 找到人员目录 View 和人员 ID、姓名等维度；不是按姓名检索人员记录 |
| `runQuery` | “Runs a Cube SQL query (PostgreSQL dialect) against the SQL API.” | 查询人员维度值以识别李四，再查询销售或领导关系 |

官方明确：

> “Call searchDataModel before runQuery to find exact view and member names rather than guessing them.”

因此一个贴近官方通用路径的例子是：发现 Directory 与 Sales 模型 → 查询 Directory 中姓名为李四的记录 → 同名消歧 → 用明确业务筛选查询 Sales。`search_people / get_managers / query_sales` 四个 Python 工具可以是产品体验封装，但不是 Cube 规定必须有的标准组件。

### Core 与 Cloud 不应混称

该官方 MCP 页说明的是 Cube 托管端点 `https://cubecloud.dev/mcp`，OAuth/账户/部署/角色及 Admin 管理的产品能力。它不是“只启动 cubejs/cube Docker 镜像就自动有同样 MCP 服务”的依据。

本地 Core 使用 Meta API 加 REST/SQL 实现薄工具，是基于官方 Core API 的自定义接入方式。要标明“基于官方 API 的示例”，不能声称它是官方托管 MCP 的一比一复刻，也不应让 AI 工具承担另一套可绕过的授权逻辑。

## 7. 本 demo 评审时应明确的自定义内容

| 自定义内容 | 为什么需要明确 |
|---|---|
| 当前、指定快照、逐期历史模式 | Cube 没有内置医药领域组织口径；必须由业务定义 |
| 同辖区医院集合 × 产品集合 | 来源系统业务假设，有例外时须改显式辖区/H/P 覆盖桥表 |
| 共享业绩按授权事实并集计算 | 已确认的业务口径，不等于组织行可加总 |
| 查询对象完整范围不足时拒绝 | 当前示例的产品决策，亦可设计明确标注的部分可见结果 |
| 人员目录可见性、直接管理者定义 | 应采用真实人员和岗位关系，不由名字或层级猜测 |

这些业务规则可以用 Cube 官方机制安全执行，但官方文档没有给出唯一表结构或唯一服务拆分。最终实现应保留可审查的领域规则与官方功能边界。

## 参考来源

| 编号 | 已读取的一手来源 | 支持的核心事实 |
|---|---|---|
| S1 | https://docs.cube.dev/docs/data-modeling/access-control/row-level-security | RLS 文档入口与默认无过滤 |
| S2 | https://docs.cube.dev/docs/data-modeling/data-access-policies | policies、Core group mapping、Cloud userAttributes、叠加 queryRewrite |
| S3 | https://docs.cube.dev/reference/configuration/config | query_rewrite/check_auth/extend_context 的正式配置接口 |
| S4 | https://cube.dev/blog/introducing-data-access-policies-ga-and-ldap-integration-in-cube-cloud | Core 1.2.0 与 Cloud 的 GA 可用性 |
| S5 | https://github.com/cube-js/cube/releases/tag/v1.7.0 | context_to_roles 移除、Python 3.13 变更 |
| S6 | https://github.com/cube-js/cube/issues/11273 | 官方维护者解释 role → group 迁移 |
| S7 | https://docs.cube.dev/embedding/authentication/security-context | verified claims、身份与规则边界 |
| S8 | https://cube.dev/blog/introducing-python-for-configuration | 官方 cube.py 支持及新项目 Python 建议 |
| S9 | https://docs.cube.dev/reference/core-data-apis/sql-api/security | SQL 身份、securityContext、queryRewrite |
| S10 | https://docs.cube.dev/reference/core-data-apis/queries | regular/post-processing/pushdown 与 rewrite 边界 |
| S11 | https://cube.dev/blog/query-push-down-in-cubes-semantic-layer | SQL pushdown 安全控制不被绕过 |
| S12 | https://docs.cube.dev/docs/integrations/mcp-server | 官方 AI discovery/runQuery、用户权限、托管端点 |
| S13 | https://docs.cube.dev/embedding/multitenancy | 同库 RLS 推荐 queryRewrite；共享队列与预聚合；与编译上下文区分 |
| S14 | https://docs.cube.dev/admin | Python/JS 配置等价、倾向 Python、依赖声明及自建镜像 |

[S1]: https://docs.cube.dev/docs/data-modeling/access-control/row-level-security
[S2]: https://docs.cube.dev/docs/data-modeling/data-access-policies
[S3]: https://docs.cube.dev/reference/configuration/config
[S4]: https://cube.dev/blog/introducing-data-access-policies-ga-and-ldap-integration-in-cube-cloud
[S5]: https://github.com/cube-js/cube/releases/tag/v1.7.0
[S6]: https://github.com/cube-js/cube/issues/11273
[S7]: https://docs.cube.dev/embedding/authentication/security-context
[S8]: https://cube.dev/blog/introducing-python-for-configuration
[S9]: https://docs.cube.dev/reference/core-data-apis/sql-api/security
[S10]: https://docs.cube.dev/reference/core-data-apis/queries
[S11]: https://cube.dev/blog/query-push-down-in-cubes-semantic-layer
[S12]: https://docs.cube.dev/docs/integrations/mcp-server
[S13]: https://docs.cube.dev/embedding/multitenancy
[S14]: https://docs.cube.dev/admin
