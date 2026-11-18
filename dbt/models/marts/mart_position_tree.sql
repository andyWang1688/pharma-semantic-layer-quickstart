-- 对 Cube 发布稳定实体；业务规则集中在 intermediate，便于 review 血缘。
{{ config(indexes=[
    {'columns': ['snapshot_code', 'ancestor_position_code'], 'type': 'btree'},
    {'columns': ['snapshot_code', 'descendant_position_code'], 'type': 'btree'}
]) }}
select snapshot_code, valid_from, valid_to, is_available, is_current,
    ancestor_position_code, ancestor_position_name, descendant_position_code,
    descendant_position_name, descendant_parent_code, depth
from {{ ref('int_position_tree') }}
