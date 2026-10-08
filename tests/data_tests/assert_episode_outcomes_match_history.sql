-- An episode's outcome must agree with the loan's monthly history:
--   'Gap in data'                         -> the loan does report again later (just not the next month)
--   'Still delinquent' / 'No further data' -> the loan has no later month at all
-- (Added after a bug: arg_max skipped the NULL "no next month" and labelled loan endings as gaps.)

with last_months as (

    select loan_id, max(reporting_month) as last_month
    from {{ ref('int_loan_months') }}
    group by loan_id

)

select episodes.episode_id, episodes.outcome, episodes.end_month, last_months.last_month
from {{ ref('fct_delinquency_episodes') }} as episodes
inner join last_months using (loan_id)
where (episodes.outcome = 'Gap in data' and last_months.last_month <= episodes.end_month)
   or (episodes.outcome in ('Still delinquent', 'No further data') and last_months.last_month > episodes.end_month)
