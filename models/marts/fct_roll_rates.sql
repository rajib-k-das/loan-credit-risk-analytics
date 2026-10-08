-- Month-to-month transitions between delinquency buckets: how many loans in each bucket moved to each bucket
-- the following month. Summing loans by from_bucket and to_bucket over any period gives a roll-rate matrix.
-- Only consecutive months are paired; loans already paid off, sold or removed have no next month.

with loan_months as (

    select
        loan_id,
        vintage_year,
        reporting_month,
        delinquency_bucket,
        is_in_forbearance,
        current_upb,
        lead(reporting_month)    over loan_timeline as next_reporting_month,
        lead(delinquency_bucket) over loan_timeline as next_delinquency_bucket
    from {{ ref('int_loan_months') }}
    where not is_default_before_first_payment            -- decision 009
    window loan_timeline as (partition by loan_id order by reporting_month)

)

select
    reporting_month                     as from_month,
    vintage_year,
    delinquency_bucket                  as from_bucket,
    next_delinquency_bucket             as to_bucket,
    is_in_forbearance,
    count(*)                            as loans,
    sum(current_upb)                    as upb
from loan_months
where next_reporting_month = reporting_month + interval 1 month
group by all
