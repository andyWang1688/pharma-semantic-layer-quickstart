from decimal import Decimal

from cube_client import cube_request
from security.database import DemoError, query
from security.policy import normalize_months, resolve_sales_scope, rewrite_query, scope_key
from tools import GROUPS, build_query, date_range, trusted_context


def raw_sales(scope, months, group_by, hospital_codes=None, product_codes=None):
    # 仅供页面/测试对账：绕过 Rollup，用相同权限键直接汇总原始事实。
    # 普通 query_sales 不调用这里，不能将对账开销理解为生产每次查询的必需步骤。
    # SQL 分组表达式来自固定白名单；动态权限和日期仍使用绑定参数。
    expressions = {
        "hospital_code": "facts.hospital_code",
        "hospital_name": "hospitals.hospital_name",
        "product_code": "facts.product_code",
        "product_name": "products.product_name",
        "province_name": "hospitals.province_name",
    }
    dimensions = GROUPS[group_by]
    select = [f'{expressions[member]} AS "Sales.{member}"' for member in dimensions]
    select += ['SUM(facts.sales_amount) AS "Sales.total_amount"', 'SUM(facts.sales_quantity) AS "Sales.total_quantity"']
    start, end = date_range(months)
    sql = (
        "SELECT "
        + ", ".join(select)
        + """
        FROM marts.mart_sales_fact facts
        JOIN marts.mart_hospital_dimension hospitals USING (hospital_code)
        JOIN marts.mart_product_dimension products USING (product_code)
        WHERE facts.month_hospital_product_key = ANY(%s)
          AND facts.sales_date >= %s::date AND facts.sales_date < %s::date + INTERVAL '1 day'
    """
    )
    parameters = [[scope_key(unit) for unit in scope["units"]], start, end]
    for column, codes in (("hospital_code", hospital_codes), ("product_code", product_codes)):
        if codes is not None:
            # 列名来自本模块固定声明，筛选值独立绑定。
            sql += f" AND facts.{column} = ANY(%s)"
            parameters.append(codes)
    if dimensions:
        sql += " GROUP BY " + ", ".join(expressions[member] for member in dimensions)
    return {"data": query(sql, tuple(parameters)), "sql": sql, "parameters": parameters}


def run_sales_example(
    viewer_id,
    person_ids,
    months,
    architecture_mode="current",
    snapshot=None,
    group_by="detail",
    *,
    hospital_codes=None,
    product_codes=None,
):
    # 演示诊断链路：额外显示范围、原始对账、SQL 和物理表证据。
    # 这里先解析一次范围用于展示，随后 Cube load 会独立重算并强制检查。
    months = normalize_months(months)
    scope = resolve_sales_scope(viewer_id, person_ids, months, architecture_mode, snapshot)
    cube_query = build_query(months, group_by, hospital_codes=hospital_codes, product_codes=product_codes)
    # 本例省份没有放进 Rollup，专用于演示自动回源；其余场景强制仅预聚合。
    context = trusted_context(viewer_id, person_ids, months, architecture_mode, snapshot, group_by != "province")
    status, actual = cube_request("load", context, cube_query)
    if status != 200 or actual.get("error"):
        raise DemoError(actual.get("error", "Cube 查询失败"), 502)
    if len(actual["data"]) >= cube_query["limit"]:
        raise DemoError("诊断结果达到行数上限，请缩小范围或提高汇总层级", 400)
    # 先实际 load，再索取 SQL 诊断；/sql 是 REST 诊断端点，不是 PostgreSQL SQL API。
    reference = raw_sales(scope, months, group_by, hospital_codes, product_codes)
    sql_status, sql_response = cube_request("sql", context, cube_query)
    if sql_status != 200 or sql_response.get("error"):
        raise DemoError(sql_response.get("error", "Cube SQL 查询失败"), 502)
    # 仅模式编译匹配不足以证明物理构建；结合仅预聚合执行成功和真实表验证。
    physical_tables = query(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'cube_pre_aggregations' AND tablename LIKE 'sales_facts_monthly_hospital_product%' ORDER BY tablename"
    )
    names = query(
        "SELECT DISTINCT employee_code, employee_name FROM marts.mart_employee_positions WHERE employee_code = ANY(%s) ORDER BY employee_code",
        (scope["subject_ids"],),
    )

    def summarize(rows):
        return float(sum((Decimal(str(row.get("Sales.total_amount") or 0)) for row in rows), Decimal(0)))

    return {
        "viewerId": viewer_id,
        "subjectIds": scope["subject_ids"],
        "employeeName": "、".join(person["employee_name"] + " · " + person["employee_code"] for person in names),
        "mode": architecture_mode,
        "snapshots": scope["snapshots"],
        "pairs": [
            {"month": month, "hospital_code": hospital, "product_code": product}
            for month, hospital, product in scope["units"]
        ],
        "query": cube_query,
        "enforcedFilters": rewrite_query(cube_query, context)["filters"],
        "data": actual["data"],
        "total": summarize(actual["data"]),
        "rawTotal": summarize(reference["data"]),
        "executionMode": "rollup_only" if context["requireRollup"] else "automatic",
        "verifiedRollups": ["SalesFacts.monthlyHospitalProduct"] if context["requireRollup"] else [],
        "physicalRollupTables": [row["tablename"] for row in physical_tables] if context["requireRollup"] else [],
        "cubeSql": sql_response,
        "rawSql": reference["sql"],
        "rawParameters": reference["parameters"],
        "coverage": "complete_subject_scope",
        "tool": "query_sales",
    }
