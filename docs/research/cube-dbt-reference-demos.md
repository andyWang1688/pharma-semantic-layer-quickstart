# 可评审的 GitHub 参考：Cube、dbt、动态权限与组织历史

核查日期：2026-11-17。本报告实际读取官方/维护方仓库的源码与测试，不只依据仓库介绍。未运行这些外部示例，也未修改本地应用代码。

## 1. 结论

**有标准组件和官方示例可参考；本次没有找到一个同时实现“人员消歧 + 当前/历史组织 + 共享 H+P 权限 + 领导汇总去重 + 预聚合”的官方完整 demo。** 应逐项采用有来源的做法，再对本项目业务规则做测试，不能把供应商过滤订单的小例子称为完整医药方案。

官方明确支持在 `queryRewrite` 运行时查数据库/API 获取用户当前部门；这是一种受支持的扩展方式。官方并没有要求必须在每次 query rewrite 中递归计算完整组织树、重建历史和传递大量 H+P 列表。既然已经采用 dbt，可以在 dbt 先产出可复用的历史归属、组织关系和去重后的权限桥，Cube 保留登录者鉴权、不可绕过的行过滤、指标、View 与预聚合。

以下参考按可直接评审的价值排序：

| 参考 | 来源性质 | 实际覆盖 | 不覆盖 |
| --- | --- | --- | --- |
| [Cube + dbt recipe][S1] 与 [`cube_dbt` Python 实现][S2] | 官方文档代码、官方开源包 | dbt marts → Cube；manifest读取、模型选择、维度映射；在Cube补 measures/joins/rollups | 不生成完整动态授权；不把snapshot节点自动当普通model加载 |
| [column-based-access][S3]、[role-based-access][S6] | 官方小型源码示例 | securityContext → queryRewrite → 强制过滤；通过关联Cube的字段限制事实 | 不实现组织树、历史归属、共享事实去重；安全检查较简化 |
| [Many-to-many joins][S8] | 官方文档里的模型代码 | bridge / associative cube、定向join、View的join_path | 不实现权限求并集、不证明任意bridge查询都能命中rollup |
| [Fivetran Workday组织历史模型][S9] | Fivetran维护的dbt开源包，非Cube官方 | 员工—岗位—组织历史、日期展开、生效区间join、日级历史输出 | 不含Cube授权、医院产品、医药指标与领导业绩去重 |
| [Cube snapshots recipe][S13] | 官方较早源码示例 | 状态变化生成日期快照的SQL思路 | 不等于dbt SCD2；不含组织历史授权；不建议直接复刻作为本例方案 |

## 2. Cube + dbt：官方做法与实际Python代码

### 官方推荐的分工

已读取固定到Cube `v1.7.1` commit `1b202da2bfd06f2efcc0ff08289ba8f90a15d648` 的 [Using Cube with dbt][S1]。它明确描述：

> dbt项目创建staging、intermediate，最后建立normalized data marts；Cube在已物化的dbt表或视图上建cubes，补充dimensions、measures、joins、pre-aggregations，再通过views向下游暴露。

同一文档有完整的 `globals.py` / Jinja片段，以及一个 `orders` cube的补充定义：在dbt生成的维度之外增加measures、`many_to_one` join和包含用户维度的pre-aggregation。它建议每个dbt model单独一个Cube模型文件，便于维护。

这段文档比“把所有逻辑塞进hook”更接近本项目应采用的基础分工，但并没有规定组织历史授权的完整表结构。

### 实际读取的官方仓库

仓库：[`cube-js/cube_dbt`][S2]。本次固定commit为 `1a20e64fe35a2aa01cf9126902c7a2148b4d96ac`；`pyproject.toml` 声明版本 `0.6.3`、MIT许可证。

| 文件 | 已读到的具体代码 | 对本例的意义 |
| --- | --- | --- |
| [`src/cube_dbt/dbt.py`][S2] | `from_file`、`from_url`；`filter(paths/tags/names)`；`_init_models` 仅接收 `resource_type == 'model'` 且排除 `ephemeral` | 读取的是构建产物的元数据，不代替dbt执行转换，也不根据当前登录者计算权限 |
| [`src/cube_dbt/model.py`][S14] | `sql_table` 读取manifest的relation_name；`as_cube()` / `as_dimensions()` 输出YAML；识别constraints、tags/tests中的主键信息 | 可以复用表名、列说明和类型；仍需明确定义业务指标、join与权限 |
| [`tests/test_dbt.py`][S15] | `test_load_only_models` 明确验证snapshot节点被忽略；其余测试覆盖ephemeral排除及path/tag/name筛选 | dbt snapshot后应再建普通mart model供Cube读取，不能假定快照节点自动成为Cube模型 |

这里的 `cube_dbt` 是官方Python/YAML/Jinja集成包。Cube 模型也可直接以 `sql_table` 或 `sql` 指向dbt已构建的mart表/视图。本 demo 当前使用直接维护的YAML模型和Python配置，Cube读取YAML时无需额外的模板生成过程。

