"""真实 dbt + Cube 刷新验收；仅修改本合成库，finally 恢复全部夹具。"""

import json
import os
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cube_client import cube_request, sign_context
from diagnostics import run_sales_example
from security.database import query
from tools import build_query, get_person_context, query_sales, search_people


def rebuild():
    # 构建日志在容器临时目录；失败只输出诊断尾部，不向交付目录导出一次性报告。
    result = subprocess.run(["dbt", "build", "--profiles-dir", "."], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    summary = [line for line in result.stdout.splitlines() if "PASS=" in line]
    print("PASS dbt 重建：" + " \n".join(summary), flush=True)


def same_token_request(token):
    # 使用同一枚仍有效 JWT 与同一个查询，验证撤权/停用优先于既有结果缓存。
    request = Request(
        os.environ["CUBE_API_URL"] + "/load",
        data=json.dumps({"query": build_query(["2026-01"], "total")}).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=25) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def verify():
    # 避免覆盖他人手动创建的测试数据；清理范围只限这里新建的十二月版本。
    assert not query("SELECT 1 FROM raw.positions WHERE snapshot_code = '2026-12'")
    assert query(
        "SELECT position_code FROM raw.employee_positions WHERE snapshot_code='2026-11' AND employee_code='E001'"
    ) == [{"position_code": "T1"}]
    assert not query("SELECT 1 FROM raw.employees WHERE employee_code='E008'")
    assert not query("SELECT 1 FROM raw.employee_positions WHERE id=600")
    assert not query("SELECT 1 FROM raw.positions WHERE position_code='R1'")
    token = sign_context({"viewerEmployeeCode": "E001"})
    status, result = same_token_request(token)
    assert status == 200 and float(result["data"][0]["Sales.total_amount"]) == 130, result
    try:
        query("DELETE FROM app.access_grants WHERE employee_code='E001' AND root_position_code='T1'")
        status, result = same_token_request(token)
        assert status >= 400 and not result.get("data"), result
        query("INSERT INTO app.access_grants (employee_code,root_position_code) VALUES ('E001','T1')")
        status, result = same_token_request(token)
        assert status == 200 and float(result["data"][0]["Sales.total_amount"]) == 130, result
        query("UPDATE app.users SET active=false WHERE employee_code='E001'")
        status, result = same_token_request(token)
        assert status >= 400 and not result.get("data"), result
        query("UPDATE app.users SET active=true WHERE employee_code='E001'")
        print("PASS 同一 JWT：撤权立即拒绝、恢复授权立即可查、停用立即拒绝；全程无需 dbt 重建", flush=True)

        query("""
            INSERT INTO raw.positions SELECT '2026-12', position_code, position_name, parent_code FROM raw.positions WHERE snapshot_code='2026-11';
            INSERT INTO raw.employee_positions SELECT id+1000, '2026-12', employee_code, position_code FROM raw.employee_positions WHERE snapshot_code='2026-11';
            INSERT INTO raw.position_account_histories SELECT id+1000, '2026-12', position_code, account_code, account_type FROM raw.position_account_histories WHERE snapshot_code='2026-11';
            INSERT INTO raw.position_product_histories SELECT id+1000, '2026-12', position_code, product_code FROM raw.position_product_histories WHERE snapshot_code='2026-11';
            INSERT INTO raw.positions VALUES ('2026-11','R1','深层空岗','T1');
            INSERT INTO raw.employees VALUES ('E008','无账号业务人员','representative');
            INSERT INTO raw.employee_positions VALUES (600,'2026-11','E008','T1');
            UPDATE raw.employee_positions SET position_code='T2' WHERE snapshot_code='2026-11' AND employee_code='E001';
        """)
        before = run_sales_example("M001", ["E001"], ["2026-01"], group_by="total")
        assert before["total"] == 130 and before["snapshots"] == {"2026-01": "2026-11"}
        rebuild()
        # 深层空岗验证：同一View可查跨级关系，并保留无任职人员的岗位。
        status, graph = cube_request(
            "load",
            {"viewerEmployeeCode": "M001"},
            {
                "dimensions": [
                    "Organization.ancestor_position_code",
                    "Organization.position_code",
                    "Organization.depth",
                    "Organization.person_id",
                ],
                "filters": [
                    {"member": "Organization.ancestor_position_code", "operator": "equals", "values": ["M"]},
                    {"member": "Organization.position_code", "operator": "equals", "values": ["R1"]},
                ],
            },
        )
        assert status == 200 and len(graph["data"]) == 1, graph
        assert (
            int(graph["data"][0]["Organization.depth"]) == 2 and graph["data"][0]["Organization.person_id"] is None
        ), graph
        print("PASS 统一Organization View：M→R1距离2，空岗保留且任职人员为空", flush=True)
        # 人员维度独立于登录账号：有业务任职即可被授权经理分析，本人登录仍须账号。
        person = get_person_context("M001", "E008")
        assert person["person_name"] == "无账号业务人员", person
        assert search_people("M001", "无账号业务人员")["people"][0]["person_id"] == "E008"
        assert query_sales("M001", ["E008"], ["2026-01"], group_by="total")["total"] == 130
        status, result = cube_request("load", {"viewerEmployeeCode": "E008"}, build_query(["2026-01"], "total"))
        assert status >= 400 and not result.get("data"), result
        assert not query("SELECT 1 FROM app.users WHERE employee_code='E008'")
        print("PASS 无登录账号的业务人员：经理可查目录和130业绩，该人员直接访问Cube仍被拒绝", flush=True)
        moved = run_sales_example("M001", ["E001"], ["2026-01"], group_by="total")
        assert moved["total"] == moved["rawTotal"] == 150, moved
        assert moved["snapshots"] == {"2026-01": "2026-11"}, moved
        assert moved["verifiedRollups"] == ["SalesFacts.monthlyHospitalProduct"] and moved["physicalRollupTables"]
        status, result = cube_request(
            "load",
            {
                "viewerEmployeeCode": "M001",
                "subjectEmployeeCodes": ["E001"],
                "architectureMode": "as_of",
                "architectureSnapshot": "2026-12",
            },
            build_query(["2026-01"], "total"),
        )
        assert status >= 400 and not result.get("data"), result
        print("PASS 任职变化构建前130、构建后150；预装未来版本不成为当前；销售继续命中共享 Rollup", flush=True)
    finally:
        # 删除本测试的新版本，恢复原任职和在线账号/授权，再重建派生表。
        query("""
            UPDATE app.users SET active=true WHERE employee_code='E001';
            INSERT INTO app.access_grants (employee_code,root_position_code) VALUES ('E001','T1') ON CONFLICT DO NOTHING;
            UPDATE raw.employee_positions SET position_code='T1' WHERE snapshot_code='2026-11' AND employee_code='E001';
            DELETE FROM raw.employee_positions WHERE id=600;
            DELETE FROM raw.employees WHERE employee_code='E008';
            DELETE FROM raw.employee_positions WHERE snapshot_code='2026-12';
            DELETE FROM raw.position_account_histories WHERE snapshot_code='2026-12';
            DELETE FROM raw.position_product_histories WHERE snapshot_code='2026-12';
            DELETE FROM raw.positions WHERE snapshot_code='2026-12';
            DELETE FROM raw.positions WHERE snapshot_code='2026-11' AND position_code='R1';
        """)
        rebuild()
    restored = run_sales_example("M001", ["E001"], ["2026-01"], group_by="total")
    assert restored["total"] == restored["rawTotal"] == 130
    print("PASS 所有刷新夹具已恢复；页面与数据库回到基准样例", flush=True)


if __name__ == "__main__":
    verify()
