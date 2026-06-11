# Agent Memory Notes

## Pan India Total in City Tables
Always include a **Pan India** total row whenever showing city-wise data (deliveries, bookings, leads, etc.).
- Use `GROUP BY ROLLUP(city)` or wrap city aggregates in an outer sum — never a separate COUNT DISTINCT
- Never show a city table without Pan India

---

## Key Metric Definitions

### Time Period Abbreviations
| Term | Definition |
|------|-----------|
| **MTD** | Month to Date — from 1st of current month to today |
| **STLM** | Same Time Last Month — same date range as MTD but in the previous month |
| **M-1** | Full previous calendar month |
| **WTD** | Week to Date — from Monday of current week to today |
| **QTD** | Quarter to Date — from 1st of current quarter to today |
| **YTD** | Year to Date — from Jan 1 of current year to today |

### Standard Filters
- Exclude luxury: `ll.procurement_category != 'luxury'` (join `sp_web.listing_lead ll on ll.id = cp.sell_lead_id`)
- Delivery Done filter: `ss.description = 'Delivery Done'` on `sp_web.status_status`
- IST adjustment: always add `INTERVAL '330' MINUTE` to UTC timestamps

### FLP (First Listing Price)
- Definition: Last listing price (`pricing_pricevalue`, `label_id=1`, `target_object_type_id=27`) set on or before `listing_date + 5 days`
- Source query: [65034] Lead Lps

### Delivery Metric
- Source table: `sp_web.buy_lead_carpurchase cp`
- Delivery date: `date(cp.delivery_time + INTERVAL '330' MINUTE)`
- Count: `COUNT(DISTINCT cp.sell_lead_id)`

### Demand Token
- Definition: 1st token of `buy_lead`
- When asked for "demand tokens", return the 1st token of `buy_lead`

---

## Price Field Definitions
- **Listing price** = latest price from LP logs: `pricing_pricevalue` where `label_id=1`, `target_object_type_id=27`, `ROW_NUMBER() OVER (PARTITION BY target_object_id ORDER BY created_on DESC) = 1`
- **Selling price** = same as listing price (latest LP) — do NOT subtract coupon
- **Deal amount** = `cp.final_amount` from `buy_lead_carpurchase`
- **Total coupon** = SUM of `discount_value` from `buy_lead_carpurchasecoupon` joined with `coupons_coupon` where `is_applied = 1`

---

## LP Log Query Requirements
When showing listing price logs, always include:
1. **set_by** — join `sp_web.spinny_auth_user sau ON sau.id = pv.created_by_id`, show `sau.full_name`
2. **listing_date** — from the listing CTE
- Always sort by `updated_on DESC` (current/latest price at top)

---

## Column Order for Time Periods
1. **Granularity order**: Day columns first → Week columns → Month columns
2. **Within each granularity**: Latest value comes first (May before Apr before Mar; MTD before STLM; M-1 before M-2)
3. **Standard named-period order**: MTD → STLM → W-1 → M-1 → M-2
Apply to both SQL SELECT and displayed table.

---

## City Grouping Logic
**Always ask "Parent city or demand city?" before running any city-wise query (deliveries, tokens, visits, leads).**

### Parent city (default)
Join: `address_hub → address_locality → address_city ac → address_city ac1 (via ac.parent_city_id = ac1.id)`
Uses ac1 display_name with fallback to ac. Full CASE with Delhi NCR grouping and Others bucket.

### Demand city (only when user explicitly asks)
Join: `listing_lead → listing_leadprofile → address_city ac (via llp.city_id)`
Uses `ac.display_name` directly. Only groups `('Noida','Gurgaon','Delhi','Delhi/NCR','Ghaziabad','Faridabad') → 'Delhi NCR'`. No Others bucket.

---

## Sort Order
- **Time-series** (date/month/week as rows): latest first
- **Cross-sectional** (city/segment as rows, periods as columns): sort by largest time frame column DESC (e.g. M-1 tokens). Pan India always last.

## Query Plan Before Execution
Always show a plan before running any query:
- Source table(s) + Redash query ID
- Key joins and filters
- How each metric is computed
- Time period date ranges
- City logic (parent or demand)

## Query Execution Rules
- Pass SQL directly to `run_query.py` — never create temporary `.py` files
- Pattern: `DORIS_DB="" python scripts/run_query.py "$(cat <<'EOF' ... EOF)"`
- Whenever a new metric/abbreviation is introduced, save it to this file immediately
