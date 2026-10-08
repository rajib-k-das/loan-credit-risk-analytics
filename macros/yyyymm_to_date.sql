{#- Freddie Mac dates are 'YYYYMM' text; return the first day of that month, or null when blank. -#}
{% macro yyyymm_to_date(column) -%}
    case
        when trim({{ column }}) similar to '[0-9]{6}'
            then make_date(cast(substr({{ column }}, 1, 4) as integer), cast(substr({{ column }}, 5, 2) as integer), 1)
    end
{%- endmacro %}
