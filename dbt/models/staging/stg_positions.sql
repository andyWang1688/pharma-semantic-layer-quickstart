-- 保持来源行数与粒度，只统一字段名称和类型。
select snapshot_code, position_code, position_name, parent_code
from {{ source('raw', 'positions') }}
