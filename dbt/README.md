# dbt 模型导航

在demo根目录执行 sh run.sh build。源码只读挂载，构建和日志位于容器/tmp/dbt，退出后自动删除。

## 1. 分层

~~~text
raw业务源8张 → staging8个 → intermediate6个 → marts6个 → Cube
app.users / app.access_grants → Cube每次请求实时读取
~~~

每张raw只有一个staging入口；staging保持来源粒度，规范字段和类型。intermediate进行去重、组合和组织递归；marts用明确列清单发布稳定实体。staging 和 intermediate 使用视图，6 张 Mart 物化为表并 ANALYZE，查询索引在 dbt 模型 config 声明；三个层级通过docs.node_color区分，两个exposure记录Cube消费出口。

业务人员来自raw.employees，岗位来自raw.positions，任职来自raw.employee_positions。岗位医院/产品覆盖、交易、医院、产品分别保持独立来源。app不进入dbt血缘。

## 2. 销售星型模型

[mart_sales_fact](models/marts/mart_sales_fact.sql) 保持销售交易粒度，通过 hospital_code、product_code 分别关联唯一的 [医院维度](models/marts/mart_hospital_dimension.sql) 和 [产品维度](models/marts/mart_product_dimension.sql)。sales_date 提供时间分析。Cube 基于这三个实体定义指标、维度关联、业务 View 和月度预聚合。

人员任职、岗位树和岗位 H+P 作为配套关系模型，负责组织导航、历史归属与访问范围；各表粒度见[架构](../docs/architecture.md)。

## 3. 组织关系模型

1. [int_position_tree.sql](models/intermediate/int_position_tree.sql)：同版祖先/后代展开；depth=0自身、1直属。名称、直接上级、版本有效区间和当前标记一并输出。
2. [int_employee_positions.sql](models/intermediate/int_employee_positions.sql)：人员任职关联人员主档和同版自身岗位名称；上级岗位保留在岗位树。支持同岗多人、一人多岗和离职历史。
3. [int_position_hp.sql](models/intermediate/int_position_hp.sql)：同版本同岗组合医院×产品，去重且无销售金额。

其余三个intermediate模型是销售、医院、产品。marts对应发布6个实体。Sales消费事实和医院产品维度；Organization关联岗位树和带人员属性的任职表，工具由这个统一View查询目录与上下级。

## 4. 版本与授权

树中的版本从岗位源snapshot_code去重得到；valid_from为月初，valid_to为下一版月初，最后版为空。上版持续生效到新版开始，是本例业务规则。organization_as_of固定2026-11-17，当前只选择最近已生效版；推进日期需构建。

请求按current/as_of/period选择树中的版本。人员范围、领导和目录由树＋任职直接查询，授权根岗位来自app.access_grants。账号停用/撤权无需dbt重建；组织与任职变更需构建，销售变更还需Cube聚合刷新。

## 5. 验证

20个模型、118项dbt数据测试，覆盖非空、唯一性、同版引用、组织环路、版本区间和事实保全。根目录sh run.sh test覆盖18个销售场景、组织关系、未来版本、实时撤权、无账号人员、深层空岗和物理Rollup。

字段说明见[models/schema.yml](models/schema.yml)，源见[models/sources.yml](models/sources.yml)。
