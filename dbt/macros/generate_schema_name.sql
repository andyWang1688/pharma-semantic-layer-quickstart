{# 独立数据库中使用职责层 schema，避免产生 marts_staging 等默认前缀。 #}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ custom_schema_name | trim if custom_schema_name else target.schema }}
{%- endmacro %}
