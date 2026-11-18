import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cube_client import cube_request
from diagnostics import run_sales_example
from security.database import DemoError, query
from security.policy import resolve_sales_scope
from tools import build_query, get_managers, get_person_context, query_sales, search_people, trusted_context

# 使用真实 HTTP、PostgreSQL 和 Rollup 验证业务语义，而非只测试生成的 query 长相。
CASES = [
    ("张三共享业绩", ["E001"], ["2026-01"], "current", None, "detail", True, 100),
    ("李四共享业绩", ["E002"], ["2026-01"], "current", None, "detail", True, 100),
    ("领导共享业绩只计一次", ["M001"], ["2026-01"], "current", None, "detail", True, 100),
    ("张三完整范围", ["E001"], ["2026-01"], "current", None, "detail", False, 130),
    ("李四完整范围", ["E002"], ["2026-01"], "current", None, "detail", False, 150),
    ("领导完整范围", ["M001"], ["2026-01"], "current", None, "detail", False, 180),
    ("同时问两个人按事实并集", ["E001", "E002"], ["2026-01"], "current", None, "total", False, 180),
    ("兼任多个岗位", ["E003"], ["2026-01"], "current", None, "detail", False, 180),
    ("领导二月", ["M001"], ["2026-02"], "current", None, "detail", False, 220),
    ("领导跨月", ["M001"], ["2026-01", "2026-02"], "current", None, "total", False, 400),
    ("按产品汇总", ["M001"], ["2026-01"], "current", None, "product", False, 180),
    ("没有展示维度仍受权限限制", ["M001"], ["2026-01"], "current", None, "total", False, 180),
    ("省份回源", ["M001"], ["2026-01"], "current", None, "province", False, 180),
    ("当前架构看两月", ["E001"], ["2026-01", "2026-02"], "current", None, "total", False, 290),
    ("固定二月架构看两月", ["E001"], ["2026-01", "2026-02"], "as_of", "2026-02", "total", False, 330),
    ("逐期历史架构看历史", ["E001"], ["2026-01", "2026-02"], "period", None, "total", False, 310),
    ("固定旧架构", ["E001"], ["2026-01"], "as_of", "2026-10", "total", False, 999),
    ("经理查询离职人员历史范围", ["E007"], ["2026-01"], "period", None, "total", False, 130),
]


def expect_denied(function, *arguments, **options):
    # 必须确实拒绝，不能用空结果悄悄替代需要明确报错的越权场景。
    try:
        function(*arguments, **options)
    except DemoError as error:
        assert error.status in (400, 403), str(error)
        return
    raise AssertionError("应当拒绝此次查询")


