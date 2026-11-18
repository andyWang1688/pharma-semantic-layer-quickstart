-- 源岗位出现环路时显式失败；闭包模型有 path 防护，构建不会无限递归。
with recursive paths as (
    select snapshot_code, position_code, parent_code, array[position_code] as visited, false as cycle
    from {{ ref('stg_positions') }}
    union all
    select p.snapshot_code, p.position_code, p.parent_code,
        paths.visited || p.position_code, p.position_code = any(paths.visited)
    from paths join {{ ref('stg_positions') }} p
      on p.snapshot_code = paths.snapshot_code and p.position_code = paths.parent_code
    where not paths.cycle
)
select snapshot_code, position_code, 'cycle' as reason from paths where cycle
union all
select c.snapshot_code, c.position_code, 'missing_parent' as reason
from {{ ref('stg_positions') }} c
left join {{ ref('stg_positions') }} p
  on p.snapshot_code = c.snapshot_code and p.position_code = c.parent_code
where c.parent_code is not null and p.position_code is null
