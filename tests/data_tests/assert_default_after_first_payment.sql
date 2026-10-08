-- A loan shouldn't default before its first payment is due (decision 009).
-- The real data has two such loans out of 200,000; they are flagged, not dropped.
-- Warn while the count is tiny; fail if it grows, which would point to a load or logic problem.
{{ config(warn_if = '>0', error_if = '>20') }}

select distinct loan_id, vintage_year, first_payment_month, default_month
from {{ ref('int_loan_months') }}
where default_month < first_payment_month
