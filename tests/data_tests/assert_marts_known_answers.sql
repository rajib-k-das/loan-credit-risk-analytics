-- Known answers for the marts, from the four synthetic test loans (see tests/fixtures/make_fixtures.py).
-- Each check returns a row only if it fails. Skipped when the fixture isn't loaded.

with fixture_loaded as (

    select count(*) > 0 as is_loaded from {{ ref('dim_loan') }} where loan_id like 'FIXTURE%'

),

-- Vintage curve, all bands combined. Data ends 2020-08, so FIXTURE00003 (first payment 2019-12)
-- is observable for 9 months only and drops out of the denominator from month 10.
curve as (

    select
        months_on_book,
        sum(loans_observable)                       as loans_observable,
        sum(cumulative_defaults)                    as defaults,
        sum(cumulative_defaults_excl_forbearance)   as defaults_excl_forbearance,
        sum(cumulative_prepayments)                 as prepayments
    from {{ ref('fct_vintage_curves') }}
    group by months_on_book

),

curve_expected (months_on_book, loans_observable, defaults, defaults_excl_forbearance, prepayments) as (

    values (4, 4, 0, 0, 1), (5, 4, 1, 1, 1), (7, 4, 2, 1, 1), (10, 3, 1, 1, 1)

),

curve_failures as (

    select 'vintage curve, month ' || e.months_on_book as failed_check
    from curve_expected as e
    left join curve as a using (months_on_book)
    where a.loans_observable is distinct from e.loans_observable
       or a.defaults is distinct from e.defaults
       or a.defaults_excl_forbearance is distinct from e.defaults_excl_forbearance
       or a.prepayments is distinct from e.prepayments

),

-- Roll rates: from 30 days, two loans rolled to 60 and one cured.
rolls as (

    select from_bucket, to_bucket, sum(loans) as loans
    from {{ ref('fct_roll_rates') }}
    group by all

),

roll_expected (from_bucket, to_bucket, loans) as (

    values ('30', '60', 2), ('30', 'Current', 1), ('120+', 'REO', 1), ('REO', 'Defaulted', 1), ('Unknown', '30', 1)

),

roll_failures as (

    select 'roll ' || e.from_bucket || ' -> ' || e.to_bucket as failed_check
    from roll_expected as e
    left join rolls as a using (from_bucket, to_bucket)
    where a.loans is distinct from e.loans

),

-- Episodes: the defaulting loan's single episode ends in REO; the forbearance episode cures and is a default
-- only in the raw view; the short 30-day episode cures.
episode_expected (loan_id, start_month, end_month, months, peak, outcome, had_forbearance, reached_default,
                  reached_default_excl_forbearance) as (

    values
    ('FIXTURE00002', date '2019-05-01', date '2019-08-01', 4, 4, 'REO',   false, true,  true),
    ('FIXTURE00003', date '2020-04-01', date '2020-06-01', 3, 3, 'Cured', true,  true,  false),
    ('FIXTURE00004', date '2019-05-01', date '2019-05-01', 1, 1, 'Cured', false, false, false)

),

episode_failures as (

    select 'episode ' || e.loan_id as failed_check
    from episode_expected as e
    left join {{ ref('fct_delinquency_episodes') }} as a
        on a.loan_id = e.loan_id and a.start_month = e.start_month
    where a.end_month is distinct from e.end_month
       or a.months_delinquent_in_episode is distinct from e.months
       or a.peak_months_delinquent is distinct from e.peak
       or a.outcome is distinct from e.outcome
       or a.had_forbearance is distinct from e.had_forbearance
       or a.reached_default is distinct from e.reached_default
       or a.reached_default_excl_forbearance is distinct from e.reached_default_excl_forbearance

),

loan_failures as (

    select 'loan status ' || e.loan_id as failed_check
    from (values ('FIXTURE00001', 'Prepaid'), ('FIXTURE00002', 'Loss exit'),
                 ('FIXTURE00003', 'Active, defaulted'), ('FIXTURE00004', 'Removed')) as e (loan_id, loan_status)
    left join {{ ref('dim_loan') }} as a using (loan_id)
    where a.loan_status is distinct from e.loan_status

),

all_failures as (

    select * from curve_failures
    union all select * from roll_failures
    union all select * from episode_failures
    union all select * from loan_failures

)

select all_failures.*
from all_failures
cross join fixture_loaded
where fixture_loaded.is_loaded
