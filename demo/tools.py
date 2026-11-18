"""可选数字员工工具：表达分析意图，通过 Cube 读取人员和销售。

身份由演示 HTTP 适配器注入；所有行权限由 Cube 执行。此模块不查询数据库。
"""

import calendar
from decimal import Decimal

from cube_client import cube_request
from security.database import DemoError
from security.policy import normalize_months

RESULT_LIMIT = 1000
GROUPS = {
    "detail": ["hospital_code", "hospital_name", "product_code", "product_name"],
    "product": ["product_code", "product_name"],
    "total": [],
    "province": ["province_name"],
}


def date_range(months: list[str]) -> list[str]:
    """把连续月份转换为包含首尾两天的 Cube 起止日期。"""
    ordered = normalize_months(months)
    last_month = ordered[-1]
    last_day = calendar.monthrange(int(last_month[:4]), int(last_month[5:]))[1]
    return [ordered[0] + "-01", f"{last_month}-{last_day:02d}"]


def trusted_context(
    viewer_id: str,
    person_ids: list[str],
    months: list[str],
    architecture_mode: str = "current",
    snapshot: str | None = None,
    require_rollup: bool = False,
) -> dict:
    """签入登录身份与分析意图；H+P 由 Cube 每次依据当前授权计算。"""
    if (
        not isinstance(person_ids, list)
        or not person_ids
        or any(not isinstance(person_id, str) or not person_id.strip() for person_id in person_ids)
    ):
        raise DemoError("必须传入有效的人员 ID 列表", 400)
    return {
        "viewerEmployeeCode": viewer_id,
        "subjectEmployeeCodes": person_ids,
        "months": normalize_months(months),
        "architectureMode": architecture_mode,
        "architectureSnapshot": snapshot,
        "requireRollup": require_rollup,
    }


def build_query(
    months: list[str],
    group_by: str = "detail",
    *,
    hospital_codes: list[str] | None = None,
    product_codes: list[str] | None = None,
) -> dict:
    """构建分析意图；医院与产品是可选业务筛选，Cube 仍会追加完整权限约束。"""
    if not isinstance(group_by, str) or group_by not in GROUPS:
        raise DemoError("分析分组无效", 400)
    filters = []
    for member, codes in (("hospital_code", hospital_codes), ("product_code", product_codes)):
        if codes is None:
            continue
        if (
            not isinstance(codes, list)
            or not codes
            or any(not isinstance(code, str) or not code.strip() for code in codes)
        ):
            raise DemoError("医院、产品筛选必须为非空编码列表", 400)
        filters.append({"member": "Sales." + member, "operator": "equals", "values": sorted(set(codes))})
    return {
        "measures": ["Sales.total_amount", "Sales.total_quantity"],
        "dimensions": ["Sales." + member for member in GROUPS[group_by]],
        "timeDimensions": [{"dimension": "Sales.sales_date", "dateRange": date_range(months)}],
        "filters": filters,
        "timezone": "UTC",
        "limit": RESULT_LIMIT,
    }


def _load_rows(context: dict, cube_query: dict) -> list[dict]:
    status, result = cube_request("load", context, cube_query)
    if status != 200 or result.get("error"):
        # Cube 1.7.1 将 Python 业务异常包装为 500；只识别已知业务拒绝。
        # 数据库或执行器错误保留上游故障含义，业务响应不携带 Python 堆栈。
        message = str(result.get("error", "Cube 查询失败"))
        marker = "Python error: DemoError:"
        if status == 500 and marker in message:
            raise DemoError(message.split(marker, 1)[1].splitlines()[0].strip(), 403)
        if status in (400, 401, 403):
            raise DemoError(message, status)
        raise DemoError("Cube 执行失败，请检查 Cube 容器日志", 502)
    rows = result.get("data")
    if not isinstance(rows, list):
        raise DemoError("Cube 响应缺少查询数据", 502)
    if len(rows) >= RESULT_LIMIT:
        # 无法证明结果完整时明确停止；不把截断结果相加后称作完整业绩。
        raise DemoError(f"结果达到 {RESULT_LIMIT} 行上限，请缩小范围或提高汇总层级", 400)
    return rows


