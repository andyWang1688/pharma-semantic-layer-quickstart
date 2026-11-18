# Review 指南

本项目是医药行业 dbt + Cube 语义层 Quickstart。重点检查粒度、关联、权限执行与可运行性。

1. **星型模型**：[销售事实](../dbt/models/marts/mart_sales_fact.sql)、[医院维度](../dbt/models/marts/mart_hospital_dimension.sql)、[产品维度](../dbt/models/marts/mart_product_dimension.sql)。核对交易粒度、唯一维度键和业务字段，模型关系见[架构](architecture.md)。
2. **组织关系**：[岗位树](../dbt/models/intermediate/int_position_tree.sql)、[任职](../dbt/models/intermediate/int_employee_positions.sql)、[岗位医院产品关系](../dbt/models/intermediate/int_position_hp.sql)。核对版本、上下级、任职和覆盖粒度。
3. **Cube 语义模型**：[SalesFacts.yml](../cube/model/cubes/SalesFacts.yml)、[Sales.yml](../cube/model/views/Sales.yml)、[Organization.yml](../cube/model/views/Organization.yml)。核对指标、维度关联、公开成员、时间粒度和预聚合。
4. **权限核心**：[policy.py](../cube/security/policy.py)。账号→架构版本→对象范围→数据库 EXISTS 校验当前岗位授权→唯一(月,H,P)→强制 AND。[cube.py](../cube/cube.py)注册钩子，[database.py](../cube/security/database.py)管理事务和连接；上级路径可见与销售授权分别校验。
5. **使用与验收**：[tools.py](../demo/tools.py)通过 Cube 查询人员及销售；[请求链路](request-walkthrough.md)和[REST 示例](examples.md)说明如何调用。sh run.sh check 做代码检查；sh run.sh test 验证 dbt、权限、历史架构、数据质量和预聚合。

改造入口见[适配说明](customization.md)，代码规则见[示例工程约定](standards/example.md)。当前包含 6 张 Mart，app 只保存账号与当前授权；测试页面用于操作和查看诊断证据。
