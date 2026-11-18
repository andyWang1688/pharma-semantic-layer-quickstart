# 直接查询Cube：销售与统一组织View

## 1. 本地身份令牌

~~~sh
sh run.sh token M001
~~~

本例签发器只供合成环境，有效两分钟；正式接身份系统。Cube地址http://127.0.0.1:32771/cubejs-api/v1，页面32770。

将返回JWT用于请求：

~~~sh
curl http://127.0.0.1:32771/cubejs-api/v1/load \
  -H 'Authorization: Bearer <刚生成的JWT>' \
  -H 'Content-Type: application/json' \
  --data '{"query":{"measures":["Sales.total_amount"],"timeDimensions":[{"dimension":"Sales.sales_date","dateRange":["2026-01-01","2026-01-31"]}],"timezone":"UTC"}}'
~~~

M001默认查询本人管理范围，返回180。E001令牌默认本人130。Continue wait表示构建或执行中，重试同请求即可。Cube自己解析权限范围。

## 2. 用同一个Organization View查姓名、岗位与上下级

下列JSON均为POST /load的body，以M001令牌访问。字段person_id/person_name代表后代岗位任职人员。

查张三的任职（重名返回E001/T1和E006/T2，需消歧）：

~~~json
{
  "query": {
    "dimensions":["Organization.person_id","Organization.person_name","Organization.position_code","Organization.parent_position_code"],
    "filters":[
      {"member":"Organization.depth","operator":"equals","values":["0"]},
      {"member":"Organization.person_name","operator":"contains","values":["张三"]}
    ]
  }
}
~~~

查M直属下级岗位：

~~~json
{
  "query": {
    "dimensions":["Organization.position_code","Organization.position_name","Organization.depth"],
    "filters":[
      {"member":"Organization.ancestor_position_code","operator":"equals","values":["M"]},
      {"member":"Organization.depth","operator":"equals","values":["1"]}
    ]
  }
}
~~~

查T1所有上级岗位：

~~~json
{
  "query": {
    "dimensions":["Organization.ancestor_position_code","Organization.ancestor_position_name","Organization.depth"],
    "filters":[
      {"member":"Organization.position_code","operator":"equals","values":["T1"]},
      {"member":"Organization.depth","operator":"gt","values":["0"]}
    ]
  }
}
~~~

取得上级M后，用position_code=M、depth=0查询person_id/person_name，得到上级岗位任职者。业务规则按role_kind=manager筛经理。全部下级使用ancestor_position_code和depth>0；空岗仍返回岗位，人员字段为空。

## 3. 历史和工具适配

organizationSnapshot签入已有架构版本时，组织查询固定在该版本；按当前岗位授权确定范围。销售对象及三种模式见[请求链路](request-walkthrough.md)。demo/tools.py提供search_people/get_person_context/get_managers/query_sales，均通过Cube View查询。

本例允许通过测试页面工具切换合成身份；生产由可信登录态注入身份。AI提供对象和分析条件，H+P由Cube计算。

## 4. 使用通用医院、产品筛选

工具适配器提供 hospital_codes 和 product_codes 两个可选业务筛选。以下本机请求以王经理身份查询团队 1 月在 H2、P1 上的销售额，返回 30：

~~~sh
curl http://127.0.0.1:32770/api/tools/query_sales \
  -H 'X-Demo-Viewer: M001' \
  -H 'Content-Type: application/json' \
  --data '{"person_ids":["M001"],"months":["2026-01"],"group_by":"total","hospital_codes":["H2"],"product_codes":["P1"]}'
~~~

普通筛选只缩小分析范围。Cube 将原有业务条件整体与岗位授权过滤 AND；即使客户端传入 H2/P2，也无法读到该账号范围外的销售事实。
