-- 保持来源行数与粒度，只统一字段名称和类型。
select id as assignment_id, snapshot_code, employee_code, position_code
from {{ source('raw', 'employee_positions') }}
