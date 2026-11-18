from cube_client import cube_request


def verify():
    # run.sh 先停止常驻 demo HTTP 服务；此临时客户端仍直接请求 Cube。
    # 证明没有 Cube → demo 授权回调依赖，登录状态与目录限制仍在 Cube 内生效。
    query = {
        "measures": ["Sales.total_amount"],
        "timeDimensions": [{"dimension": "Sales.sales_date", "dateRange": ["2026-01-01", "2026-01-31"]}],
        "timezone": "UTC",
    }
    status, result = cube_request("load", {"viewerEmployeeCode": "E001"}, query)
    assert status == 200 and float(result["data"][0]["Sales.total_amount"]) == 130, result
    # 有效签名也不能让已停用账号访问数据。
    status, result = cube_request("load", {"viewerEmployeeCode": "E005"}, query)
    assert status >= 400 and not result.get("data"), result
    status, result = cube_request(
        "load",
        {"viewerEmployeeCode": "E001"},
        {
            "dimensions": ["Organization.person_id", "Organization.person_name"],
            "filters": [{"member": "Organization.person_name", "operator": "equals", "values": ["李四"]}],
        },
    )
    assert status == 200 and not result["data"], result
    print("PASS demo HTTP 服务停止：Cube 独立返回本人130、拒绝停用身份、人员目录权限仍生效", flush=True)


if __name__ == "__main__":
    verify()
