# Cube 原生成员校验与本示例的权限边界

> 实测记录说明：下文Directory是先前版本的模型名称。当前已统一为Organization View，原生成员校验结论继续适用；当前代码与查询见[架构](../architecture.md)及[直接请求](../examples.md)。

核查日期：2026-11-17。运行版本：Cube Core **1.7.1**。已核对容器内 `api-gateway`、`schema-compiler`、`server-core` 三个包，版本均为 `1.7.1`。在线文档为滚动更新内容；下文将文档承诺、固定版本实现与实测结果分开记录。

## 1. 结论：不需要在 Python 再维护一份字段名清单

`Sales` / `Directory` View 的 `includes` 已经定义可查询的业务成员。不存在的 View 成员应交给 Cube 编译器判断。本例中的 `SALES_MEMBERS`、`DIRECTORY_MEMBERS` 属于重复维护，可以删除。

但**不能把所有查询入口限制也一起删除**。在本次 1.7.1 REST 实测中，`public: false` 会隐藏元数据，并阻止隐藏成员作为 `/load` 的结果列返回；它不会全面禁止隐藏成员用于过滤，`/sql` 编译接口也可能为私有 Cube 成员生成 SQL。因此本示例继续在 `query_rewrite` 中限定一次请求只能使用 `Sales` 或 `Directory` 中的一个业务 View，并按该 View 注入对应行权限。该限制检查所有传入成员的前缀，不逐个列举字段。

这三个职责应分开：

| 职责 | 放在哪里 | 是否另写字段清单 |
| --- | --- | --- |
| 成员定义、类型、View 暴露哪些成员 | Cube 模型与 View `includes` | 否 |
| 当前请求走销售权限还是人员目录权限，是否混入内部 Cube | Python `query_rewrite` 的业务 View 路由 | 否，只判断 View 名称 |
| 当前登录者能看哪些人员、哪些医院产品事实 | 同一个 Cube 安全 hook 注入强制过滤 | 否，查询业务权限关系 |
| 按用户组配置哪些成员可访问 | 如有此需求，可用官方 `access_policy.member_level` | 不应在应用中再复制模型字段列表 |

本例按已确认要求保留 `query_rewrite`，没有因此引入 `access_policy`。

## 2. 官方文档分别承诺什么

### View 定义消费面

[Views][S1] 说明 View 是底层 Cube 数据图的 facade，可以控制成员和 join path；`includes` 列出 View 要包含的 measures、dimensions、hierarchies、segments。成员未包含进 View，就不存在相应的 `View.member` 路径。

当前文档另有明确说明：View 包含的成员不继承底层成员的 `public` 标记；底层 `public: false` 成员仍可通过包含它的 View 查询。这支持“内部 Cube + 公开业务 View”的建模方式，但不能推出任意 REST 入口、任意成员引用位置都具有相同的拒绝行为。

### `public` 是可见性配置，固定版本仍需验证实际入口

[Views][S1] 对 `public: false` 的文档措辞是“this view cannot be queried through the API”。实际 1.7.1 对返回列、过滤字段、SQL 生成接口的处理不同，见第 3 节。不能只根据 `/meta` 没有出现某个 Cube，就认为请求无法引用它。

### 需要按用户组声明成员权限时，官方提供 access policies

[Member-level security][S2] 将成员权限类比数据库表和列权限，明确支持在 Cube / View 上使用 `access_policy.member_level.includes` 或 `excludes`，并说明未获得策略授权的其他组默认被拒绝。

这是声明式成员授权功能；`View.includes` 是 View 自身的组成定义，`public` 是可见性配置，三者不应混为一个机制。是否采用 policy 是权限设计选择，不是删除重复字段清单的前提。

### hook 没有模型元数据 API，不代表编译器不会校验

[Configuration — query_rewrite][S3] 称其为 security hook，可追加行权限或抛出异常拒绝请求。同时明确写道：

> Currently, there's no built-in way to access the data model metadata in `query_rewrite`.

