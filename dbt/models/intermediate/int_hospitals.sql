-- 医院主档独立于组织；在中间层消除完全相同的源记录，编码冲突由唯一性测试拒绝。
select distinct hospital_code, hospital_name, province_name from {{ ref('stg_hospitals') }}
