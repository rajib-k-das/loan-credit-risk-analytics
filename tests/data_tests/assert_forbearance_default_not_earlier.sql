-- Excluding forbearance is a stricter default test, so it can never produce an earlier default than the raw one.

select distinct loan_id, default_month, default_month_excl_forbearance
from {{ ref('int_loan_months') }}
where default_month_excl_forbearance < default_month
