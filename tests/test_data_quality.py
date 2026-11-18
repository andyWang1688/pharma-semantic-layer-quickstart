import re
from pathlib import Path

from security.database import query

# 每条检查都应返回零行；发现问题时给出对应的实际记录，不静默跳过。
CHECKS = {
    "人员任职业务键重复": """
        SELECT snapshot_code, employee_code, position_code, COUNT(*) FROM raw.employee_positions
        GROUP BY 1,2,3 HAVING COUNT(*) > 1
    """,
    "辖区医院业务键重复": """
        SELECT snapshot_code, position_code, account_code, account_type, COUNT(*) FROM raw.position_account_histories
        GROUP BY 1,2,3,4 HAVING COUNT(*) > 1
    """,
    "辖区产品业务键重复": """
        SELECT snapshot_code, position_code, product_code, COUNT(*) FROM raw.position_product_histories
        GROUP BY 1,2,3 HAVING COUNT(*) > 1
    """,
    "任职孤立人员或辖区": """
        SELECT assignments.* FROM raw.employee_positions assignments
        LEFT JOIN raw.employees people USING (employee_code)
        LEFT JOIN raw.positions positions USING (snapshot_code, position_code)
        WHERE people.employee_code IS NULL OR positions.position_code IS NULL
    """,
    "医院覆盖孤立辖区或医院": """
        SELECT accounts.* FROM raw.position_account_histories accounts
        LEFT JOIN raw.positions positions USING (snapshot_code, position_code)
        LEFT JOIN marts.mart_hospital_dimension hospitals ON hospitals.hospital_code = accounts.account_code
        WHERE positions.position_code IS NULL OR hospitals.hospital_code IS NULL
    """,
    "产品覆盖孤立辖区或产品": """
        SELECT relations.* FROM raw.position_product_histories relations
        LEFT JOIN raw.positions positions USING (snapshot_code, position_code)
        LEFT JOIN marts.mart_product_dimension products USING (product_code)
        WHERE positions.position_code IS NULL OR products.product_code IS NULL
    """,
    "医院覆盖客户类型错误": """
        SELECT * FROM raw.position_account_histories WHERE account_type <> 'hospital'
    """,
    "辖区父节点跨版本或缺失": """
        SELECT child.* FROM raw.positions child LEFT JOIN raw.positions parent
          ON parent.snapshot_code = child.snapshot_code AND parent.position_code = child.parent_code
        WHERE child.parent_code IS NOT NULL AND parent.position_code IS NULL
    """,
    "辖区层级循环": """
        WITH RECURSIVE paths AS (
          SELECT snapshot_code, position_code, parent_code, ARRAY[position_code] AS visited, false AS cycle
          FROM raw.positions
          UNION ALL
          SELECT parent.snapshot_code, parent.position_code, parent.parent_code,
                 paths.visited || parent.position_code, parent.position_code = ANY(paths.visited)
          FROM paths JOIN raw.positions parent
            ON parent.snapshot_code = paths.snapshot_code AND parent.position_code = paths.parent_code
          WHERE NOT paths.cycle
        ) SELECT * FROM paths WHERE cycle
    """,
    "组织快照格式无效": """
        SELECT * FROM raw.positions WHERE snapshot_code !~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
    """,
    "授权根辖区不存在": """
        SELECT grants.* FROM app.access_grants grants
        WHERE NOT EXISTS (SELECT 1 FROM raw.positions WHERE position_code = grants.root_position_code)
    """,
    "任职人员属性不一致或缺失": """
        SELECT a.* FROM marts.mart_employee_positions a
        LEFT JOIN raw.employees e USING (employee_code)
        WHERE e.employee_code IS NULL OR a.employee_name IS DISTINCT FROM e.employee_name
          OR a.role_kind IS DISTINCT FROM e.role_kind
    """,
    "销售事实孤立医院或产品": """
        SELECT facts.* FROM marts.mart_sales_fact facts
        LEFT JOIN marts.mart_hospital_dimension hospitals USING (hospital_code)
        LEFT JOIN marts.mart_product_dimension products USING (product_code)
        WHERE hospitals.hospital_code IS NULL OR products.product_code IS NULL
    """,
    "销售事实基础字段无效": """
        SELECT * FROM marts.mart_sales_fact
        WHERE sales_id = '' OR hospital_code = '' OR product_code = ''
          OR sales_amount < 0 OR sales_quantity < 0
    """,
}


