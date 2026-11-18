# 医药行业星型模型与系统架构

本项目采用标准维度建模方法，以医药销售主题为起点。dbt 产出事实、维度与业务关系，Cube 提供语义查询。固定 Cube Core 1.7.1，组织关系使用完整月快照。

## 销售星型模型

~~~mermaid
flowchart LR
  Hospital[医院维度<br/>mart_hospital_dimension] -->|hospital_code 一对多| Fact[销售事实<br/>mart_sales_fact<br/>一笔交易]
  Product[产品维度<br/>mart_product_dimension] -->|product_code 一对多| Fact
  Employee[人员任职<br/>mart_employee_positions] -->|同版任职岗位| Tree[版本化岗位树<br/>mart_position_tree]
  Tree -->|同版下属岗位| Bridge[岗位医院产品桥<br/>mart_position_hp]
  Bridge -.->|确定事实查询范围| Fact
  Fact --> Sales[Sales View<br/>指标与时间分析]
~~~

事实与医院、产品维度通过业务键形成星型关系。sales_date 是事实的时间维度，Cube 定义其时间粒度与预聚合。金额和销量始终保留交易粒度，维度键在主档中唯一。

人员任职、岗位树和岗位 H+P 是组织关系与桥接模型。它们用于人员识别、层级导航和确定访问范围；Cube 的销售查询通过事实键过滤范围，避免多对多关系复制事实行。Organization View 发布人员与岗位关系，Sales View 发布事实与业务维度。

## 分层与运行职责

~~~mermaid
flowchart LR
  Raw[raw 业务源 8 张] --> Stg[staging 8 个]
  Stg --> Int[intermediate 6 个]
  Int --> Mart[marts 6 个]
  Mart --> Models[YAML Cube 与业务 View]
  Client[数字员工工具或 REST 客户端] --> Hook[Cube 验签与 Python query_rewrite]
  Grants[app 当前账号与授权] --> Hook
  Hook --> Models
  Models --> Result[事实或预聚合]
~~~

| Mart | 一行的含义 |
|---|---|
| mart_sales_fact | 一笔真实销售，sales_id 唯一 |
| mart_hospital_dimension / mart_product_dimension | 一个医院 / 一个产品 |
| mart_employee_positions | 一版架构的一条人员任职，含姓名、类型和自身岗位名称 |
| mart_position_tree | 同版的一对祖先/后代岗位，含距离、直接上级及版本生效信息 |
| mart_position_hp | 同版的岗位—医院—产品唯一覆盖，无金额 |

raw 业务源独立于 app 账号。staging 保持来源粒度；intermediate 计算去重、组合和闭包；Mart 用明确列清单发布实体。staging 和 intermediate 是视图，6 张 Mart 落表并执行 ANALYZE。索引随 dbt 全量重建恢复。

OrganizationGraph 将岗位树 LEFT JOIN 任职，保留空岗、一人多岗、同岗多人。树中 depth=0 表示自身，depth=1 表示直属关系。版本目录取树的 DISTINCT；两个消费出口在 dbt exposure 中记录。

## 身份、目录和销售授权

JWT 的 viewerEmployeeCode 表示登录人；subjectEmployeeCodes 表示被分析人员。二者分别使用。销售期间取 Sales.sales_date 的查询日期范围。签名上下文若含 months，则查询期间必须完全落在其中。architectureMode 和 architectureSnapshot 选择架构口径。组织目录可传显式版本 organizationSnapshot，或传销售月 organizationPeriod，由同一规则选择当月有效版本。这些名称属于本例契约。

app.users 保存工号与 active；app.access_grants 保存工号与 root_position_code。一人可获多个根岗位。每条授权允许该根岗位在各已生效版本中的整个子树；独立旧岗位需要单独授权。岗位编码跨版本对应同一业务岗位，禁止将旧编码复用给无关岗位。

目录可见范围为授权子树加上级路径，方便识别人和领导；兄弟岗位被过滤。Organization 查询同时限制 snapshot_code、ancestor_position_code、position_code。销售权限只由授权子树覆盖计算；上级姓名可见不会扩大销售范围。

销售请求先查询被分析人员在每个所需版本中的任职，确认其目录可见；再将任职子树展开为 H+P。数据库先比较对象岗位与授权岗位。对象包含额外岗位时，再通过 SQL 集合差核对其覆盖是否完全获准。完整对象的任一配对越权时，整个请求拒绝；多个对象的合法配对取并集。