这是 **hook 的可用接口**限制，不是 Cube 编译器的校验能力限制。[官方 issue #6652][S4] 中维护者提出的 workaround 是携带相同 JWT 调用 `/meta` 获取模型元数据。该办法面向需要模型反射的通用 hook；本例只需要按两个业务 View 选择权限处理，无须为此发起 Cube 到自身的 `/meta` HTTP 请求。

## 3. 固定版本实测：不要把 `/sql` 成功当成 `/load` 能返回数据

隔离探针使用与示例相同的 1.7.1 镜像、相同模型与数据库连接、Tesseract；配置为 `NODE_ENV=production`、`CUBEJS_DEV_MODE=false`，`query_rewrite` 仅原样返回 query。探针没有发布宿主机端口，正式示例的权限 hook 没有关闭。

| 请求 | 原生结果 | 能证明什么 |
| --- | --- | --- |
| `/meta` | 只返回 `Sales`、`Directory` | 内部 Cube 不向消费端自省公开 |
| `/sql` 选择 `SalesFacts.total_amount` 或 `SalesFacts.sales_id` | HTTP 200 | 私有 Cube 成员仍可通过该 REST 入口编译 SQL |
| `/sql` 引用不存在的 `Sales.does_not_exist` | HTTP 400 | 编译器校验实际引用的成员是否存在 |
| `/sql` 引用 View 未包含的 `Sales.sales_id` | HTTP 400 | 底层存在的成员不会自动成为 View 成员 |
| `/load` 返回公开 `Sales.province_name`，同时选择私有 `SalesFacts.total_amount` | HTTP 500，`You requested hidden member` | 私有 measure 在结果转换阶段被拒绝输出 |
| `/load` 选择私有非主键维度 `Hospitals.province_name` | HTTP 500，`You requested hidden member` | 私有维度同样不能作为结果列输出 |
| `/load` 选择公开销售列，过滤 `SalesFacts.hospital_code = H1` | HTTP 200，返回北京、销售额 100 | 私有成员可用于筛选公开结果，不能仅靠 `public` 禁止这种引用 |
| `/load` 加入未选择的 `order: SalesFacts.total_amount desc` | HTTP 200 | 未选择的排序项可能被忽略，不能声称任意 order 成员一定被存在性或可见性校验拒绝 |

返回列测试通过省份维度使查询走底层查询，避免预聚合匹配行为掩盖成员可见性结论。这些是该固定版本、该模型的结果，不承诺未来版本保持相同 HTTP 状态码。

REST `/sql` 是生成 SQL 的接口；这里的测试不等于对 PostgreSQL 协议 SQL API 做了测试。两个接口不能仅凭名称相似合并结论。

## 4. 源码解释与报告边界

已直接读取运行镜像安装的以下代码，未修改运行文件：

| 安装包内路径 | 核对到的行为 |
| --- | --- |
| `@cubejs-backend/schema-compiler/dist/src/compiler/CubeEvaluator.js`；[v1.7.1 源码][S7] | `cubeNameFromPath`、`byPathAnyType`、`byPath`、`parsePath` 对不存在的 Cube / member 抛错；这与 `public` 可见性是两回事 |
| `@cubejs-backend/api-gateway/dist/src/gateway.js`；[v1.7.1 源码][S8] | `filterVisibleItemsInMeta` 按 `isVisible` 过滤模型成员；开发模式或 Playground 身份存在例外，因此探针关闭开发模式 |
| `@cubejs-backend/api-gateway/dist/src/helpers/prepare-annotation.js` | annotation 从过滤后的模型元数据构建，围绕返回的 measures、dimensions、带 granularity 的 timeDimensions；没有递归检查 query.filters / order |
| `@cubejs-backend/schema-compiler/dist/src/adapter/BaseQuery.js` | `collectAllMemberNames` 采集查询涉及成员；`allMembersConcat` 包含 filters、measureFilters、segments 和 timeDimensions，未把任意 order 项单独加入 |
| `@cubejs-backend/server-core/dist/src/core/CompilerApi.js`；[v1.7.1 源码][S9] | `applyRowLevelSecurity` 在启用 RBAC 后才执行 policy 逻辑，依据查询成员判断适用策略；未经启用直接返回，不会凭 `public: false` 自动获得 policy |

[官方 PR #10590][S5] 解释 `/load` / GraphQL 返回阶段的检查链：RBAC 可见性影响 meta，meta 过滤后构建 annotation，Rust 转换层拒绝不在 annotation 中的返回成员。[后续 issue #10601][S6] 记录 filter-only timeDimensions 不应按返回列做 annotation 校验的回归及修复，进一步说明“参与过滤”和“作为返回列”并非同一检查路径。

源码机制与本次探针结果互相印证。另已成功读取官方仓库 `v1.7.1` 下的 `CubeEvaluator.ts`、`gateway.ts`、`CompilerApi.ts`；上述源码链接固定到该版本。PR 与 issue 用于解释检查机制，不替代安装包与隔离实测的版本证据。

## 5. 对本示例的具体处理

1. 删除 Python 中逐个枚举 `Sales.*` / `Directory.*` 的重复字段集合；新增 View 成员由模型维护。
2. 保留对传入 query 的递归成员采集，包括嵌套 filters、timeDimensions、segments 和 order，以便判断业务入口。一次请求仅接受一个已支持的业务 View；直接引用内部 Cube 或混用两个 View 时拒绝。
3. 路由通过后，追加该 View 对应的强制行权限。原有过滤与强制权限取交集；不能让用户传入过滤替代权限条件。
4. 不把未知成员检查包装成自建 schema 校验器。对确实需要编译的未知 measure / dimension / filter，交给 Cube 报错；未选中的 order 可能被忽略，接口文档不承诺全部未知排序字段都会报错。
5. `public: false` 和 View `includes` 继续用于模型可见性与消费面；Python View 入口检查承担本示例的安全路由职责。以后需要按用户组声明字段权限，再评估原生 member-level access policies。

因此，**可以去掉重复字段清单，不能去掉“所有允许的请求都必须经过正确行权限规则”的保证。** 这条保证可以由 Cube 官方支持的 `query_rewrite` 在 Cube 进程内实现，无须额外权限 HTTP 服务。

[S1]: https://docs.cube.dev/reference/data-modeling/view
[S2]: https://docs.cube.dev/docs/data-modeling/access-control/member-level-security
[S3]: https://docs.cube.dev/reference/configuration/config#query_rewrite
[S4]: https://github.com/cube-js/cube/issues/6652
[S5]: https://github.com/cube-js/cube/pull/10590
[S6]: https://github.com/cube-js/cube/issues/10601
[S7]: https://github.com/cube-js/cube/blob/v1.7.1/packages/cubejs-schema-compiler/src/compiler/CubeEvaluator.ts
[S8]: https://github.com/cube-js/cube/blob/v1.7.1/packages/cubejs-api-gateway/src/gateway.ts
[S9]: https://github.com/cube-js/cube/blob/v1.7.1/packages/cubejs-server-core/src/core/CompilerApi.ts
