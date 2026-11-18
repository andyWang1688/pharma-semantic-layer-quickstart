"""医药示例的业务授权：登录身份、架构口径、完整对象范围与强制过滤。

公开入口是 rewrite_query 和 resolve_sales_scope。每次调用使用同一只读快照；
dbt 已准备岗位闭包和 H+P，运行时只选择版本并核对当前授权。
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypedDict

from security.database import DemoError, query, read_session

ArchitectureMode = Literal["current", "as_of", "period"]
ScopeUnit = tuple[str, str, str]  # 销售月份、医院编码、产品编码
MAX_MONTHS = 24
MAX_SCOPE_UNITS = 50_000
SALES_SCOPE_SQL = Path(__file__).with_name("sales_scope.sql").read_text(encoding="utf-8")


class SalesScope(TypedDict):
    """经过完整授权检查的范围；units 按事实粒度去重，与岗位数量无关。"""

    viewer_id: str
    subject_ids: list[str]
    snapshots: dict[str, str]
    units: list[ScopeUnit]
    mode: ArchitectureMode


def scope_key(unit: ScopeUnit) -> str:
    """与 dbt int_sales 的 PostgreSQL JSON 文本保持相同编码和空格。"""
    return json.dumps(unit, ensure_ascii=False)


def normalize_months(months: Any) -> list[str]:
    """接受连续的 YYYY-MM 月份；排序去重，并限制一次请求的分析跨度。"""
    if not isinstance(months, list) or not months or len(months) > MAX_MONTHS:
        raise DemoError(f"请选择 1 至 {MAX_MONTHS} 个连续月份", 400)
    if any(
        not isinstance(month, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month) or month.startswith("0000-")
        for month in months
    ):
        raise DemoError("月份格式必须为 YYYY-MM", 400)
    ordered = sorted(set(months))
    ordinals = [int(month[:4]) * 12 + int(month[5:]) for month in ordered]
    if ordinals != list(range(ordinals[0], ordinals[-1] + 1)):
        raise DemoError("月份必须连续", 400)
    return ordered


def _query_members(cube_query: dict) -> list[str]:
    # 只判断权限主题；字段是否存在、是否由 View 公开，交给 Cube 原生编译器。
    members = []
    for field in ("measures", "dimensions", "segments"):
        members.extend(cube_query.get(field) or [])
    members.extend(item.get("dimension") for item in cube_query.get("timeDimensions") or [])
    order = cube_query.get("order") or []
    if isinstance(order, dict):
        members.extend(order)
    else:
        for item in order:
            members.append(
                item.get("id") if isinstance(item, dict) else item[0] if isinstance(item, list) and item else item
            )

    def visit(filters):
        for condition in filters:
            if "and" in condition:
                visit(condition["and"])
            elif "or" in condition:
                visit(condition["or"])
            else:
                members.append(condition.get("member", condition.get("dimension")))

    visit(cube_query.get("filters") or [])
    return members


def _months_from_query(cube_query: dict) -> list[str]:
    # 标准 Cube 日期范围决定需要授权的月份；原查询仍保留日级条件。
    ranges = [
        item.get("dateRange")
        for item in cube_query.get("timeDimensions") or []
        if item.get("dimension") == "Sales.sales_date"
    ]
    if len(ranges) != 1 or not isinstance(ranges[0], list) or len(ranges[0]) != 2:
        raise DemoError("请为销售查询指定明确的起止日期", 400)
    try:
        start, end = [date.fromisoformat(value[:10]) for value in ranges[0]]
    except (TypeError, ValueError, OverflowError):
        raise DemoError("销售日期必须为有效的 ISO 日期", 400) from None
    first, last = start.year * 12 + start.month - 1, end.year * 12 + end.month - 1
    if end < start or last - first >= MAX_MONTHS:
        raise DemoError(f"销售期间必须在 1 至 {MAX_MONTHS} 个月内", 400)
    return [f"{ordinal // 12:04d}-{ordinal % 12 + 1:02d}" for ordinal in range(first, last + 1)]


def _require_active_user(viewer_id: Any) -> None:
    if not isinstance(viewer_id, str) or not viewer_id.strip():
        raise DemoError("缺少有效的登录工号")
    rows = query("SELECT active FROM app.users WHERE employee_code = %s", (viewer_id,))
    if not rows or not rows[0]["active"]:
        raise DemoError("登录账号不存在或已停用")


def _architecture_versions() -> list[dict]:
    rows = query("""
        SELECT DISTINCT snapshot_code, valid_from, valid_to, is_current
        FROM marts.mart_position_tree WHERE is_available ORDER BY snapshot_code
    """)
    if not rows or sum(row["is_current"] for row in rows) != 1:
        raise DemoError("组织模型尚未完成有效构建")
    return rows


def _select_snapshot(versions: list[dict], snapshot: str | None) -> str:
    if snapshot is None:
        return next(row["snapshot_code"] for row in versions if row["is_current"])
    if snapshot not in {row["snapshot_code"] for row in versions}:
        raise DemoError("指定架构快照不存在或尚未生效", 400)
    return snapshot


def _snapshots_for(months: list[str], mode: ArchitectureMode, snapshot: str | None) -> dict[str, str]:
    # dbt 负责版本生效和岗位递归；这里只选择各销售月应使用的已生效版本。
    if not isinstance(mode, str) or mode not in {"current", "as_of", "period"}:
        raise DemoError("架构模式无效", 400)
    versions = _architecture_versions()
    if mode != "as_of" and snapshot is not None:
        raise DemoError("仅指定快照模式可以传入架构版本", 400)
    if mode == "as_of" and snapshot is None:
        raise DemoError("指定快照模式必须传入架构版本", 400)
    fixed = _select_snapshot(versions, snapshot)
    available = [row["snapshot_code"] for row in versions]
    result = {}
    for month in months:
        candidates = [version for version in available if version <= month]
        if mode == "period" and not candidates:
            raise DemoError(f"{month} 之前没有组织快照，不能自动套用当前架构", 400)
        result[month] = candidates[-1] if mode == "period" else fixed
    return result


def _organization_positions(viewer_id: str, versions: list[str]) -> list[dict]:
    # 目录可见范围包含授权子树和上级路径；销售授权只使用子树。
    return query(
        """
        SELECT DISTINCT t.snapshot_code,
          CASE WHEN t.ancestor_position_code = g.root_position_code
            THEN t.descendant_position_code ELSE t.ancestor_position_code END AS position_code
        FROM marts.mart_position_tree t
        JOIN app.access_grants g
          ON g.root_position_code = t.ancestor_position_code
          OR g.root_position_code = t.descendant_position_code
        WHERE g.employee_code = %s AND t.snapshot_code = ANY(%s) AND t.is_available
        ORDER BY t.snapshot_code, position_code
    """,
        (viewer_id, versions),
    )


def _resolve_sales_scope(
    viewer_id: str, subject_ids: Any, months: Any, mode: ArchitectureMode, snapshot: str | None
) -> SalesScope:
    if (
        not isinstance(subject_ids, list)
        or not subject_ids
        or any(not isinstance(subject, str) or not subject.strip() for subject in subject_ids)
    ):
        raise DemoError("必须传入有效的人员 ID 列表", 400)
    snapshots = _snapshots_for(normalize_months(months), mode, snapshot)
    subjects = sorted(set(subject_ids))
    rows = query(SALES_SCOPE_SQL, (json.dumps(snapshots), subjects, viewer_id, MAX_SCOPE_UNITS + 1, MAX_SCOPE_UNITS))
    status = rows[0]["status"]
    if status == "hidden_subject":
        raise DemoError("查询对象超出登录人的人员目录范围")
    if status == "too_large":
        raise DemoError(f"查询范围超过 {MAX_SCOPE_UNITS} 个月份医院产品组合，请缩小期间或对象", 400)
    if status == "empty":
        raise DemoError("所选架构下没有医院产品权限")
    if status != "ok":
        raise DemoError("登录人不能查看该对象的完整业绩")
    return {
        "viewer_id": viewer_id,
        "subject_ids": subjects,
        "snapshots": snapshots,
        "units": sorted((row["month"], row["hospital_code"], row["product_code"]) for row in rows),
        "mode": mode,
    }


@read_session()
def resolve_sales_scope(
    viewer_id: str,
    subject_ids: list[str],
    months: list[str],
    mode: ArchitectureMode = "current",
    snapshot: str | None = None,
) -> SalesScope:
    """为本地诊断解析范围；普通业务请求由 Cube 调用 rewrite_query。"""
    _require_active_user(viewer_id)
    return _resolve_sales_scope(viewer_id, subject_ids, months, mode, snapshot)


@read_session()
def rewrite_query(cube_query: dict, security_context: dict) -> dict:
    """Cube 原生入口：保留用户条件并强制 AND 权限，读取异常直接阻止查询。"""
    viewer_id = security_context.get("viewerEmployeeCode")
    _require_active_user(viewer_id)
    members = _query_members(cube_query)
    if not members or any(not isinstance(member, str) for member in members):
        raise DemoError("查询成员必须来自已发布的语义 View")
    prefixes = {member.split(".")[0] for member in members}
    if prefixes == {"Sales"}:
        subjects = security_context.get("subjectEmployeeCodes", [viewer_id])
        months = _months_from_query(cube_query)
        signed_months = security_context.get("months")
        if signed_months is not None and not set(months).issubset(normalize_months(signed_months)):
            raise DemoError("销售查询期间超出了签名上下文允许的月份", 400)
        scope = _resolve_sales_scope(
            viewer_id,
            subjects,
            months,
            security_context.get("architectureMode", "current"),
            security_context.get("architectureSnapshot"),
        )
        mandatory = {
            "member": "Sales.month_hospital_product_key",
            "operator": "equals",
            "values": [scope_key(unit) for unit in scope["units"]],
        }
    elif prefixes == {"Organization"}:
        period = security_context.get("organizationPeriod")
        explicit = security_context.get("organizationSnapshot")
        if period is None:
            snapshot = _select_snapshot(_architecture_versions(), explicit)
        else:
            snapshot = _snapshots_for(normalize_months([period]), "period", explicit)[period]
        positions = [row["position_code"] for row in _organization_positions(viewer_id, [snapshot])]
        if not positions:
            raise DemoError("当前账号没有可查询的组织范围")
        mandatory = {
            "and": [
                {"member": "Organization.snapshot_code", "operator": "equals", "values": [snapshot]},
                {"member": "Organization.ancestor_position_code", "operator": "equals", "values": positions},
                {"member": "Organization.position_code", "operator": "equals", "values": positions},
            ]
        }
    else:
        # 两个 View 使用不同的行权限；过滤、排序也必须留在同一权限主题中。
        raise DemoError("只允许分别查询 Sales 或 Organization View")
    return {**cube_query, "filters": [{"and": [*(cube_query.get("filters") or []), mandatory]}]}