def verify():
    # 脏源数据仅在只读 CTE 夹具中模拟，不混入可供 review 的基础业务表。
    duplicate_source = query("""
        WITH source_accounts AS (
          SELECT position_code, account_code FROM raw.position_account_histories
          WHERE snapshot_code = '2026-11' AND position_code = 'T1' AND account_type = 'hospital'
          UNION ALL SELECT 'T1', 'H1'
        ), normalized_accounts AS (
          SELECT DISTINCT position_code, account_code FROM source_accounts
        ) SELECT (SELECT COUNT(*) FROM source_accounts) AS source_count,
                 (SELECT COUNT(*) FROM normalized_accounts) AS normalized_count
    """)
    assert duplicate_source == [{"source_count": 3, "normalized_count": 2}], duplicate_source
    print("PASS 脏源数据夹具 3 行规范化为 2 条关系，基础样例保持业务键唯一", flush=True)
    # 每个场景同时对账原始事实；命中候选不够，还检查物理表和仅预聚合执行。
    for name, people, months, mode, snapshot, grouping, shared, expected in CASES:
        result = run_sales_example(
            "M001",
            people,
            months,
            mode,
            snapshot,
            grouping,
            hospital_codes=["H1"] if shared else None,
            product_codes=["P1"] if shared else None,
        )
        assert result["total"] == expected, (name, result["total"])
        assert result["rawTotal"] == expected, (name, result["rawTotal"])
        assert bool(result["verifiedRollups"]) == (grouping != "province"), name
        assert bool(result["physicalRollupTables"]) == (grouping != "province"), name
        print(f"PASS {name}: {expected}; {result['executionMode']}", flush=True)

    # 验证同名消歧、领导去重、离职对象，以及“目录能找到人”不扩大销售权限。
    matches = search_people("M001", "张三")
    assert matches["status"] == "needs_clarification"
    assert {person["person_id"] for person in matches["people"]} == {"E001", "E006"}
    assert search_people("M001", "李四")["people"][0]["person_id"] == "E002"
    assert search_people("E001", "李四")["status"] == "not_found"
    managers = get_managers("M001", ["E001", "E002"])
    assert [person["person_id"] for person in managers["managers"]] == ["M001"]
    assert get_person_context("M001", "E001", "2026-02")["assignments"][0]["territory_id"] == "T2"
    assert get_person_context("E001", "M001")["person_name"] == "王经理"
    assert search_people("M001", "赵离职", sales_month="2026-01")["people"][0]["person_id"] == "E007"
    assert search_people("M001", "赵离职", sales_month="2026-02")["status"] == "not_found"
    assert get_managers("M001", ["E001"], sales_month="2026-03")["snapshot"] == "2026-02"
    departed = search_people("M001", "赵离职", "2026-01")
    assert departed["people"][0]["person_id"] == "E007"
    expect_denied(query_sales, "E007", ["E007"], ["2026-01"], "period")
    business_result = query_sales("M001", ["E001"], ["2026-01"])
    assert business_result["total"] == 130
    assert not {"pairs", "rawSql", "enforcedFilters", "cubeSql"} & business_result.keys()
    # 业务筛选支持任意医院/产品；筛选值不会替代 Cube 的强制权限。
    filtered = query_sales(
        "M001",
        ["M001"],
        ["2026-01"],
        group_by="total",
        hospital_codes=["H2"],
        product_codes=["P1"],
    )
    assert filtered["total"] == 30, filtered
    outside = query_sales(
        "M001",
        ["M001"],
        ["2026-01"],
        group_by="total",
        hospital_codes=["H2"],
        product_codes=["P2"],
    )
    assert outside["total"] == 0, outside
    print("PASS 通用医院/产品筛选：H2/P1=30，越权配对H2/P2=0", flush=True)
    expect_denied(query_sales, "E001", ["M001"], ["2026-01"])
    print("PASS 重名消歧、真实 Organization 查询、目录过滤、领导去重、目录信息不扩大销售权限", flush=True)
    # 组织关系直接由统一 View 返回：直属下级、上级路径和空岗均受同一份授权约束。
    status, graph = cube_request(
        "load",
        {"viewerEmployeeCode": "M001"},
        {
            "dimensions": ["Organization.ancestor_position_code", "Organization.position_code", "Organization.depth"],
            "filters": [
                {"member": "Organization.ancestor_position_code", "operator": "equals", "values": ["M"]},
                {"member": "Organization.depth", "operator": "equals", "values": ["1"]},
            ],
        },
    )
    assert status == 200 and {row["Organization.position_code"] for row in graph["data"]} == {"T1", "T2"}, graph
    status, graph = cube_request(
        "load",
        {"viewerEmployeeCode": "E001"},
        {
            "dimensions": ["Organization.ancestor_position_code", "Organization.position_code"],
        },
    )
    assert status == 200 and graph["data"], graph
    assert all(
        row["Organization.ancestor_position_code"] in {"M", "T1"} and row["Organization.position_code"] in {"M", "T1"}
        for row in graph["data"]
    ), graph
    print("PASS 统一Organization View：直属下级T1/T2；代表只见授权子树与上级路径，兄弟岗位被过滤", flush=True)

    # 当前授权可赋给新审计员，也可撤销旧经理；历史任职不能替代这份授权。
    assert query_sales("M002", ["E001"], ["2026-01"], "period")["total"] == 130
    expect_denied(query_sales, "M003", ["E001"], ["2026-01"], "period")
    print("PASS 历史组织不等于当前授权：新授权审计员按当前授予范围访问，调岗经理不能借旧岗位恢复权限", flush=True)

    # 普通账号无需单独开通历史功能，三种口径均按同一份岗位授权查询。
    for mode, snapshot in (("current", None), ("as_of", "2026-02"), ("period", None)):
        result = query_sales("E002", ["E002"], ["2026-01", "2026-02"], mode, snapshot, "total")
        assert result["total"] == 330, (mode, result)
    assert get_person_context("E002", "E002", "2026-02")["assignments"][0]["territory_id"] == "T2"
    assert query_sales("E001", ["E001"], ["2026-01"], "as_of", "2026-01", "total")["total"] == 130
    # 张三二月在T2，今天只获T1授权，因此二月完整历史业绩仍拒绝。
    expect_denied(query_sales, "E001", ["E001"], ["2026-02"], "period")
    expect_denied(query_sales, "E002", ["E001"], ["2026-01"], "period")
    print("PASS 普通账号三种历史口径均可用；历史组织可查，跨授权岗位的历史业绩仍拒绝", flush=True)

    # 客户端 OR 条件必须整体 AND 权限；H2/P2=800 虽满足用户条件，仍不可进入。
    context = trusted_context("M001", ["M001"], ["2026-01"])
    attack = build_query(["2026-01"], "total")
    attack["filters"] = [
        {
            "or": [
                {"member": "Sales.hospital_code", "operator": "equals", "values": ["H2"]},
                {"member": "Sales.product_code", "operator": "equals", "values": ["P2"]},
            ]
        }
    ]
    status, result = cube_request("load", context, attack)
    assert status == 200 and float(result["data"][0]["Sales.total_amount"]) == 80, result
    # 只签登录身份，Cube 从标准 dateRange 推导本人期间，不经过工具范围解析。
    status, result = cube_request("load", {"viewerEmployeeCode": "E001"}, build_query(["2026-01"], "total"))
    assert status == 200 and float(result["data"][0]["Sales.total_amount"]) == 130, result
    print("PASS 直接 Cube REST：只有可信登录身份和普通查询，无需 demo 后端组装权限或回调", flush=True)
    status, result = cube_request(
        "load", trusted_context("M001", ["E001"], ["2026-01"], "period"), build_query(["2026-01", "2026-02"], "total")
    )
    assert status >= 400 and "销售查询期间超出了签名上下文允许的月份" in result.get("error", ""), result
    status, result = cube_request("load", {**context, "requireRollup": True}, build_query(["2026-01"], "province"))
    assert status >= 400 and not result.get("data"), result
    for invalid_context in [
        {},
        trusted_context("E005", ["E001"], ["2026-01"]),
        trusted_context("E001", ["M001"], ["2026-01"]),
    ]:
        status, result = cube_request("load", invalid_context, build_query(["2026-01"], "total"))
        assert status >= 400 and not result.get("data"), result
    status, result = cube_request("load", context, {"measures": ["SalesFacts.total_amount"]})
    assert status >= 400 and not result.get("data"), result
    print("PASS queryRewrite 强制 AND、时间与 H/P 配对、仅预聚合限制、无身份/停用/越权/内部 Cube 拒绝", flush=True)

    # 字段合法性直接交给 Cube；移除 Python 字段名单后仍须原生拒绝未知/未公开字段。
    invalid_members = [
        {**build_query(["2026-01"], "total"), "measures": ["Sales.does_not_exist"]},
        {**build_query(["2026-01"], "total"), "dimensions": ["Sales.sales_id"]},
        {
            **build_query(["2026-01"], "total"),
            "filters": [
                {"member": "Sales.does_not_exist", "operator": "equals", "values": ["H1"]},
            ],
        },
        {**build_query(["2026-01"], "total"), "order": {"Sales.does_not_exist": "desc"}},
    ]
    for invalid_query in invalid_members:
        status, result = cube_request("load", context, invalid_query)
        assert status >= 400 and not result.get("data"), result
        assert "does_not_exist" in result.get("error", "") or "sales_id" in result.get("error", ""), result
    # 不依靠 public:false 拦过滤引用；主题路由拒绝任何跨入底层或另一套行权限的查询。
    for mixed_query in [
        {
            **build_query(["2026-01"], "province"),
            "filters": [
                {"member": "SalesFacts.hospital_code", "operator": "equals", "values": ["H1"]},
            ],
        },
        {**build_query(["2026-01"], "total"), "order": {"SalesFacts.total_amount": "desc"}},
        {**build_query(["2026-01"], "total"), "dimensions": ["Organization.person_name"]},
    ]:
        status, result = cube_request("load", context, mixed_query)
        assert status >= 400 and not result.get("data"), result
        assert "只允许分别查询 Sales 或 Organization View" in result.get("error", ""), result
    print("PASS 原生成员校验：未知字段/View未公开字段拒绝；主题路由拒绝底层过滤、排序及混用", flush=True)

    # 所有失败都应默认拒绝：无辖区、停用、未知账号、不存在版本等。
    for viewer_id in ("E004", "E005", "unknown"):
        expect_denied(query_sales, viewer_id, ["E001"], ["2026-01"])
    assert query_sales("E001", ["E001"], ["2026-01"], "period")["total"] == 130
    expect_denied(query_sales, "M001", ["E001"], ["2025-12"], "period")
    expect_denied(query_sales, "M001", ["E001"], ["2026-01"], "as_of", "2099-01")
    for path, payload in [
        (
            "/api/tools/query_sales",
            {"person_ids": ["E001"], "months": ["2026-01"], "allowedHospitalProducts": ["forged"]},
        ),
        ("/api/tools/query_sales", {"person_ids": ["E001"], "months": ["2026-01"], "viewer_id": "M001"}),
    ]:
        request = Request(
            "http://localhost:8080" + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            urlopen(request, timeout=20)
        except HTTPError as error:
            assert error.code in (400, 403)
        else:
            raise AssertionError(path)
    print("PASS 历史查询统一使用岗位授权、缺失历史快照不回退、工具拒绝伪造 H/P 或登录人", flush=True)

    # 月份不能丢失，否则一月/二月的不同 H+P 会互相扩大授权。
    scope = resolve_sales_scope("M001", ["E001"], ["2026-01", "2026-02"], "period")
    assert ("2026-01", "H3", "P2") not in scope["units"]
    assert ("2026-02", "H2", "P1") not in scope["units"]
    # 故意使用错误的事实 JOIN 覆盖写法，证明重叠辖区会算成 280，而正确总计是 180。
    wrong = query("""
        WITH coverage AS (
          SELECT DISTINCT accounts.position_code, accounts.account_code, products.product_code
          FROM raw.position_account_histories accounts
          JOIN raw.position_product_histories products USING (snapshot_code, position_code)
          WHERE accounts.snapshot_code = '2026-11' AND accounts.account_type = 'hospital'
            AND accounts.position_code IN ('T1', 'T2')
        ) SELECT SUM(facts.sales_amount) AS amount FROM marts.mart_sales_fact facts
        JOIN coverage ON coverage.account_code = facts.hospital_code AND coverage.product_code = facts.product_code
        WHERE facts.sales_date >= '2026-01-01' AND facts.sales_date < '2026-02-01'
    """)
    assert float(wrong[0]["amount"]) == 280
    # 组织源变更需要 dbt 构建后发布，独立的 test_dbt_refresh.py 验证刷新边界。
    print(f"PASS {len(CASES)} 销售场景及人员工具、越权、历史时间配对、真实 Rollup、版本选择检查全部通过", flush=True)


if __name__ == "__main__":
    verify()
