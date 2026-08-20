# %%
import pandas as pd
import numpy as np
import holidays

# --------------------------------------------
# User-defined target year
# --------------------------------------------
target_year = 2025  # Define the target year here

# --------------------------------------------
# Load your 2018 data
# --------------------------------------------
df_2018 = pd.read_csv("inputs/demand_reg_data/demand_reg_factors.csv", index_col=0, parse_dates=True)

# Identify German holidays for 2018
de_holidays_2018 = holidays.Germany(years=[2018])
df_2018['holiday_name'] = df_2018.index.map(lambda d: de_holidays_2018.get(d) if d in de_holidays_2018 else np.nan)
df_2018['day_of_week'] = df_2018.index.day_name()
df_2018['year'] = df_2018.index.year
df_2018['month'] = df_2018.index.month
df_2018['day'] = df_2018.index.day
df_2018['hour'] = df_2018.index.hour

# Compute weekday_in_month for 2018
df_2018 = df_2018.reset_index().rename(columns={'index': 'datetime'})
df_2018['date'] = df_2018['datetime'].dt.date

# Group by date and pick the first entry of each day (should be midnight if data is complete)
daily_2018 = (df_2018
              .groupby('date', as_index=False)
              .first())

# daily_2018 now has one row per day (the first hour of that day)
daily_2018['weekday_in_month'] = daily_2018.groupby(['year', 'month', 'day_of_week']).cumcount() + 1

# Keep only the necessary columns in daily_2018
daily_2018 = daily_2018[['date', 'day_of_week', 'month', 'weekday_in_month', 'holiday_name']]

# Merge weekday_in_month back into df_2018
df_2018 = df_2018.merge(daily_2018, on=['date', 'day_of_week', 'month', 'holiday_name'], how='left')
df_2018.set_index('datetime', inplace=True)

# --------------------------------------------
# Create the target year dataset
# --------------------------------------------
date_target_year = pd.date_range(f'{target_year}-01-01 00:00', f'{target_year}-12-31 23:00', freq='H')
df_target_year = pd.DataFrame(index=date_target_year)

# Identify German holidays for the target year
de_holidays_target_year = holidays.Germany(years=[target_year])
df_target_year['holiday_name'] = df_target_year.index.map(lambda d: de_holidays_target_year.get(d) if d in de_holidays_target_year else np.nan)
df_target_year['day_of_week'] = df_target_year.index.day_name()
df_target_year['year'] = df_target_year.index.year
df_target_year['month'] = df_target_year.index.month
df_target_year['day'] = df_target_year.index.day
df_target_year['hour'] = df_target_year.index.hour

df_target_year = df_target_year.reset_index().rename(columns={'index': 'datetime'})
df_target_year['date'] = df_target_year['datetime'].dt.date

# Group by date for the target year as well
daily_target_year = (df_target_year
                     .groupby('date', as_index=False)
                     .first())

daily_target_year['weekday_in_month'] = daily_target_year.groupby(['year', 'month', 'day_of_week']).cumcount() + 1
daily_target_year = daily_target_year[['date', 'day_of_week', 'month', 'weekday_in_month', 'holiday_name']]

df_target_year = df_target_year.merge(daily_target_year, on=['date', 'day_of_week', 'month', 'holiday_name'], how='left')

# --------------------------------------------
# Matching Logic
# --------------------------------------------
# Create a holiday map for 2018: holiday_name -> date
holiday_map_2018 = (daily_2018
                    .dropna(subset=['holiday_name'])
                    .set_index('holiday_name')['date']
                    .to_dict())

def find_matched_date_2018(row):
    # If holiday in target year, try holiday match
    if pd.notna(row['holiday_name']) and row['holiday_name'] in holiday_map_2018:
        return holiday_map_2018[row['holiday_name']]
    # Non-holiday: match by month, day_of_week, weekday_in_month
    candidates = daily_2018[
        (daily_2018['month'] == row['month']) &
        (daily_2018['day_of_week'] == row['day_of_week']) &
        (daily_2018['weekday_in_month'] == row['weekday_in_month'])
    ]
    if len(candidates) > 0:
        return candidates.iloc[0]['date']
    else:
        # Fallback: first occurrence of that weekday in that month of 2018
        fallback = daily_2018[
            (daily_2018['month'] == row['month']) &
            (daily_2018['day_of_week'] == row['day_of_week'])
        ]
        if len(fallback) > 0:
            return fallback.iloc[0]['date']
        else:
            return np.nan

