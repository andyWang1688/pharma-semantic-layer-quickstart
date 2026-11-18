-- 覆盖必须引用同版本岗位和实际医院/产品；不允许孤立关系被 JOIN 静默丢弃。
select a.snapshot_code, a.position_code from {{ ref('stg_position_accounts') }} a
left join {{ ref('stg_positions') }} p using (snapshot_code, position_code)
left join {{ ref('int_hospitals') }} h on h.hospital_code = a.account_code
where p.position_code is null or h.hospital_code is null or a.account_type <> 'hospital'
union all
select a.snapshot_code, a.position_code from {{ ref('stg_position_products') }} a
left join {{ ref('stg_positions') }} p using (snapshot_code, position_code)
left join {{ ref('int_products') }} r using (product_code)
where p.position_code is null or r.product_code is null
union all
select a.snapshot_code, a.position_code from {{ ref('stg_employee_positions') }} a
left join {{ ref('stg_positions') }} p using (snapshot_code, position_code)
left join {{ ref('stg_people') }} r using (employee_code)
where p.position_code is null or r.employee_code is null
