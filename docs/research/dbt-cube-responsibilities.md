# dbt 与 Cube：星型模型、组织历史和权限的分工

核查日期：2026-11-17。本文保留方案研究依据。同日已按此分工重构独立 demo：Cube Core 1.7.1，dbt Core 1.9.10。当前实现与验证见 [架构](../architecture.md)；真实项目保持原状。

当前精简版为6张Mart：事实、医院、产品、带人员属性的任职、岗位树、岗位H+P；组织版本并入树，人员范围和领导由查询时关联取得。组织统一出口见[Organization View](../../cube/model/views/Organization.yml)。

## 1. 结论与官方依据

**推荐这个项目采用：dbt 建好事实、业务维度、历史关系与桥表；Cube 定义业务指标、View 和预聚合；Python query_rewrite 执行每次请求的权限过滤。**

以下区分官方能力与本项目的设计判断：

| 判断 | 依据 |
|---|---|
| 同一数据库内，不同用户的行权限可以使用 query_rewrite | Cube Multitenancy 明确给出 rule of thumb；配置参考说明该钩子每次请求执行 [1][2] |
| dbt 先建设数据集市，Cube 在其上增加维度、指标、关联、预聚合及 View | Cube 官方 Using Cube with dbt 的分层说明 [3] |
| 上下级展开、历史有效期组合、H+P 覆盖清洗放到 dbt | 结合上述分层与本例反复查库的实现作出的工程建议；官方没有规定医药专用算法 |
| 当前、固定版本、逐期历史这三种分析口径 | 本项目的业务定义；Cube 与 dbt 都需要按定义建模 |
| 当前 RLS 文档也提供声明式 Access Policies | 官方能力；本方案沿用用户已选择的 query_rewrite [4] |

官方 Multitenancy 原文：

> As a rule of thumb, the queryRewrite should be used in scenarios when you want to define row-level security within the same database for different users of such database.

官方 dbt 集成原文：

> Cube projects usually define cubes on top of dbt models, materialized as tables or views in your data warehouse ... enrich them with measures, joins, and pre-aggregations.

## 2. dbt 提前准备什么

下表使用概念模型名称；实现分别对应 mart_sales_fact、mart_employee_positions、mart_position_tree 和 mart_position_hp；岗位节点版本由树的depth=0行表达。组织版本采用完整月快照 snapshot_code，有效区间为左闭右开。

| dbt 输出 | 一行的含义 | 用途 |
|---|---|---|
| fct_sales | 一笔交易；交易主键唯一 | 保存销售额和销量，供业务维度分析 |
| dim_position_history | 一个岗位的一份组织版本 / 有效区间 | 保存上级关系与组织历史 |
| bridge_employee_position | 一个人在一个岗位的任职版本 / 有效区间 | 回答某个时间张三在哪个岗 |
| bridge_position_tree | 同一组织版本中，一对祖先岗、后代岗；包含自己 | dbt 展开层级，查询时直接筛后代 |
| bridge_position_hp | 同一版本、岗位、医院、产品的唯一覆盖关系 | dbt 在同岗内组合 H+P，再去重 |

全部业务来源从 raw 进入 staging，人员主档 raw.employees 与应用账号 app.users 分开。app 仅保存在线身份与授权，不作为 dbt 的 source。医院、产品主维度沿用普通星型模型。bridge_position_hp 中保存关系键，销售金额保留在 fct_sales。祖先展开也可与覆盖合成加速表，是否物化要根据关系数量评估。优先复用岗位覆盖，避免一开始就全量展开为所有员工 × 所有销售月份 × H+P。

Kimball 的多值维度桥表方法明确要求：多对多关系随时间变化时，桥表保存生效/失效时间，查询约束到一致的时间点 [11]。这是历史关系建模的经典依据。

使用有效期时，每条派生关系的有效区间取其所有来源关系有效区间的交集：起点取最大值，终点取最小值，只保留非空交集。组织路径上的每条上下级关系也必须同时有效。该规则属于本业务的时间关联设计。

