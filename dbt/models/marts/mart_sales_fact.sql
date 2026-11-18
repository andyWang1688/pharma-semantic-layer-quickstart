-- 对 Cube 发布稳定实体；业务规则集中在 intermediate，便于 review 血缘。
{{ config(indexes=[{'columns': ['month_hospital_product_key', 'sales_date'], 'type': 'btree'}]) }}
select sales_id, sales_date, hospital_code, product_code, sales_amount, sales_quantity,
    month_hospital_product_key
from {{ ref('int_sales') }}