def query_sales(
    viewer_id: str,
    person_ids: list[str],
    months: list[str],
    architecture_mode: str = "current",
    snapshot: str | None = None,
    group_by: str = "detail",
    *,
    hospital_codes: list[str] | None = None,
    product_codes: list[str] | None = None,
) -> dict:
    """一次 Cube load 查询完整对象范围，重叠人员的业绩由事实并集计算。"""
    context = trusted_context(viewer_id, person_ids, months, architecture_mode, snapshot)
    rows = _load_rows(
        context,
        build_query(
            months,
            group_by,
            hospital_codes=hospital_codes,
            product_codes=product_codes,
        ),
    )
    # 医院/产品分组互斥；这项求和适用于完整返回的互斥分组。
    total = sum((Decimal(str(row.get("Sales.total_amount") or 0)) for row in rows), Decimal(0))
    return {
        "subjectIds": sorted(set(person_ids)),
        "mode": architecture_mode,
        "data": rows,
        "total": float(total),
        "tool": "query_sales",
        "coverage": "complete_subject_scope",
        "months": normalize_months(months),
        "snapshot": snapshot,
    }


def organization_query(
    viewer_id: str, snapshot: str | None, dimensions: list[str], filters: list[dict], sales_month: str | None = None
) -> list[dict]:
    """人员、任职和上下级关系只从受权限控制的 Organization View 获取。"""
    rows = _load_rows(
        {"viewerEmployeeCode": viewer_id, "organizationSnapshot": snapshot, "organizationPeriod": sales_month},
        {
            "dimensions": ["Organization." + member for member in dimensions],
            "filters": filters,
            "limit": RESULT_LIMIT,
        },
    )
    return [{key.removeprefix("Organization."): value for key, value in row.items()} for row in rows]


def organization_filter(member: str, values: list[str], operator: str = "equals") -> dict:
    return {"member": "Organization." + member, "operator": operator, "values": values}


def _people_contexts(
    viewer_id: str, snapshot: str | None, filters: list[dict], sales_month: str | None = None
) -> tuple[str, list[dict]]:
    # 批量读取任职和直接上级任职，重名和多人请求使用相同的两段查询。
    rows = organization_query(
        viewer_id,
        snapshot,
        [
            "snapshot_code",
            "person_id",
            "person_name",
            "role_kind",
            "position_code",
            "position_name",
            "parent_position_code",
        ],
        [organization_filter("depth", ["0"]), *filters],
        sales_month,
    )
    if not rows:
        # 空搜索仍返回 Cube 实际采用的架构版本，客户端不猜测当前版本。
        versions = organization_query(viewer_id, snapshot, ["snapshot_code"], [], sales_month)
        if len(versions) != 1:
            raise DemoError("无法确定可查询的组织版本")
        return versions[0]["snapshot_code"], []
    version = rows[0]["snapshot_code"]
    parents = sorted({row["parent_position_code"] for row in rows if row["parent_position_code"]})
    manager_rows = (
        organization_query(
            viewer_id,
            version,
            ["position_code", "person_id", "person_name"],
            [
                organization_filter("depth", ["0"]),
                organization_filter("position_code", parents),
                organization_filter("role_kind", ["manager"]),
            ],
        )
        if parents
        else []
    )
    people = {}
    for row in rows:
        person_id = row["person_id"]
        if person_id is None:  # 空岗保留在组织 View；人员工具只输出实际任职人。
            continue
        person = people.setdefault(
            person_id,
            {
                "person_id": person_id,
                "person_name": row["person_name"],
                "role_kind": row["role_kind"],
                "snapshot": version,
                "assignments": [],
                "managers": {},
                "tool": "get_person_context",
            },
        )
        person["assignments"].append(
            {
                "territory_id": row["position_code"],
                "territory_name": row["position_name"],
                "parent_territory_id": row["parent_position_code"],
            }
        )
        for manager in manager_rows:
            if manager["position_code"] == row["parent_position_code"]:
                person["managers"][manager["person_id"]] = {
                    "person_id": manager["person_id"],
                    "person_name": manager["person_name"],
                }
    for person in people.values():
        person["assignments"].sort(key=lambda assignment: assignment["territory_id"])
        person["managers"] = sorted(person["managers"].values(), key=lambda manager: manager["person_id"])
    return version, [people[person_id] for person_id in sorted(people)]


def search_people(viewer_id: str, name: str, snapshot: str | None = None, *, sales_month: str | None = None) -> dict:
    """按可见姓名检索，按工号区分重名；返回任职信息供用户消歧。"""
    if not isinstance(name, str) or not name.strip():
        raise DemoError("请输入待查人员姓名", 400)
    version, people = _people_contexts(
        viewer_id,
        snapshot,
        [
            organization_filter("person_name", [name.strip()], "contains"),
        ],
        sales_month,
    )
    return {
        "status": "needs_clarification" if len(people) > 1 else "resolved" if people else "not_found",
        "people": people,
        "snapshot": version,
        "tool": "search_people",
        "next_action": "请用户按辖区或人员 ID 选择，禁止猜测" if len(people) > 1 else "使用返回的 person_id 查询",
    }


