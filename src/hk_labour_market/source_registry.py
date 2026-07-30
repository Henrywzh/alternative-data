"""Version-controlled source registry for the labour-market core history."""

from __future__ import annotations

from dataclasses import dataclass

from .config import CENSTATD_API_URL


@dataclass(frozen=True)
class CenstatdTableSpec:
    dataset_id: str
    table_id: str
    title: str
    expected_latest_age_days: int
    notes: str

    @property
    def source_url(self) -> str:
        return f"{CENSTATD_API_URL}?id={self.table_id}&lang=en&full_series=1"


# Stage 1 deliberately contains only complete, official C&SD history.  The
# table ids and definitions are the source of truth; no dashboard-specific
# aliases or derived indicators belong here.
CORE_CENSTATD_TABLES: tuple[CenstatdTableSpec, ...] = (
    CenstatdTableSpec(
        "labour_force_monthly",
        "210-06101",
        "Statistics on labour force, employment, unemployment and underemployment",
        120,
        "Contains monthly rolling-three-month observations and annual estimates.",
    ),
    CenstatdTableSpec(
        "labour_demand_by_industry",
        "215-16001",
        "Establishments, persons engaged, vacancies and vacancy rate by industry section",
        180,
        "Quarter-end labour-demand survey observations; excludes the civil service.",
    ),
    CenstatdTableSpec(
        "nominal_wage_index_by_industry",
        "220-19001",
        "Nominal wage indices by industry section",
        180,
        "Comparable HSIC Version 2.0 series is kept separate from older classifications.",
    ),
    CenstatdTableSpec(
        "real_wage_index_by_industry",
        "220-19002",
        "Real wage indices by industry section",
        180,
        "C&SD-published real measure; no local CPI deflation is applied.",
    ),
    CenstatdTableSpec(
        "nominal_payroll_index_by_industry",
        "220-19021",
        "Nominal indices of payroll per person engaged by industry section",
        180,
        "Broader compensation measure than the wage index.",
    ),
    CenstatdTableSpec(
        "real_payroll_index_by_industry",
        "220-19022",
        "Real indices of payroll per person engaged by industry section",
        180,
        "C&SD-published real payroll measure.",
    ),
    CenstatdTableSpec(
        "median_earnings_by_industry",
        "210-06316",
        "Median monthly employment earnings by industry of main employment and sex",
        120,
        "Includes annual estimates and monthly rolling-three-month observations.",
    ),
    CenstatdTableSpec(
        "median_earnings_by_occupation",
        "210-06317",
        "Median monthly employment earnings by occupation of main employment and sex",
        120,
        "Occupation series has an explicit C&SD classification break/backcast note.",
    ),
    CenstatdTableSpec(
        "economically_active_household_income",
        "130-06608A",
        "Median monthly household income of economically active households by household size",
        180,
        "Excludes foreign domestic helpers, matching the official table definition.",
    ),
)


STAGE_2_CENSTATD_TABLES: tuple[CenstatdTableSpec, ...] = (
    CenstatdTableSpec(
        "labour_demand_industry_division_sex",
        "215-16003",
        "Establishments, persons engaged and vacancies by industry division and sex",
        180,
        "Detailed industry demand data; includes construction-site observations.",
    ),
    CenstatdTableSpec(
        "employment_by_industry_establishment_size",
        "215-16006",
        "Establishments and persons engaged by industry, establishment size and sex",
        180,
        "Preserves C&SD MPS establishment-size classifications.",
    ),
    CenstatdTableSpec(
        "vacancies_by_industry_occupation",
        "215-16007",
        "Vacancies by industry section and major occupation group",
        180,
        "Occupation classification is C&SD-backcast only from the documented comparable start.",
    ),
    CenstatdTableSpec(
        "construction_workers_vacancies_by_site_type",
        "215-17001",
        "Construction sites, manual workers, vacancies and opportunities by site type",
        180,
        "Preserves public/private sector and construction-site type classifications.",
    ),
    CenstatdTableSpec(
        "construction_workers_vacancy_rate_by_site_type",
        "215-17002",
        "Construction manual-worker averages and vacancy rates by site type",
        180,
        "Preserves public/private sector and construction-site type classifications.",
    ),
    CenstatdTableSpec(
        "construction_workers_vacancies_by_end_use",
        "215-17003",
        "Construction manual workers and vacancies by project end-use",
        180,
        "Preserves public/private sector and project end-use classifications.",
    ),
    CenstatdTableSpec(
        "construction_workers_vacancies_by_site_size",
        "215-17004",
        "Construction manual workers and vacancies by site size",
        180,
        "Preserves public/private sector and site-size classifications.",
    ),
)


STAGE_3_CENSTATD_TABLES: tuple[CenstatdTableSpec, ...] = (
    CenstatdTableSpec(
        "monthly_wage_distribution_by_employment_nature_sex",
        "220-23011",
        "Monthly wage level and distribution by employment nature and sex",
        550,
        "Annual Earnings and Hours Survey (AEHS); includes wage percentiles.",
    ),
    CenstatdTableSpec(
        "hourly_wage_distribution_by_sex_age",
        "220-23022",
        "Hourly wage level and distribution by sex and age group",
        550,
        "AEHS annual hourly-wage percentiles by age and sex.",
    ),
    CenstatdTableSpec(
        "hourly_wage_distribution_by_industry_occupation",
        "220-23025",
        "Hourly wage level and distribution by industry and occupational group",
        550,
        "AEHS annual hourly-wage levels, percentiles and employee counts.",
    ),
    CenstatdTableSpec(
        "employees_by_hourly_wage_industry",
        "220-23027",
        "Employees by employment nature, hourly wage and industry",
        550,
        "AEHS annual hourly-wage-band distribution by industry.",
    ),
    CenstatdTableSpec(
        "weekly_hours_distribution_by_sex_age",
        "220-23031",
        "Weekly working hours by employment nature, sex and age group",
        550,
        "AEHS annual weekly-hours percentiles.",
    ),
    CenstatdTableSpec(
        "weekly_hours_distribution_by_sex_education",
        "220-23032",
        "Weekly working hours by employment nature, sex and education",
        550,
        "AEHS annual weekly-hours percentiles by educational attainment.",
    ),
    CenstatdTableSpec(
        "weekly_hours_distribution_by_sex_occupation",
        "220-23033",
        "Weekly working hours by employment nature, sex and occupation",
        550,
        "AEHS annual weekly-hours percentiles by occupational group.",
    ),
    CenstatdTableSpec(
        "weekly_hours_distribution_by_industry",
        "220-23034",
        "Weekly working hours by employment nature and industry",
        550,
        "AEHS annual weekly-hours percentiles by industry.",
    ),
    CenstatdTableSpec(
        "employees_by_weekly_hours_industry",
        "220-23035",
        "Employees by employment nature, industry and weekly working hours",
        550,
        "AEHS annual weekly-hours-band distribution by industry.",
    ),
)