最终过滤集合为唯一的“销售月、医院、产品”，query_rewrite 将它整体 AND 到用户条件。该键来自销售事实，Rollup 也保留它；用户只查总计时仍然执行。底层 Cube public=false，通过 Sales、Organization 两个 View 分别查询；成员存在性由 Cube 原生校验，Python 负责权限主题路由。

Python 在 Cube 进程内运行，数据库查询使用绑定参数。每请求一条连接、一个 REPEATABLE READ READ ONLY 事务；当前授权和账号每次重新读取。撤权在下一请求生效，已读取快照的请求继续依该快照完成。跨请求权限缓存未启用，数据库失败直接阻止查询。

## 三种架构口径

版本来自 raw.positions.snapshot_code。valid_from 为版月初，valid_to 为下一版月初，左闭右开；上版持续到下一版。organization_as_of 固定为 2026-11-17，dbt 标记当前与已生效版本；推进日期后重新构建。未来预装版本不能查询。

| 口径 | 各销售月使用的组织、任职和覆盖版本 |
|---|---|
| current | 全部销售月使用最近已生效版 |
| as_of | 全部销售月使用用户明确选择的同一版 |
| period | 每个销售月取不晚于该月的最近版；缺少历史时拒绝 |

三种口径共用同一份当前岗位授权。切换版本会改变任职、上下级和岗位 H+P；历史任职自身不产生访问权。示例中的人员姓名/类型是当前主档属性，未实现历史属性版本。

## 数字员工与预聚合

search_people、get_person_context、get_managers 均通过 Organization View 读取。姓名搜索和多人领导查询批量加载任职及父岗位人员，避免逐人往返。person_id/person_name 对应后代岗位任职人；经理按直接父岗位任职且 role_kind=manager 识别，这是本例的汇报规则。

query_sales 只发送一次 Cube load。diagnostics 额外读取权限集合、原始事实、SQL 和物理 Rollup，用于本机页面和验收。诊断开销与普通业务请求分开。演示服务停止后，合法 JWT 仍可直接查询 Cube。

SalesFacts.monthlyHospitalProduct 以月/H/P、配对键和常用展示维度聚合；员工、辖区和组织版本不进入聚合。查询依据指标、维度和过滤条件匹配预聚合，组织变化继续使用同一套销售聚合。省份未加入 Rollup，用于验证回源。Cube 每分钟检查销售事实、医院和产品 Mart 的 PostgreSQL OID。dbt 全量替换表时 OID 变化，触发 Rollup 更新。此方式依赖全量换表；原地增量更新需改用数据发布批次作为刷新键。

多岗位覆盖是关系模型的一项正确性验收：范围先取并集，再汇总事实；同一交易计入一次，金额相同的不同交易分别计入。

## 运行与适用边界

sh run.sh build 在全量 dbt 构建前停止消费者，通过后恢复；失败保持停止。test 包含故障路径、dbt build、数据质量、18 个销售场景、撤权停用、无账号人员、深层空岗、未来版本及构建前后差异；刷新夹具最终恢复。所有步骤都在独立合成库执行。

本机 HTTP 适配器允许用 X-Demo-Viewer 切换合成身份，默认 M001；公开签名密钥用于复现。正式部署需要接入真实认证、数据库最小权限账号和相应的密钥管理。Cube 1.7.1 将 Python 钩子异常包装为 HTTP 500，演示客户端识别 DemoError 为业务拒绝；其他上游失败按故障返回。

范围枚举保护为 24 个连续月和 50,000 个月/H/P 组合；结果达到 1,000 行时明确拒绝完整汇总。该保护用于限定本示例；大范围查询可评估数据库权限桥或半连接的方案，并重新验证 Rollup 匹配与撤权语义。SQL 在库内完成去重与对象校验，最多取上限加一的不同组合用于判定，超限时不发送部分组合。该边界只约束返回行数，PG 的去重、排序、临时文件和 CPU 成本仍取决于覆盖分布。

同岗医院集×产品集、完整月快照、岗位编码稳定是适用前提。日级调岗、按医院限定产品资格、多币种、退货与分摊需要增加对应业务模型。Veeva 官方对象仅作关系参考，源系统差异见[Veeva 映射](research/veeva-object-mapping.md)。

工程修改要求集中于[示例工程约定](standards/example.md)。官方扩展机制和自定义业务算法的区别见[Cube 官方依据](research/official-cube-guidance.md)。
