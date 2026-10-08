-- A loan that has paid off, defaulted out (loss exit) or been removed must have no later monthly rows.

with exits as (

    select loan_id, min(reporting_month) as exit_month
    from {{ ref('int_loan_months') }}
    where zero_balance_code is not null or delinquency_status_code = 'RA'
    group by loan_id

)

select loan_months.loan_id, loan_months.reporting_month, exits.exit_month
from {{ ref('int_loan_months') }} as loan_months
inner join exits using (loan_id)
where loan_months.reporting_month > exits.exit_month
