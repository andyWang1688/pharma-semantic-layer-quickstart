-- 保持来源行数与粒度，只统一字段名称和类型。
select employee_code, employee_name, role_kind
from {{ source('raw', 'employees') }}
