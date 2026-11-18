# 适配自己的项目

保留数仓、语义模型和权限执行的职责，再按自己的系统替换来源和业务规则。

| 要调整的内容 | 入口 | 需要一同确认的契约 |
|---|---|---|
| 数据来源 | dbt/models/sources.yml、staging；本例来源由 db/init 初始化 | 来源粒度、业务编码、增量/历史方式；staging 保持来源行粒度 |
| 事实、维度与业务规则 | dbt/models/intermediate、marts、schema.yml | 交易唯一键、维度键唯一性、关联关系、金额和数量的口径 |
| 指标、维度与 View | cube/model/cubes、cube/model/views | YAML 关联、公开成员、时间粒度；Cube API 返回字段契约 |
| 企业身份与岗位权限 | cube/cube.py、cube/security/policy.py、app.users/access_grants | 可信登录工号、授权来源、根岗位语义、撤权时效和历史访问规则 |
| 查询入口与预聚合 | demo/tools.py、SalesFacts.yml 的 pre_aggregations | 筛选与权限分别表达；Rollup 必须包含实际筛选需要的成员 |

## 权限代码的位置

policy.py 集中业务决策：当前账号检查、三种架构口径、目录可见范围、完整分析对象范围和最终强制过滤。cube.py 是 Cube 的原生配置入口；database.py 提供请求内只读一致性事务。业务客户端只传分析意图，通过 Cube 查询数据。

app.access_grants 的每条根岗位授权覆盖其在各已生效版本中的整个子树。一人可以授权多个根岗位；岗位编码必须保持稳定。需要按版本、产品或有效期授权时，应调整授权契约和验证场景。

## 源数据与时间

当前样例使用完整月快照；岗位内医院集与产品集组合成覆盖。接入医院产品例外时，使用明确的岗位—医院—产品来源关系。销售产品与业务产品需要先确认编码和粒度对应关系。

历史姓名、日级任职、币种、退货和目标达成率均需要各自明确的数据来源与指标定义。新增主题时按其事实粒度建模，再复用适用的维度。

## 验证与运行

修改后先运行 sh run.sh check，再运行 sh run.sh test。源数据和 dbt 模型变化后运行 sh run.sh build；模型构建成功后 Cube 才恢复查询。Compose 和依赖变化后使用 sh run.sh up 更新镜像与服务。

本机模拟身份和公开凭据用于复现。实际部署需接企业认证、独立密钥与数据库账号，并按规模配置连接池、队列、刷新 worker 和发布流程。本例只启用已验收的 REST 查询入口；增加其他入口时验证相同身份和权限契约。

完整假设见[架构](architecture.md)，官方组件与业务规则的区别见[Cube 官方依据](research/official-cube-guidance.md)。


## PostgreSQL 规模与查询成本

销售事实和岗位覆盖可以在同一库内同时达到千万行。评估同一条授权销售查询时，记录查询月份数、该人员对应的下属岗位数、去重后的医院产品数、命中的交易数，以及并发请求数。总表行数无法直接推算响应时间。

常用团队月报继续按月、医院、产品共享预聚合；交易明细只保存一次。权限按有效组织版本从岗位子树查覆盖，先去重，再用于过滤。大量岗位同时覆盖相同的医院产品时，直接将交易 JOIN 到岗位会放大金额。切勿为了得到正确合计而使用 SUM(DISTINCT 销售额)。

本例使用 (版本, 岗位, 医院, 产品) 的唯一索引及事实的 (月份医院产品键, 销售日期) 索引。它们服务于选择性查询；覆盖大部分事实时，PG 选择顺序扫描也可能更省。若单次常态查询超过本例枚举上限，应在库内用半连接将授权集合与月度销售汇总匹配，验证完整对象授权、撤权生效和 Cube 的实际查询计划后再切换。普通 Cube REST 查询的 equals 过滤参数是值清单，SQL 子查询不能直接填入 values。

接入真实量级时，先选同一库中的代表、区域经理及全国负责人，用同一请求分别记录权限 SQL 与最终聚合 SQL 的 EXPLAIN (ANALYZE, BUFFERS)、Cube 是否命中、冷构建时间及并发 P95。若按月刷新成为瓶颈，依据销售更正、医院改名等实际变更确定要重建的月份并验证历史回补。全量换表切到增量后，刷新键也需切到成功发布的批次。此示例没有测得千万行联合负载的延迟或并发能力。

[Cube 预聚合匹配](https://docs.cube.dev/docs/pre-aggregations/matching-pre-aggregations) · [Cube 查询格式](https://docs.cube.dev/reference/core-data-apis/rest-api/query-format) · [PostgreSQL 执行计划](https://www.postgresql.org/docs/16/using-explain.html)
