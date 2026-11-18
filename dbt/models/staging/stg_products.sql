-- 保持来源行数与粒度，只统一字段名称和类型。
select product_code, product_name
from {{ source('raw', 'products') }}
