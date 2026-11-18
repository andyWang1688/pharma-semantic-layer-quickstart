-- 对 Cube 发布稳定实体；业务规则集中在 intermediate，便于 review 血缘。
{{ config(indexes=[{'columns': ['snapshot_code', 'position_code', 'hospital_code', 'product_code'], 'unique': true, 'type': 'btree'}]) }}
select snapshot_code, position_code, hospital_code, product_code
from {{ ref('int_position_hp') }}