### 历史数据如何产生

源系统已提供 from/to、生效版本或完整历史时，dbt 清洗并保留这些历史。dbt 官方说明，此类源数据可能直接使用 incremental append/merge，无需额外 snapshot [5]。

源系统只覆盖更新当前行时，dbt snapshots 可以保存 SCD2 历史；可靠 updated_at 适用官方推荐的 timestamp strategy [5][6]。Snapshot 记录定期运行时捕获到的变化。运行间隔内已被覆盖的中间版本，需要源端历史或 CDC 才能完整保留。医药系统的业务生效日期也要单独保留，按业务日期分析时使用该字段定义的有效区间。

dbt 检查应覆盖唯一键、关系引用、无效/重叠有效期、单节点多当前版本、组织环路，以及同岗 H+P 去重。源端独立医院集 × 产品集的组合需要客户确认；若覆盖带医院产品特例，直接使用显式三元关系。

## 3. Cube 每个请求执行什么

```text
可信登录身份 + 分析对象 + 销售期间 + 架构口径
  → 检查当前账号与当前授权
  → 按口径选择 dbt 已准备的组织关系
  → 查询对象范围取并集，按当前授权校验
  → 得到唯一的 (销售期间, 医院, 产品) 范围
  → query_rewrite 强制 AND 到标准 Cube 查询
  → Cube 匹配共享 Rollup 并计算结果
```

建议 query_rewrite 保留小量输入验证、范围查询和强制过滤。组织递归、跨表清洗和完整历史构造由 dbt 处理。可将并集、交集和去重也写入 dbt 管理的 SQL View；Cube 直接按可信身份和请求条件查询这个 View。

dbt run/build 在任务执行时创建数据库的表或 View [7]。表中的结果按构建周期更新；View 中的 SQL 在访问数据库时执行。人员与口径由查询条件传入已建好的关系，业务请求无需启动一次 dbt job。dbt 负责部署关系，Cube 负责把登录身份变成不可绕过的过滤条件。

当前账号停用、授权撤销的生效速度取决于读取的数据源及缓存策略。要求立即生效时，在请求中检查在线账号/授权状态；若使用 dbt 物化权限表，则必须接受并明确其刷新时延。

三种口径都可以复用同一套历史关系：

| 请求口径 | 选用关系 | 销售期间 |
|---|---|---|
| current | 当前完整组织版本 | 用户选择的全部期间 |
| as_of | 用户指定的同一个组织版本 | 用户选择的全部期间 |
| period | 每个销售期间分别取对应组织版本 | 每期范围只作用于该期销售 |

current 选择当前已生效且导入完整的版本；本例已由 dbt 的 mart_position_tree 按 organization_as_of 标记。组织与覆盖来源须在同一事务中完整导入，随后执行 dbt 构建。

如果组织按日变化，且需按交易发生时的关系逐笔判定，过滤与预聚合时间粒度也应支持该业务精度。

当前 demo 的月份/H/P JSON 键是过滤表达的一种自定义实现。先查询范围、再附加标准维度过滤属于本例方案；Cube 官方没有要求必须使用这个键。

## 4. 多对多关系与预聚合

共享业绩采用集合语义：选择张三、李四或其领导时，相同 H+P 在同一销售期间只进入一次范围；每笔真实销售仍按交易主键保留。两个不同交易金额恰好相同也分别计入。按人员显示的每行可共享业绩，跨行总计重新按覆盖并集计算。

建议继续采用不含员工和组织版本的共享销售 Rollup，基础粒度为销售月 × 医院 × 产品，包含强制过滤所需的配对键及常用展示维度。日级访问、月中变更的逐笔归属、渠道等额外过滤需要更细粒度或额外成员。

