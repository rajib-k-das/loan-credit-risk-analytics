-- One row per delinquency episode: an unbroken run of months 30+ days past due (gaps and islands).
-- Records how long it lasted, how deep it went, whether it happened in forbearance, and how it ended.
--
-- Islands: for consecutive delinquent months, (month number - row number) is constant, so it identifies the run.
-- A month with unknown status breaks a run; the outcome then reads 'Unknown status' (decision 007).

with data_end as (

    select max(reporting_month) as last_reporting_month from {{ ref('int_loan_months') }}

),

loan_months as (

    select
        loan_id,
        vintage_year,
        reporting_month,
        delinquency_bucket,
        months_delinquent,
        is_in_forbearance,
        default_month,
        default_month_excl_forbearance,
        lead(reporting_month)    over loan_timeline as next_reporting_month,
        lead(delinquency_bucket) over loan_timeline as next_delinquency_bucket
    from {{ ref('int_loan_months') }}
    where not is_default_before_first_payment            -- decision 009
    window loan_timeline as (partition by loan_id order by reporting_month)

),

delinquent_months as (

    select
        *,
        date_diff('month', date '1990-01-01', reporting_month)
            - row_number() over (partition by loan_id order by reporting_month)    as island_id
    from loan_months
    where delinquency_bucket in ('30', '60', '90', '120+')

),

episodes as (

    select
        loan_id,
        vintage_year,
        island_id,
        min(reporting_month)                                     as start_month,
        max(reporting_month)                                     as end_month,
        count(*)                                                 as months_delinquent_in_episode,
        max(months_delinquent)                                   as peak_months_delinquent,
        bool_or(is_in_forbearance)                               as had_forbearance,
        arg_max(next_reporting_month, reporting_month)           as next_reporting_month,
        arg_max(next_delinquency_bucket, reporting_month)        as next_delinquency_bucket,
        any_value(default_month)                                 as default_month,
        any_value(default_month_excl_forbearance)                as default_month_excl_forbearance
    from delinquent_months
    group by loan_id, vintage_year, island_id

)

select
    loan_id || '-' || row_number() over (partition by loan_id order by start_month)   as episode_id,
    loan_id,
    vintage_year,
    row_number() over (partition by loan_id order by start_month)                      as episode_number,
    start_month,
    end_month,
    months_delinquent_in_episode,
    peak_months_delinquent,
    case
        when peak_months_delinquent = 1 then '30'
        when peak_months_delinquent = 2 then '60'
        when peak_months_delinquent = 3 then '90'
        else '120+'
    end                                                                                as peak_bucket,
    had_forbearance,
    case
        when next_reporting_month is null and end_month = data_end.last_reporting_month then 'Still delinquent'
        when next_reporting_month is null                                              then 'No further data'
        when next_reporting_month <> end_month + interval 1 month                      then 'Gap in data'
        when next_delinquency_bucket = 'Current'                                       then 'Cured'
        when next_delinquency_bucket = 'Prepaid'                                       then 'Paid off'
        when next_delinquency_bucket = 'REO'                                           then 'REO'
        when next_delinquency_bucket = 'Defaulted'                                     then 'Loss exit'
        when next_delinquency_bucket = 'Removed'                                       then 'Removed'
        else 'Unknown status'
    end                                                                                as outcome,
    coalesce(default_month between start_month and end_month + interval 1 month, false)
                                                                                       as reached_default,
    coalesce(default_month_excl_forbearance between start_month and end_month + interval 1 month, false)
                                                                                       as reached_default_excl_forbearance
from episodes
cross join data_end