def verify_layering():
    # 架构契约：业务源只来自 raw，每张源表只有一个 staging 入口。
    # 检查源码依赖和数据库结构，防止后续把应用账号重新当作人员主档。
    model_root = Path(__file__).resolve().parents[1] / "dbt" / "models"
    expected_sources = {
        "employees",
        "positions",
        "employee_positions",
        "position_account_histories",
        "position_product_histories",
        "sales",
        "hospitals",
        "products",
    }
    found_sources = []
    for layer, allowed_prefixes in (
        ("staging", ()),
        ("intermediate", ("stg_", "int_")),
        ("marts", ("int_", "mart_")),
    ):
        for path in sorted((model_root / layer).glob("*.sql")):
            sql = path.read_text()
            sources = re.findall(r"source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", sql)
            refs = re.findall(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)", sql)
            assert not re.search(r"\bapp\.", sql), path
            if layer == "staging":
                assert len(sources) == 1 and sources[0][0] == "raw" and not refs, (path, sources, refs)
                found_sources.append(sources[0][1])
            else:
                assert not sources and refs and all(ref.startswith(allowed_prefixes) for ref in refs), (
                    path,
                    sources,
                    refs,
                )
    assert len(found_sources) == len(expected_sources) and set(found_sources) == expected_sources, found_sources
    raw_tables = {row["tablename"] for row in query("SELECT tablename FROM pg_tables WHERE schemaname='raw'")}
    app_tables = {row["tablename"] for row in query("SELECT tablename FROM pg_tables WHERE schemaname='app'")}
    assert raw_tables == expected_sources, raw_tables
    assert app_tables == {"users", "access_grants"}, app_tables
    # 精简后发布6个稳定实体；删除的派生表也必须从运行库移除，避免误读旧数据。
    expected_marts = {
        "mart_sales_fact",
        "mart_hospital_dimension",
        "mart_product_dimension",
        "mart_employee_positions",
        "mart_position_tree",
        "mart_position_hp",
    }
    for schema, prefix in (("marts", "mart_"), ("intermediate", "int_")):
        kind = "BASE TABLE" if schema == "marts" else "VIEW"
        actual = {
            row["table_name"]
            for row in query(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type=%s",
                (schema, kind),
            )
        }
        expected = (
            expected_marts
            if schema == "marts"
            else {
                "int_sales",
                "int_hospitals",
                "int_products",
                "int_employee_positions",
                "int_position_tree",
                "int_position_hp",
            }
        )
        assert actual == expected, (schema, actual, expected)
    account_columns = {
        row["column_name"]
        for row in query(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='app' AND table_name='users'"
        )
    }
    assert account_columns == {"employee_code", "active"}, account_columns
    grant_columns = {
        row["column_name"]
        for row in query(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='app' AND table_name='access_grants'"
        )
    }
    assert grant_columns == {"employee_code", "root_position_code"}, grant_columns
    print("PASS 分层：8个raw业务源各有一个staging入口，依赖逐层向下；app只含账号与实时授权", flush=True)


def verify():
    verify_layering()
    for name, sql in CHECKS.items():
        violations = query(sql)
        assert not violations, (name, violations)
    # 不只检查没有脏行，还核对完整样例，防止误删关系/事实后“检查全绿”。
    expected_counts = {
        "app.users": 10,
        "raw.employees": 10,
        "raw.positions": 13,
        "raw.employee_positions": 23,
        "raw.position_account_histories": 16,
        "raw.position_product_histories": 16,
        "marts.mart_hospital_dimension": 5,
        "marts.mart_product_dimension": 4,
        "marts.mart_sales_fact": 13,
        "app.access_grants": 9,
        "raw.sales": 13,
        "raw.hospitals": 5,
        "raw.products": 4,
        "marts.mart_position_tree": 19,
        "marts.mart_position_hp": 25,
        "marts.mart_employee_positions": 23,
    }
    for table, expected in expected_counts.items():
        actual = query(f"SELECT COUNT(*) AS count FROM {table}")[0]["count"]
        assert actual == expected, (table, actual, expected)
    # 两笔同金额销售是正常事实；以下业务汇总必须保留它们并排除越权测试事实。
    expected_facts = [
        ("2026-01", "H1", "P1", 100),
        ("2026-01", "H2", "P1", 30),
        ("2026-01", "H2", "P2", 800),
        ("2026-01", "H3", "P2", 50),
        ("2026-01", "H4", "P1", 600),
        ("2026-01", "H4", "P3", 700),
        ("2026-01", "H9", "P9", 999),
        ("2026-02", "H1", "P1", 120),
        ("2026-02", "H2", "P1", 40),
        ("2026-02", "H3", "P2", 60),
    ]
    actual_facts = query("""
        SELECT to_char(sales_date, 'YYYY-MM') AS month, hospital_code, product_code, SUM(sales_amount) AS amount
        FROM marts.mart_sales_fact GROUP BY 1,2,3 ORDER BY 1,2,3
    """)
    assert [
        (row["month"], row["hospital_code"], row["product_code"], row["amount"]) for row in actual_facts
    ] == expected_facts, actual_facts
    print(
        f"PASS 数据质量：{len(CHECKS)} 项检查、{len(expected_counts)} 张表行数、10 组月医院产品金额全部一致", flush=True
    )


if __name__ == "__main__":
    verify()
