-- 对 Cube 发布稳定实体；业务规则集中在 intermediate，便于 review 血缘。
{{ config(indexes=[{'columns': ['snapshot_code', 'employee_code'], 'type': 'btree'}]) }}
select assignment_id, snapshot_code, employee_code, employee_name, role_kind,
    position_code, position_name
from {{ ref('int_employee_positions') }}