def get_person_context(
    viewer_id: str, person_id: str, snapshot: str | None = None, *, sales_month: str | None = None
) -> dict:
    """获取指定人员的任职及直接管理者；目录可见性由 Cube 决定。"""
    if not isinstance(person_id, str) or not person_id.strip():
        raise DemoError("必须提供有效的人员 ID", 400)
    _, people = _people_contexts(viewer_id, snapshot, [organization_filter("person_id", [person_id])], sales_month)
    if not people:
        raise DemoError("该人员不在当前可查询的组织范围内")
    return people[0]


def get_managers(
    viewer_id: str, person_ids: list[str], snapshot: str | None = None, *, sales_month: str | None = None
) -> dict:
    """批量查询直接管理者，按工号去重，保留兼岗和多个直接管理者。"""
    if (
        not isinstance(person_ids, list)
        or not person_ids
        or any(not isinstance(person_id, str) or not person_id.strip() for person_id in person_ids)
    ):
        raise DemoError("必须传入有效的人员 ID 列表", 400)
    version, people = _people_contexts(
        viewer_id,
        snapshot,
        [
            organization_filter("person_id", sorted(set(person_ids))),
        ],
        sales_month,
    )
    if {person["person_id"] for person in people} != set(person_ids):
        raise DemoError("部分人员不在当前可查询的组织范围内")
    managers = {manager["person_id"]: manager for person in people for manager in person["managers"]}
    return {
        "people": people,
        "managers": sorted(managers.values(), key=lambda person: person["person_id"]),
        "snapshot": version,
        "tool": "get_managers",
        "status": "resolved" if len(managers) == 1 else "needs_clarification" if managers else "no_manager_assignment",
    }


def function_schema(name, description, properties, required):
    # 给数字员工的调用契约，禁止多余参数，避免传入伪造的权限值。
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


# Schema 不含 viewer_id、allowedHospitalProducts；身份由 HTTP 适配器注入。
DIRECTORY_PERIOD = {"type": "string", "description": "逐期历史使用此销售月的有效架构，跨月分别查询；与 snapshot 互斥"}
TOOL_SCHEMAS = [
    function_schema(
        "search_people",
        "按当前登录人的可见目录检索真实人员。重名时必须消歧，禁止编造工号。",
        {
            "name": {"type": "string"},
            "snapshot": {"type": "string", "description": "可选的已有历史架构月份"},
            "sales_month": DIRECTORY_PERIOD,
        },
        ["name"],
    ),
    function_schema(
        "get_person_context",
        "取得已识别人员的辖区和直接管理者。不能把组织信息视为销售访问授权。",
        {
            "person_id": {"type": "string"},
            "snapshot": {"type": "string"},
            "sales_month": DIRECTORY_PERIOD,
        },
        ["person_id"],
    ),
    function_schema(
        "get_managers",
        "查询这些人员在指定架构中的直接管理者，并按人员 ID 去重。多位管理者时不要猜。",
        {
            "person_ids": {"type": "array", "items": {"type": "string"}},
            "snapshot": {"type": "string"},
            "sales_month": DIRECTORY_PERIOD,
        },
        ["person_ids"],
    ),
    function_schema(
        "query_sales",
        "查询已识别对象的完整授权业绩。多人员取事实并集，权限范围由 Cube 计算。医院、产品参数用于业务筛选。",
        {
            "person_ids": {"type": "array", "items": {"type": "string"}, "description": "只使用人员工具返回的 ID"},
            "months": {"type": "array", "items": {"type": "string"}, "description": "连续 YYYY-MM 月份"},
            "architecture_mode": {"type": "string", "enum": ["current", "as_of", "period"]},
            "snapshot": {"type": "string", "description": "as_of 模式必填，其余模式禁止传入"},
            "group_by": {"type": "string", "enum": list(GROUPS)},
            "hospital_codes": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "可选医院编码筛选；继续受登录人权限限制",
            },
            "product_codes": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "可选产品编码筛选；继续受登录人权限限制",
            },
        },
        ["person_ids", "months"],
    ),
]

# HTTP 路由只允许调用这里列出的业务函数。
FUNCTIONS = {
    "search_people": search_people,
    "get_person_context": get_person_context,
    "get_managers": get_managers,
    "query_sales": query_sales,
}