Cube 官方匹配规则检查查询维度、过滤维度和指标，View 成员会映射到原 cube 成员 [8]。因此该建议的前提是权限最终表达为 Rollup 已覆盖的成员；任意关联权限桥表后能否继续使用原 Rollup，需要检查实际 SQL 和匹配结果。星型模型能使用预聚合，覆盖成员、时间粒度和多对多关系共同影响匹配。

大范围 H+P 清单会增加权限查询、Python 序列化、SQL 参数和过滤成本。先按目标客户的数据规模测试。规模超出预算时，评估数据库端 EXISTS/半连接方案；dbt 可以提前建设月/H/P 销售汇总表供其查询。此时需重新验证 Cube Rollup 的匹配与结果，不能宣称改成 EXISTS 后仍自动共享现有 Rollup。

rollup_join 官方定位是跨数据源连接两个 Rollup，当前文档标记 Preview，不能作为任意权限桥表连接的默认解法 [9]。大量 FILTER_PARAMS 的动态 SQL 也应谨慎：Cube 官方建议将其主要用于谓词下推优化，并把过重的转换上移 [10]。

dbt 与 Cube 的刷新职责可以分开：dbt 更新事实和关系；编排器在成功后触发 Cube 预聚合刷新。Cube 官方 dbt recipe 给出了这一集成建议 [3]。组织变化只改变请求过滤时，共享销售 Rollup 无需按每个用户和组织版本重建。

## 5. 与现有 demo 的对应及下一步

原 territory_scope、hospital_products_for_territories 的组织递归与医院产品组合，已迁入 dbt intermediate 模型。policy.py 按版本批量读取 Mart，并完成可信身份检查、范围校验及强制 AND；人员任职与领导详情通过统一Organization View查询，工具适配位于demo/tools.py；JS cubes/views 继续描述指标和关联。

迁移已验证共享 H1/P1 为 100/100/100；两人全量与经理并集合计为 130/150/180；张三一至二月 current/as_of/period 为 290/330/310。另测同JWT实时撤权/停用、历史越权、未来版本与dbt刷新边界。月中日级归属与客户规模性能仍在本例验证范围之外。

实际 GitHub 示例、代码路径和适用边界见同目录 cube-dbt-reference-demos.md。完整医药业务仍需基于这些官方组件开发和验收。

## 来源

[1] [Cube Multitenancy](https://docs.cube.dev/embedding/multitenancy) — queryRewrite rule of thumb 与共享资源。

[2] [Cube configuration: query_rewrite](https://docs.cube.dev/reference/configuration/config#query_rewrite) — 每次请求的安全钩子。

[3] [Using Cube with dbt](https://docs.cube.dev/recipes/data-modeling/dbt) — 数据集市分层、元数据与刷新编排。

[4] [Cube Row-level security](https://docs.cube.dev/docs/data-modeling/access-control/row-level-security) — Access Policies。

[5] [dbt: Choosing incremental models or snapshots](https://docs.getdbt.com/best-practices/how-we-handle-cdc/2-choosing-incremental-or-snapshots) — 已有历史、snapshot 条件及捕获局限。

[6] [dbt snapshots](https://docs.getdbt.com/docs/build/snapshots) — SCD2、timestamp/check 与有效期字段。

[7] [dbt SQL models](https://docs.getdbt.com/docs/build/sql-models) — 通过 run 在仓库中创建表或 View。

[8] [Cube: Matching queries with pre-aggregations](https://docs.cube.dev/docs/pre-aggregations/matching-pre-aggregations) — 成员与过滤维度匹配。

[9] [Cube: rollup_join](https://docs.cube.dev/reference/data-modeling/pre-aggregations#rollup_join) — 定位、预览状态和限制。

[10] [Cube: FILTER_PARAMS](https://docs.cube.dev/reference/data-modeling/context-variables#filter_params) — 使用边界与上移转换建议。

[11] [Kimball: Multivalued Dimensions and Bridge Tables](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/multivalued-dimension-bridge-table/) — 多对多历史桥表与有效时间约束。
