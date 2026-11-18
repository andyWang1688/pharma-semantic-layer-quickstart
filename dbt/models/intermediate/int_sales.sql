-- 保留每笔交易，包括金额相同的不同交易；在仓库内统一计算权限配对键。
select sales_id, sales_date, hospital_code, product_code, sales_amount, sales_quantity,
    jsonb_build_array(to_char(sales_date, 'YYYY-MM'), hospital_code, product_code)::text as month_hospital_product_key
from {{ ref('stg_sales') }}
