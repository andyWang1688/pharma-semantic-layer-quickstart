-- 保持来源行数与粒度，只统一字段名称和类型。
select id, snapshot_code, position_code, account_code, account_type
from {{ source('raw', 'position_account_histories') }}
