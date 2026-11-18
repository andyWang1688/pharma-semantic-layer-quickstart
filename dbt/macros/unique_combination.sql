{# 直接检验复合业务键，避免为了测试向业务模型添加无意义的技术列。 #}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as row_count
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
