-- 保持来源行数与粒度，只统一字段名称和类型。
select id, snapshot_code, position_code, product_code
from {{ source('raw', 'position_product_histories') }}
