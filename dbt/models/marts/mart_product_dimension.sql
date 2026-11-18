-- 对 Cube 发布稳定实体；业务规则集中在 intermediate，便于 review 血缘。
select product_code, product_name
from {{ ref('int_products') }}
