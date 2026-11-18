-- 保持来源行数与粒度，只统一字段名称和类型。
select hospital_code, hospital_name, province_name
from {{ source('raw', 'hospitals') }}
