-- 保持来源行数与粒度，只统一字段名称和类型。
select sales_id, cast(sales_date as timestamp) as sales_date, hospital_code, product_code, sales_amount, sales_quantity
from {{ source('raw', 'sales') }}
