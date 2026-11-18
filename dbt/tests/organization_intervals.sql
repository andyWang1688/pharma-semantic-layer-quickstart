-- 从树取得唯一版本；区间有效、当前版本恰好一份，未来版本不可用。
with versions as (
    select distinct snapshot_code, valid_from, valid_to, is_available, is_current
    from {{ ref('int_position_tree') }}
)
select snapshot_code from versions
where snapshot_code !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' or valid_to <= valid_from
    or (is_current and not is_available)
union all
select 'current_count' from versions having count(*) filter (where is_current) <> 1
