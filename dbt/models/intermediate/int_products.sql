-- 产品主档独立于辖区；编码冲突由唯一性测试拒绝。
select distinct product_code, product_name from {{ ref('stg_products') }}
