-- Month-to-month transitions between credit states (Defaulted is absorbing), for the Markov forecast (decision 005).
-- Same pairing rule as fct_roll_rates (consecutive months only), but on credit_state instead of the reported bucket:
-- a loan that reaches 90 days moves to Defaulted and stays there.

with loan_months as (

    select
        loan_id,
        reporting_month,
        credit_state,
        lead(reporting_month) over loan_timeline as next_reporting_month,
        lead(credit_state)    over loan_timeline as next_credit_state
    from {{ ref('int_loan_months') }}
    where not is_default_before_first_payment            -- decision 009
    window loan_timeline as (partition by loan_id order by reporting_month)

)

select
    reporting_month          as from_month,
    credit_state             as from_state,
    next_credit_state        as to_state,
    count(*)                 as loans
from loan_months
where next_reporting_month = reporting_month + interval 1 month
  and credit_state not in ('Defaulted', 'Prepaid', 'Removed')
group by all
