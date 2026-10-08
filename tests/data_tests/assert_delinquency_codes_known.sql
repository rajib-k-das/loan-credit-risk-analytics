-- Flags delinquency status values this pipeline doesn't know how to map.
-- A warning, not an error: the rows are kept as 'Unknown' and listed here for review.
{{ config(severity = 'warn') }}

select delinquency_status_code, count(*) as row_count
from {{ ref('stg_freddie__performance') }}
where not regexp_full_match(delinquency_status_code, '[0-9]{1,3}|RA|XX')
group by delinquency_status_code