较早的 `@cubejs-backend/dbt-schema-extension` 不应当作当前首选。官方维护者在 [PR #5746][S16] 中于2023-05-09明确表示该集成因dbt方向变化而弃用；它与当前Python `cube_dbt` 不是同一个包。

## 3. 动态RLS：有官方示例，也有直接针对“当前部门”的维护者答复

### 关联关系过滤：最贴近“先确定归属，再过滤事实”的小例子

固定源码commit：`e1f78d4c635d485eec8d22d4c4946f26f26faac1`。

| 文件 | 实际行为 |
| --- | --- |
| [`examples/recipes/column-based-access/cube.js`][S3] | 读取 `securityContext.email`，向query追加 `Suppliers.email equals [...]` 过滤 |
| [`schema/Products.js`][S4] | Products通过 `supplier_id = Suppliers.id` 关联Suppliers |
| [`schema/Suppliers.js`][S5] | 定义供应商id主键和email维度 |

关键代码是：

```javascript
query.filters.push({
  member: `Suppliers.email`,
  operator: 'equals',
  values: [securityContext.email],
});
```

它证明权限过滤可以落在关联维度上，让Cube生成join和事实查询。**它没有证明多对多权限桥与H+P事实join后，任意分组和任意rollup都自动正确、自动命中。**

这个文件的最后修改提交是 [`49ead61`（2022-11-21）][S17]；模型仍使用 `belongsTo`、`primaryKey` 等旧写法。它适合验证机制，不宜把全部实现原样当作当前生产规范。静态检查还可看到它只检查选中的measures/dimensions，没有遍历filters/order；本项目应保证所有可用入口都经过正确的权限规则。

另一组实际源码 [`examples/recipes/role-based-access/cube.js`][S6] 依据JWT里的manager/operator角色追加Orders.status过滤，配套 [`schema/Orders.js`][S7]。这同样是机制教学示例：未知非空role并不会在该文件中被显式拒绝，因此不能把它当作完整的默认拒绝授权实现。

### 运行时查“当前部门”是否官方认可

[Issue #6488的维护者完整答复][S18] 正面回答了与本项目接近的问题：用户不想在token里固定部门，希望在queryRewrite执行时查询数据库或后端API，取得用户当时有效部门。

维护者Igor Lukanin于2023-12-01回答：

> You can certainly do that. Depending on the data modeling language you use, you can just use the `requests` modeule in Python or the `fetch` function in JavaScript.

同一回复还反驳了“部门join用户会阻止预聚合”的笼统前提：

> You can definitely have measures and dimensions from different cubes in a single pre-aggregation.

**语境边界：**这说明单个pre-aggregation可以包含多个Cube的measures/dimensions，不是承诺把任意权限桥加进查询后，原来的rollup无需修改也能命中。该issue没有提供组织闭包、历史区间、多对多H+P去重或规模测试的完整实现。

因此，这个来源支持“可在hook查实时归属”，不能用它证明“每次请求重算整棵历史组织树是最佳实践”。

## 4. Bridge与组织历史：两份可分别复用的代码参考

### Cube官方bridge模型

已读取固定commit下的 [`docs-mintlify/docs/data-modeling/joins.mdx`，127—237行][S8]。官方用 `posts → post_topics → topics` 示范：

```text
posts --one_to_many--> post_topics --many_to_one--> topics
```

然后通过View的 `join_path: posts.post_topics.topics` 暴露topic名称。它覆盖了关联Cube与定向join的建模方法，可类比事实与权限关系桥；但**角色/辖区范围是访问集合时，应先确定允许事实的集合，再对事实求和**。这是本例“共享H+P只算一次”的业务约束，不能直接由“把topic替换成辖区”推导所有汇总结果。

这是文档中可阅读的模型代码片段，不是带人员鉴权、dbt流水线和验收数据的完整运行项目。

### Fivetran Workday：把员工—岗位—组织历史计算放到dbt

仓库：`fivetran/dbt_workday`；已固定commit `84f33cbe9f4756deabd40c31cb49742409836673`。该commit的 `dbt_project.yml` 声明包版本 `1.0.3`，要求dbt `>=1.3.0, <3.0.0`。这是Fivetran维护的Workday HCM转换包，非Cube官方集成示例。

| 实际源码 | 读取到的处理 | 可借鉴范围 |
| --- | --- | --- |
| [`models/workday_history/staging/stg_workday__worker_position_organization_history.sql`][S10] | 生成包含worker、position、organization、source、历史起点的surrogate key，保留 `_fivetran_start/_fivetran_end` | 把归属关系和有效区间标准化成可测试的仓库模型 |
| [`models/workday_history/workday__worker_position_org_daily_history.sql`][S9] | 日期spine；window row_number；选择日级记录；按start/end区间join日期；输出worker_id/position_id/organization_id/date_day | 将历史归属计算提前到dbt，使查询端消费已定义粒度的关系表 |
| [`models/workday__organization_overview.sql`][S11] | 合并组织、组织角色、员工岗位关系，保留superior_organization_id、top_level_organization_id、manager_id | 参考当前组织关系与人员岗位维度的准备工作 |
| [`integration_tests/packages.yml`][S12] 与 `integration_tests/seeds/*history_data.csv` | 本地引用包，仓库附有worker、worker_position、worker_position_organization历史种子数据 | 有可进一步运行的测试工程，当前任务只做源码读取 |

适用限制：它依赖Fivetran Workday历史源字段，默认需要打开 `employee_history_enabled`；组织overview本身不是历史层级闭包。其日级窗口、键和时间边界是该包的具体选择，不应未经业务核对直接作为Veeva岗位历史的规则。它没有医院、产品、Cube queryRewrite或销售事实，不能称为本项目的现成完整方案。

## 5. 不建议直接照搬的旧snapshot recipe

已读取 [`examples/recipes/snapshots/schema/StatusSnapshots.js`][S13] 以及其父模型 `Statuses.js`；最后修改提交为 [`29f071b`（2021-08-26）][S19]。它用 `GENERATE_SERIES` 展开日期，再关联状态变化。

这份示例不是dbt snapshots，也不是组织历史授权。静态阅读可见其 `MAX(changed_at)` 子查询未限定到当前 `range.date`，若把它当成“每个历史日期截至当天的最新状态”，必须先补充明确的时间口径和对账测试。这里未运行该旧示例，不宣称已验证其历史结果正确。

对本项目更值得采用的参考组合是：**官方dbt recipe的分层 + dbt组织历史模型 + 官方Cube bridge/View建模 + query_rewrite强制授权**。dbt产出的表具体有哪些键、当前授权能否查看过去、历史架构使用哪一个as-of时间、共享H+P如何求并集，仍是本项目需要明确并测试的业务定义。相关职责划分见同目录 `dbt-cube-responsibilities.md`。

## 核验与未覆盖范围

本次通过GitHub API读取固定commit的文件内容及相关测试，同时读取官方文档和维护者完整答复。没有克隆外部仓库，没有安装其依赖，没有执行其Docker或dbt工程。未发现完整医药demo的结论仅限本次检索的官方Cube仓库、官方Python集成包、相关GitHub issue和上述dbt包，不能解释为断言社区不存在其他实现。

[S1]: https://github.com/cube-js/cube/blob/1b202da2bfd06f2efcc0ff08289ba8f90a15d648/docs-mintlify/recipes/data-modeling/dbt.mdx
[S2]: https://github.com/cube-js/cube_dbt/blob/1a20e64fe35a2aa01cf9126902c7a2148b4d96ac/src/cube_dbt/dbt.py
[S3]: https://github.com/cube-js/cube/blob/e1f78d4c635d485eec8d22d4c4946f26f26faac1/examples/recipes/column-based-access/cube.js
[S4]: https://github.com/cube-js/cube/blob/e1f78d4c635d485eec8d22d4c4946f26f26faac1/examples/recipes/column-based-access/schema/Products.js
[S5]: https://github.com/cube-js/cube/blob/e1f78d4c635d485eec8d22d4c4946f26f26faac1/examples/recipes/column-based-access/schema/Suppliers.js
[S6]: https://github.com/cube-js/cube/blob/e1f78d4c635d485eec8d22d4c4946f26f26faac1/examples/recipes/role-based-access/cube.js
[S7]: https://github.com/cube-js/cube/blob/e1f78d4c635d485eec8d22d4c4946f26f26faac1/examples/recipes/role-based-access/schema/Orders.js
[S8]: https://github.com/cube-js/cube/blob/e1f78d4c635d485eec8d22d4c4946f26f26faac1/docs-mintlify/docs/data-modeling/joins.mdx#L127-L237
[S9]: https://github.com/fivetran/dbt_workday/blob/84f33cbe9f4756deabd40c31cb49742409836673/models/workday_history/workday__worker_position_org_daily_history.sql
[S10]: https://github.com/fivetran/dbt_workday/blob/84f33cbe9f4756deabd40c31cb49742409836673/models/workday_history/staging/stg_workday__worker_position_organization_history.sql
[S11]: https://github.com/fivetran/dbt_workday/blob/84f33cbe9f4756deabd40c31cb49742409836673/models/workday__organization_overview.sql
[S12]: https://github.com/fivetran/dbt_workday/blob/84f33cbe9f4756deabd40c31cb49742409836673/integration_tests/packages.yml
[S13]: https://github.com/cube-js/cube/blob/e1f78d4c635d485eec8d22d4c4946f26f26faac1/examples/recipes/snapshots/schema/StatusSnapshots.js
[S14]: https://github.com/cube-js/cube_dbt/blob/1a20e64fe35a2aa01cf9126902c7a2148b4d96ac/src/cube_dbt/model.py
[S15]: https://github.com/cube-js/cube_dbt/blob/1a20e64fe35a2aa01cf9126902c7a2148b4d96ac/tests/test_dbt.py
[S16]: https://github.com/cube-js/cube/pull/5746
[S17]: https://github.com/cube-js/cube/commit/49ead61be49491efc11ded6d29bbecddaeebe332
[S18]: https://github.com/cube-js/cube/issues/6488#issuecomment-1836066085
[S19]: https://github.com/cube-js/cube/commit/29f071bd2351ac8c6734b6342d8856a5d9434754
