-- 只在同一版本、同一岗位内组合医院和产品；覆盖关系没有销售金额。
-- 本例沿用客户的“岗内医院集×产品集”口径；独立医院产品例外应使用显式覆盖源。
select distinct a.snapshot_code, a.position_code,
    a.account_code as hospital_code, p.product_code
from {{ ref('stg_position_accounts') }} a
join {{ ref('stg_position_products') }} p using (snapshot_code, position_code)
where a.account_type = 'hospital'