df_target_year['matched_date_2018'] = df_target_year.apply(find_matched_date_2018, axis=1)

# --------------------------------------------
# Merge the hourly values
# --------------------------------------------
df_2018_for_merge = df_2018.reset_index().copy()
df_2018_for_merge['date'] = df_2018_for_merge['datetime'].dt.date
df_2018_for_merge['hour'] = df_2018_for_merge['datetime'].dt.hour

# Identify the columns representing load values (all except the computed ones)
load_cols = [c for c in df_2018_for_merge.columns if c not in 
             ['datetime','holiday_name','day_of_week','year','month','day','hour','date','weekday_in_month']]

df_target_year = df_target_year.merge(df_2018_for_merge[['date','hour','holiday_name','day_of_week','month','weekday_in_month'] + load_cols],
                                      left_on=['matched_date_2018','hour'],
                                      right_on=['date','hour'], how='left', suffixes=('_target','_2018'))

# Final cleanup
all_columns = ['datetime', 'holiday_name_target', 'day_of_week_target', 'month_target', 'weekday_in_month_target'] + load_cols
df_target_year_final = df_target_year[all_columns].copy()
df_target_year_final.rename(columns={
    'datetime_target': 'datetime',
    'holiday_name_target': 'holiday_name',
    'day_of_week_target': 'day_of_week',
    'month_target': 'month',
    'weekday_in_month_target': 'weekday_in_month'
}, inplace=True)
df_target_year_final.set_index('datetime', inplace=True)

# %% Validation

# 1. Check for NaNs in critical columns of df_target_year_final
print("**Test 1: Check for missing values in critical columns**")
critical_cols = ['holiday_name', 'day_of_week', 'month', 'weekday_in_month']
null_counts = df_target_year_final[critical_cols].isna().sum()
print("Null counts in critical columns:\n", null_counts)
# It's okay for holiday_name to have NaNs (non-holiday days), but day_of_week, month, weekday_in_month should not be NaN.
assert null_counts['day_of_week'] == 0, "Some day_of_week values are missing."
assert null_counts['month'] == 0, "Some month values are missing."
assert null_counts['weekday_in_month'] == 0, "Some weekday_in_month values are missing."
print("-> Pass: No unexpected missing values in critical columns.")

# 2. Check holiday alignment: If a day in target year is a holiday, ensure that
#    the matched 2018 day has the same holiday_name.
print("\n**Test 2: Holiday alignment test**")
df_holidays_target_year = df_target_year[df_target_year['holiday_name_target'].notna()].drop_duplicates(['datetime'])
if not df_holidays_target_year.empty:
    # Merge with df_2018_for_merge to check the 2018 holiday
    holiday_check = df_holidays_target_year.merge(df_2018_for_merge, left_on=['matched_date_2018', 'hour'],
                                                  right_on=['date', 'hour'], how='left', suffixes=('_target', '_2018'))

    # Compare holiday names
    holiday_mismatches = holiday_check[holiday_check['holiday_name_target'] != holiday_check['holiday_name']]
    if not holiday_mismatches.empty:
        print("Holiday mismatches found:\n", holiday_mismatches[['datetime_target','holiday_name_target','holiday_name']])
        raise AssertionError("Holiday mismatch between target year and 2018.")
    else:
        print("-> Pass: All target year holidays matched the correct 2018 holiday.")
else:
    print("-> No holidays found in target year dataset to check, or no holiday data present.")

# 3. Check day-of-week alignment:
#    For a random sample of 1000 hours (or fewer if dataset is small), ensure that the target year day_of_week matches the 2018 source.
print("\n**Test 3: Day-of-week alignment test**")
sample_size = min(1000, len(df_target_year))
sample_target_year = df_target_year.sample(sample_size, random_state=42)
dow_check = sample_target_year.merge(df_2018_for_merge, left_on=['matched_date_2018', 'hour'],
                                     right_on=['date', 'hour'], how='left', suffixes=('_target', '_2018'))

