-- A loan that has a zero balance code (paid off, sold, REO disposition, removed) must have no later monthly rows.
-- Note: REO acquisition ('RA') is not an exit. Those loans keep reporting until the property is sold (code 09).

with exits as (

    select loan_id, min(reporting_month) as exit_month
    from {{ ref('int_loan_months') }}
    where zero_balance_code is not null
    group by loan_id

)

select loan_months.loan_id, loan_months.reporting_month, exits.exit_month
from {{ ref('int_loan_months') }} as loan_months
inner join exits using (loan_id)
where loan_months.reporting_month > exits.exit_month
