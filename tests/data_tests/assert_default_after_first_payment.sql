-- A loan can't default before its first payment is due, and a default ignoring forbearance
-- can never come earlier than the raw default (it uses a stricter test).

select loan_id, first_payment_month, default_month, default_month_excl_forbearance
from {{ ref('int_loan_months') }}
where default_month < first_payment_month
   or default_month_excl_forbearance < default_month
