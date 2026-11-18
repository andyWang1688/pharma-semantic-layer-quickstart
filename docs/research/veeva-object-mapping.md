# Veeva 官方对象与本例仓库表

核查日期：2026-11-17。本例参考 Veeva Align 的官方关系对象，使用简化仓库表承接，不模拟完整 Veeva API 或复制其 DDL。

## 1. 哪一套 Veeva 模型

Veeva China CRM Suite、Salesforce 平台的 Veeva CRM、Vault CRM、Veeva Align 是不同产品。Veeva 将 China CRM Suite 定义为面向中国市场独立构建的产品，不能把其中一个产品的对象名称当作所有 Veeva 产品的统一标准。[China CRM Suite](https://www.veeva.com/cn/product/veeva-china-crm-suite-en/)

本例用岗位、岗位与医院的关系、岗位与产品的关系表达辖区覆盖。接入源系统时，应按对应产品的对象字典核对字段。

Align 官方直接提供人员、辖区、客户、产品和分配对象，因此采用它说明关系。以下“示例表”是本例设计，不是 Veeva 官方表名或字段名。[Align Objects](https://alignhelp.veeva.com/doc/Content/Align/Components/AlignObjects.htm)

| Align 官方对象 | 官方职责 | 示例表 |
|---|---|---|
| `territory__aln` | 辖区及层级、生命周期 | `raw.positions` |
| `roster_member__aln` | 可被分配到辖区的人员 | `raw.employees` |
| `account__aln` | 客户，包含 HCP/HCO | `marts.mart_hospital_dimension`，仅演示医院 |
| `product__aln` | 产品 | `marts.mart_product_dimension` |
| `roster_member_territory__aln` | 人员与辖区分配 | `raw.employee_positions` |
| `account_territory__aln` | 客户与辖区分配 | `raw.position_account_histories` |
| `territory_product__aln` | 辖区与产品分配 | `raw.position_product_histories` |

`app.access_grants` 是本例的当前授权契约，没有对应的 Veeva 官方对象。登录状态、历史查询能力也属于本例身份与授权设计。Territory 是否等于客户说的“岗位”，需要客户确认，不能仅凭名称认定。

## 2. Salesforce CRM 不能丢失辖区配对

官方集成映射包括 `territory__aln → Territory2`、`account_territory__aln → ObjectTerritory2Association`；人员辖区分配对应 `UserTerritory2Association`。[Align-CRM Integration](https://alignhelp.veeva.com/doc/Content/Align/Features/AlignCRMIntegration.htm)、[End-dating impact](https://support.veeva.com/hc/en-us/articles/360011216894-What-Is-the-Impact-in-Veeva-Align-and-Veeva-CRM-if-a-Territory-is-End-Dated-in-Veeva-Align)

`My_Setup_Products_vod__c` 是人员产品并集，不保留 Territory 关联。Align 会合并人员全部辖区的不同产品再推送到 CRM；因此不能用这张表反推每个辖区的 H+P 权限。[My Setup Products](https://alignhelp.veeva.com/doc/Content/Align/Features/MySetupProducts.htm)

本例在同一 `snapshot_code + position_code` 下连接客户与产品关系，再对结果去重。例如 T1 只覆盖 H1/P1，T2 只覆盖 H2/P2，兼任者得到两个配对，不会获得 H1/P2。这是保留分配关系的用途。

同辖区“医院集合 × 产品集合”仍是本例业务假设。若产品资格因医院而异，应使用明确的辖区/H/P覆盖关系，不能沿用这个乘积。CRM 的 TSF `Allowed_Products_vod` 用于客户和辖区上的产品讲解、样品等业务限制，是否用于销售 BI 权限应另行定义。[Working with Territory Fields](https://crmhelp.veeva.com/doc/Content/CRM_topics/Accounts/AcctsDefaultFunc/WorkingwithTerritoryFields.htm)

## 3. 历史关系和销售事实

官方用户辖区分配有 `start_date__aln/end_date__aln`；客户分配也有 Start Date、End Date。产品分配有生命周期，不能将产品本体与分配关系的有效期混为一谈。Align 产品文档明确产品本体不使用 Start/End Date。[Align-CRM Integration](https://alignhelp.veeva.com/doc/Content/Align/Features/AlignCRMIntegration.htm)、[Account Assignment](https://alignhelp.veeva.com/doc/Content/Align/Features/AccountAssignment.htm)、[Product](https://alignhelp.veeva.com/doc/Content/Align/Features/Product.htm)

本例将这些历史关系简化为月快照 `snapshot_code`，没有实现完整有效期模型。正式接入应保留源 ID、来源系统、关系生效时间和失效时间；结束有效期后 CRM 分配可能删除，仅采集当前 CRM 关系不足以恢复历史。[End-dating impact](https://support.veeva.com/hc/en-us/articles/360011216894-What-Is-the-Impact-in-Veeva-Align-and-Veeva-CRM-if-a-Territory-is-End-Dated-in-Veeva-Align)

`marts.mart_sales_fact` 是合成外部销售事实，不冒充 Veeva 交易源。Veeva Fixed Reports 官方说明销售数据进入独立 repository，`Sales_Transaction_vod` 只作为引用对象，数据不会加载到该对象。[Loading Data Map Templates](https://crmhelp.veeva.com/doc/Content/CRM_topics/FixedReports/InitConfig/LoadingSalesData/DataMapTemplates.htm)

`product__aln` 不保证是销售包装 SKU。CRM 产品与销售产品组另有映射，本例假设 P1 等编码已经对齐；正式接入必须确认事实、授权使用的产品层级和映射。[Product](https://alignhelp.veeva.com/doc/Content/Align/Features/Product.htm)、[Loading Product Data](https://crmhelp.veeva.com/doc/Content/CRM_topics/FixedReports/InitConfig/LoadingSalesData/AnalyticsProdGrps.htm)

## 4. Review 时如何判断

关系对象和时间概念有 Veeva 官方依据；事实不复制、共享范围取并集来自本次已确认的业务口径；月份/H/P键、当前授权表和三种架构模式是本例设计。Cube 执行机制及其官方来源见 [Cube 调研](official-cube-guidance.md)，实际取舍见 [架构决策](../architecture.md)。
