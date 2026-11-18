# 示例工程约定

适用于医药行业 dbt + Cube 星型建模参考项目；客户项目的来源表和发布契约另行维护。

1. **建模契约**：实现 MUST 遵循 [模型与架构](../architecture.md)。销售事实 MUST 保持交易粒度，业务维度键 MUST 唯一，组织多对多关系 MUST 通过关系桥确定范围。当前授权根岗位 MUST 应用于各已生效版本。行为变更 MUST 同步更新该说明与真实查询验收。
2. **数据分层**：source() MUST 仅出现在 staging；关联、去重、闭包计算 MUST 放在 intermediate；Cube 模型 MUST 读取 Mart。Mart MUST 使用明确列清单。staging 与 intermediate 默认使用视图。Mart MUST 使用实体表并在构建后 ANALYZE，索引在 dbt 模型声明。验证：dbt build 与 test_data_quality.py。
3. **权限执行**：业务客户端 MUST 通过 Cube 获取人员和销售；query_rewrite MUST 使用可信身份、参数绑定和请求内一致性快照。输入错误、权限读取失败、对象范围不完整 MUST 拒绝查询。用户条件 MUST 整体 AND 强制权限。验证：test_policy.py、test_integration.py、test_dbt_refresh.py 和 test_cube_only.py。
4. **代码和接口**：Python MUST 通过固定版本 Ruff 检查与格式检查；主要业务入口 MUST 说明输入、返回和错误边界。模块 MUST 按实际职责组织，MUST NOT 为单一调用添加无行为的转发层。验证：sh run.sh check。
5. **示例证据**：Rollup 命中 MUST 同时核对仅预聚合执行、物理表和原始事实结果；容量达到上限 MUST 明确报错，MUST NOT 将截断结果标为完整。功能验证 MUST 与客户规模性能区分。验证：sh run.sh test。

依据：[dbt 分层](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview)、[Cube query_rewrite](https://docs.cube.dev/reference/configuration/config#query_rewrite)、[Cube 预聚合匹配](https://docs.cube.dev/docs/product/caching/matching-pre-aggregations)。本例的业务授权与历史算法属于自定义设计。
