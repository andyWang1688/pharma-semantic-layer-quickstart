-- 对 Cube 发布稳定实体；业务规则集中在 intermediate，便于 review 血缘。
select hospital_code, hospital_name, province_name
from {{ ref('int_hospitals') }}
