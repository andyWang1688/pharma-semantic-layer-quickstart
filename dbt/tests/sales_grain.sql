-- Mart 必须保全每笔来源交易和金额；检查主档引用以及金额/数量基础值。
select s.sales_id from {{ ref('stg_sales') }} s
left join {{ ref('mart_sales_fact') }} f using (sales_id)
left join {{ ref('mart_hospital_dimension') }} h on h.hospital_code = s.hospital_code
left join {{ ref('mart_product_dimension') }} p on p.product_code = s.product_code
where f.sales_id is null or f.sales_amount <> s.sales_amount or f.sales_quantity <> s.sales_quantity
    or h.hospital_code is null or p.product_code is null or s.sales_amount < 0 or s.sales_quantity < 0
union all
select f.sales_id from {{ ref('mart_sales_fact') }} f
left join {{ ref('stg_sales') }} s using (sales_id)
where s.sales_id is null
