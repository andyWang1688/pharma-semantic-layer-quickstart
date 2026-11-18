# 请求示例：查询团队销售额

王经理登录，查询“本团队2026年1月销售额”。Cube 按当前架构及岗位授权，汇总销售事实并返回180。以下说明客户端、数仓、语义模型和权限各自执行的工作。

## 1. dbt提前准备6个实体

执行sh run.sh build后，岗位树记录十一月M→M、M→T1、M→T2及各岗自身，同时保存版本和生效信息。任职记录E001→T1、E002→T2、M001→M。岗位覆盖为T1:{H1/P1,H2/P1}；T2:{H1/P1,H1/P2,H3/P1,H3/P2}。

这些关系分别位于mart_position_tree、mart_employee_positions、mart_position_hp。另有销售事实和医院/产品两个维度，总共6张Mart。

## 2. 人员识别与组织查询

登录人查询本人团队时，可以直接使用已验证的工号 M001；按姓名指定其他对象时，通过 Organization View 找到真实工号和岗位。以下以姓名检索展示同一组织接口的用法。

search_people通过Cube Organization View批量查询真实姓名、任职和版本，条件是person_name包含张三且depth=0。返回E001/T1和E006/T2供消歧。父岗位任职人员再由一次批量查询取得。选择E001后，李四得到E002。

~~~json
{
  "dimensions": ["Organization.person_id", "Organization.person_name", "Organization.position_code", "Organization.parent_position_code"],
  "filters": [
    {"member":"Organization.depth","operator":"equals","values":["0"]},
    {"member":"Organization.person_name","operator":"contains","values":["张三"]}
  ]
}
~~~

岗位T1、T2的parent_position_code均为M。get_person_context再通过同一View查询position_code=M、depth=0、role_kind=manager，取得M001王经理；get_managers合并去重。详情和领导都由同一组织View查询取得。

query_rewrite会将Organization限制到选定版本和授权关联岗位。M001获根M授权，能看到M/T1/T2任职者；E001只获T1，能查看T1和上级M，兄弟T2被过滤。看到王经理姓名后，查他完整销售仍要检查H+P。

## 3. 发送销售意图，Cube自己计算范围

本例受信签发器把以下内容签入JWT，AI提供对象ID和期间：

~~~json
{"viewerEmployeeCode":"M001","subjectEmployeeCodes":["M001"],"months":["2026-01"],"architectureMode":"current"}
~~~

普通Cube query：

~~~json
{
  "measures":["Sales.total_amount","Sales.total_quantity"],
  "dimensions":[],
  "timeDimensions":[{"dimension":"Sales.sales_date","dateRange":["2026-01-01","2026-01-31"]}],
  "timezone":"UTC"
}
~~~

Cube原生Python query_rewrite调用policy.rewrite_query。只读一致性事务内检查app.users的active和app.access_grants，随后从岗位树取得唯一当前版本2026-11。

对象范围由任职直接关联岗位树和覆盖：

~~~sql
SELECT DISTINCT t.snapshot_code, hp.hospital_code, hp.product_code
FROM marts.mart_employee_positions a
JOIN marts.mart_position_tree t
  ON t.snapshot_code=a.snapshot_code AND t.ancestor_position_code=a.position_code
JOIN marts.mart_position_hp hp
  ON hp.snapshot_code=t.snapshot_code AND hp.position_code=t.descendant_position_code
WHERE a.snapshot_code='2026-11' AND a.employee_code = 'M001';
~~~

PostgreSQL 先比较请求岗位与授权根 M 展开的子树。对象包含子树外的岗位时，再检查其 H+P 与已授权 H+P 的集合差。检查通过后，数据库只返回按销售月去重的组合。对象必须在可见组织中，完整H+P范围也必须被授权包含。授权撤销在下一请求重新读取。

## 4. 查询预聚合并返回结果

唯一范围为：

~~~text
2026-01,H1,P1
2026-01,H2,P1
2026-01,H1,P2
2026-01,H3,P1
2026-01,H3,P2
~~~

转换成JSON文本配对键，强制AND到查询：

~~~json
{
  "member":"Sales.month_hospital_product_key","operator":"equals",
  "values":[
    "[\"2026-01\", \"H1\", \"P1\"]",
    "[\"2026-01\", \"H2\", \"P1\"]",
    "[\"2026-01\", \"H1\", \"P2\"]",
    "[\"2026-01\", \"H3\", \"P1\"]",
    "[\"2026-01\", \"H3\", \"P2\"]"
  ]
}
~~~

Cube命中SalesFacts.monthlyHospitalProduct。H1/P1=60+40=100，H2/P1=15+15=30，H3/P2=25+25=50，合计180。另两种覆盖没有交易，贡献0。未授权的H2/P2=800被排除。张三130、李四150，二人并集合计180。

## 5. 三种历史口径仍复用同一岗位树

张三一至二月：current两个月用十一月T1得到290；as_of二月两个月用二月T2得到330；period一月T1、二月T2得到310。版本选择从树的去重版本目录取得，销售月与H/P配对保留。

可以在shared_sales执行：

~~~sql
SELECT * FROM marts.mart_position_tree
WHERE snapshot_code='2026-11' ORDER BY ancestor_position_code,depth,descendant_position_code;
SELECT * FROM marts.mart_employee_positions WHERE snapshot_code='2026-11';
SELECT * FROM marts.mart_position_hp WHERE snapshot_code='2026-11';
~~~

工具源码[tools.py](../demo/tools.py)，权限[policy.py](../cube/security/policy.py)，直接REST示例[examples.md](examples.md)。
