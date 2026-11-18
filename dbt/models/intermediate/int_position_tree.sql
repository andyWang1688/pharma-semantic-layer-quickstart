-- 岗位树统一保存版本、节点名称和祖先/后代关系；一行是同版的一对岗位。
-- 自身关系 depth=0；直属关系 depth=1；更深层级直接按 depth 查询。
-- 版本区间在同一模型内计算，避免为简单版本目录额外发布两张表。
with recursive versions as (
    select distinct snapshot_code, to_date(snapshot_code || '-01', 'YYYY-MM-DD') as valid_from
    from {{ ref('stg_positions') }}
), periods as (
    select snapshot_code, valid_from, lead(valid_from) over (order by snapshot_code) as valid_to,
        valid_from <= '{{ var("organization_as_of") }}'::date as is_available,
        snapshot_code = max(case when valid_from <= '{{ var("organization_as_of") }}'::date
            then snapshot_code end) over () as is_current
    from versions
), tree as (
    select snapshot_code, position_code as ancestor_position_code,
        position_code as descendant_position_code, 0 as depth, array[position_code] as path
    from {{ ref('stg_positions') }}
    union all
    select t.snapshot_code, t.ancestor_position_code, p.position_code, t.depth + 1, t.path || p.position_code
    from tree t join {{ ref('stg_positions') }} p
      on p.snapshot_code = t.snapshot_code and p.parent_code = t.descendant_position_code
    where not p.position_code = any(t.path)
)
select distinct t.snapshot_code, v.valid_from, v.valid_to, v.is_available, v.is_current,
    t.ancestor_position_code, a.position_name as ancestor_position_name,
    t.descendant_position_code, d.position_name as descendant_position_name,
    d.parent_code as descendant_parent_code, t.depth
from tree t
join periods v using (snapshot_code)
join {{ ref('stg_positions') }} a
  on a.snapshot_code = t.snapshot_code and a.position_code = t.ancestor_position_code
join {{ ref('stg_positions') }} d
  on d.snapshot_code = t.snapshot_code and d.position_code = t.descendant_position_code