dow_alignment_rate = (dow_check['day_of_week_target'] == dow_check['day_of_week']).mean()
print(f"Day-of-week alignment rate: {dow_alignment_rate:.2%}")
assert dow_alignment_rate > 0.9, "Day-of-week alignment rate is less than 99%."
print("-> Pass: Day-of-week alignment is excellent.")

# 4. Check nth weekday alignment:
#    Confirm that the weekday_in_month also aligns.
print("\n**Test 4: Nth weekday-of-month alignment test**")
nth_alignment_rate = (dow_check['weekday_in_month_target'] == dow_check['weekday_in_month']).mean()
print(f"Nth weekday-of-month alignment rate: {nth_alignment_rate:.2%}")
assert nth_alignment_rate > 0.9, "Nth weekday-of-month alignment rate is less than 99%."
print("-> Pass: Nth weekday-of-month alignment is excellent.")

# 5. Check month alignment:
#    Confirm that the matched dates come from the same month in 2018.
month_alignment_rate = (dow_check['month_target'] == dow_check['month']).mean()
print("\n**Test 5: Month alignment test**")
print(f"Month alignment rate: {month_alignment_rate:.2%}")
assert month_alignment_rate > 0.9, "Month alignment rate is less than 99%."
print("-> Pass: Month alignment is excellent.")

# 6. Check no unmapped hours:
#    Confirm that all rows in df_target_year_final got a match from 2018 (no missing load data).
print("\n**Test 6: Check for any unmapped hours**")
region_cols = [c for c in df_target_year_final.columns if c not in ['holiday_name','day_of_week','month','weekday_in_month']]
missing_values = df_target_year_final[region_cols].isna().sum().sum()
assert missing_values == 0, f"Found {missing_values} missing region values. Some hours were not matched."
print("-> Pass: All hours in target year have mapped region values from 2018.")

# 7. Optional: Compare distributions:
#    Check if the overall distribution of day-of-week counts matches between target year and 2018.
print("\n**Test 7: Distributional check of day counts**")
dow_counts_target_year = df_target_year_final['day_of_week'].value_counts().sort_index()
dow_counts_2018 = df_2018['day_of_week'].value_counts().sort_index()

print("Day-of-week distribution in target year:\n", dow_counts_target_year)
print("Day-of-week distribution in 2018:\n", dow_counts_2018)

# They won't be identical because calendars differ, but should be similar in pattern.
# For example, the ratio of Mondays to Tuesdays should be in a similar ballpark.
ratios = (dow_counts_target_year / dow_counts_2018).fillna(0)
print("Ratio of day-of-week counts (target year/2018):\n", ratios)
# No strict assertion here, just a sanity check. Ratios close to 1 indicate similar patterns.
if (ratios < 0.5).any() or (ratios > 1.5).any():
    print("Warning: Day-of-week frequency ratios differ significantly. Check the calendar differences.")
else:
    print("-> Day-of-week frequency distribution is reasonably aligned, considering calendar differences.")

print("\nAll validation tests completed.")

# %%
# drop also unrelevant columns
df_target_year_final.drop(['holiday_name', 'day_of_week', 'month', 'weekday_in_month'], axis=1, inplace=True)

# Merge Berlin into Brandenburg
df_target_year_final["BB"] = df_target_year_final["BB"] + df_target_year_final["BE"]

# Merge Bremen into Niedersachsen
df_target_year_final["NI"] = df_target_year_final["NI"] + df_target_year_final["HB"]

# Merge Hamburg into Schleswig-Holstein
df_target_year_final["SH"] = df_target_year_final["SH"] + df_target_year_final["HH"]

# Now drop the merged columns
df_target_year_final = df_target_year_final.drop(columns=["BE", "HB", "HH"])

# localize the index to UTC
df_target_year_final = df_target_year_final.tz_localize('UTC')

# save the final dataset
df_target_year_final.to_csv(f"inputs/demand_reg_data/demand_reg_factors_{target_year}.csv")
print("Final dataset saved.")
# %%
