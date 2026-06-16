# CoolShift Method, Formulas, and Assumptions

## Input Model

CoolShift uses the organizer schema:

- `Scenario_Profiles`
- `Appliances`
- `Energy_Assets`
- `Interval_Inputs`
- `Baseline_Schedule`

All required public data is processed at 15-minute resolution. The app also includes one reproducible custom seven-day scenario with fixed deterministic generation rules.

## Baseline Calculation

For each interval:

```text
interval_hours = interval_minutes / 60
cooling_power_kw =
  baseline_ac_units_on * total_ac_rated_power_per_unit_kw
  + baseline_fan_units_on * total_fan_rated_power_per_unit_kw
  + baseline_other_cooling_kw

site_demand_kwh = (cooling_power_kw + non_cooling_load_kw) * interval_hours
```

The same solar, battery, outage, tariff, carbon, comfort, and weather inputs are used for baseline and optimized comparison.

## Dispatch Model

Per interval, demand is served in this order:

1. Solar direct to load.
2. Excess solar charges the battery within `max_charge_kw` and capacity limits.
3. Battery discharges for remaining demand when useful or required, within `max_discharge_kw`, efficiency, and reserve constraints.
4. Grid serves remaining demand only when `grid_available = 1`.
5. If grid is unavailable and energy is still unmet, the interval is marked infeasible.

Battery state of charge is stored at the end of each interval.

## Comfort Model

CoolShift uses a transparent thermal-memory estimator:

```text
indoor_temp =
  previous_indoor_temp * 0.62
  + outdoor_temperature * 0.30
  + solar_gain
  + occupancy_gain
  - cooling_effect
```

Adjustments:

- Low insulation increases heat gain.
- High sun exposure increases daytime gain.
- Occupancy increases internal heat.
- AC capacity lowers estimated indoor temperature.
- Fans improve perceived comfort slightly without direct cooling capacity.

Comfort status:

- `COMFORT_OK`: occupied interval is inside the selected comfort band.
- `WARM`: occupied interval is above comfort max but below unsafe level.
- `UNSAFE_HEAT`: occupied interval is materially above comfort max or heat index is high.
- `UNOCCUPIED`: no comfort penalty unless heat is extreme.
- `INFEASIBLE`: energy/capacity constraints prevent serving required load.

## Optimization Objective

The default objective balances:

- Comfort and safety
- Cost
- Emissions
- Peak demand

The frontend sliders let judges change weights. The optimizer is deterministic for identical inputs and settings.

## Hard Constraints

CoolShift checks:

- One output row per 15-minute timestamp.
- No grid energy while grid is unavailable.
- Battery SOC never below zero or above capacity.
- Battery reserve, charge, and discharge limits respected.
- Appliance quantities respected.
- Setpoints within appliance limits.
- Cost and emissions equal interval grid energy multiplied by tariff and carbon factor.
- Infeasible comfort or unmet load is reported instead of hidden.

## Custom Scenario

`TEAM-CUSTOM` is a seven-day synthetic scenario for a small clinic/community cooling room in Karachi. It is generated from deterministic rules with no random dependency:

- Higher daytime occupancy.
- Midday solar availability.
- Peak evening tariffs.
- Scheduled short grid outages.
- Moderate solar and battery assets.

The generation code is in `backend/coolshift/sample_data.py`.

