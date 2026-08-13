# Business Aviation Report — Detailed Style Plan

## Purpose and audience

The report should work at two levels:

1. An executive reader can understand the network, the main risks and the
   recommended actions without reading statistical detail.
2. A technical or analytics reader can understand how every chart was produced,
   what statistical concept it uses and what its limitations are.

The main report should contain approximately 12–15 A4 pages, followed by a
technical appendix. All narrative, titles, chart labels and explanations will be
written in English.

## Visual identity

### Page and typography

- A4 portrait, white background.
- Margins: 1.5 cm on all sides.
- Body typeface: Calibri 12 pt.
- Main title: Calibri 24 pt, bold, dark blue.
- Section title: Calibri 18 pt, bold, dark blue.
- Subsection title: Calibri 14 pt, bold, standard blue.
- Figure caption and source: Calibri 9 pt, grey.
- Line spacing: 1.08–1.15; 6 pt after body paragraphs.
- Footer: report name, development period and page number.

### Colour palette

| Role | Colour | Hex |
|---|---|---|
| Primary series and headings | Standard blue | `#5B9BD5` |
| Section bands and callouts | Light blue | `#D9EAF7` |
| Positive/reliable result | Green | `#70AD47` |
| Main dark text/accent | Dark blue | `#1F4E78` |
| Supporting text | Grey | `#667085` |
| Neutral comparison | Light grey | `#A5A5A5` |
| Warning or operational risk | Orange | `#ED7D31` |

Red should be used only for exceptional severe-risk markers. Meaning must never
depend on colour alone: use labels, symbols or patterns as well.

### Chart standards

- White chart area with subtle light-grey grid lines.
- Standard palette order: blue, green, grey, orange, dark blue, yellow.
- Direct labels are preferred over large legends.
- Percentages use one decimal place; delays use one decimal minute.
- Every chart states its denominator and minimum-volume rule.
- Route and operator rankings display the number of flights beside the rate.
- Axes start at zero unless a different scale is essential and clearly marked.
- Avoid 3D effects, gradients, shadows and decorative charts.

## Two complementary page types

### Business insight page

Use for demand, route, operator, airport and reliability findings.

- Top: one-sentence business question.
- Left 60–65%: main chart.
- Right 35–40%: interpretation panel.
- Bottom: one-line data definition and caveat.

The interpretation panel follows the same sequence:

1. **Finding:** what the chart shows.
2. **Meaning:** why it matters operationally.
3. **Action:** what a business team could investigate or change.
4. **Caution:** what the evidence does not prove.

### Statistical explanation page

Use immediately before or beside technically demanding results.

- Light-blue concept band at the top.
- Central explanatory diagram generated with the same plotting library.
- Short sections: “What it is”, “Why it is used”, “How to read it”.
- Small worked example using fictional or rounded numbers.
- Green box for the decision rule; grey box for limitations.

The report should explain at least:

- OTP15 and delay-severity thresholds.
- Median and p90.
- Wilson confidence intervals.
- Volume–reliability quadrants.
- Pearson versus Spearman correlation.
- Null hypothesis, p-value and effect size.
- Benjamini–Hochberg correction for multiple comparisons.
- Delay recovery: departure delay minus arrival delay.

## Proposed report narrative

### 1. Cover and report contract

- Title: “European Scheduled Aviation Performance”.
- Subtitle: “Demand, punctuality and operational recovery across observed periods”.
- Nine monthly snapshots through June 2023; descriptive reporting may use all
  months while model fitting/tuning keeps March and June 2023 as holdouts.

### 2. Executive summary

- Six KPI cards: flights, routes, operators, OTP15, p90 delay and recovery rate.
- Three main findings.
- Three recommended business investigations.
- One limitations statement.

### 3. Data scope and quality

- Data-source diagram from raw files to business KPIs.
- Scope waterfall: raw records → scheduled commercial → physically valid →
  observed arrival delay.
- Observed months timeline, showing that they are snapshots rather than a
  continuous year.
- Data limitations: no passengers, seats, cancellations, diversions or revenue.

### 4. How reliability is measured

- Statistical explanation page.
- OTP15 threshold diagram.
- Median versus p90 illustration.
- Wilson interval example showing how route volume changes uncertainty.

### 5. Network demand

- Flights by observed period.
- Top directional routes.
- Most-connected departure airports.
- Operators with the largest route networks.
- Interpretation should distinguish flights from passenger demand.

### 6. Overall punctuality and severity

- Delay distribution with a visible long tail.
- OTP15, >30 and >60-minute shares.
- Median, p90 and p95.
- Explanation of why the average alone is insufficient.

### 7. Popular routes: volume versus reliability

- Volume–OTP15 quadrant chart.
- Bubble size represents p90 delay; colour represents >30-minute delay rate.
- No route chart may include a route with fewer than two historical flights.
- Table of popular and reliably above-network routes.
- Separate list of popular routes requiring attention.

### 8. Least reliable routes

- Forest plot with OTP15 and Wilson intervals.
- Executive threshold: at least 500 flights and three active periods.
- Broad-monitoring appendix: at least 100 flights and three periods.
- Explain why raw percentages from thin routes are not ranked directly.

### 9. Airline network and reliability

- Flights, routes and airports served.
- OTP15 and p90 delay.
- Route-concentration HHI.
- Reliability versus network breadth scatter plot.
- Explicitly state that `AC Operator` is the operating carrier.
- Future adjusted comparison should control for route, duration, airport and time.

### 10. Airport and time-of-day pressure

- Day × scheduled-hour OTP15 heatmap.
- Separate origin- and destination-airport volume/reliability quadrants.
- Separate Wilson-interval rankings for the most reliable and most problematic
  origin airports.
- Separate Wilson-interval rankings for the most reliable and most problematic
  destination airports.
- Minimum 30 observed flights for airport charts in development; the final
  threshold must be stated in the caption.
- Peak-volume and low-reliability operating windows.
- Interpret as an operational signal, not causal proof of congestion.

### 11. Delay propagation and recovery

- Departure-delay versus arrival-delay hexbin.
- Green equality line.
- Recovery rate among flights departing more than 15 minutes late.
- Route/operator examples with high and low recovery.

### 12. Relationships between variables

- Reduced correlation matrix or ranked correlation table.
- Pearson and Spearman explanation.
- Separate pre-departure and post-event variables visually.
- State that retrospective association does not authorise a variable for the
  T−60 prediction model.

### 13. Hypothesis tests

- One statistical explanation page.
- H0, effect size, p-value, adjusted p-value and practical threshold.
- Core H01: December 2021 and December 2022 have equal arrival OTP15;
  two-proportion z-test and percentage-point difference.
- Core H02: median recovery equals zero for flights departing >15 minutes late;
  paired Wilcoxon and median minutes recovered.
- Core H03: arrival-delay distributions are equal across haul bands;
  Kruskal-Wallis and epsilon squared.
- Candidate H04: OTP15 is independent of origin airport; chi-square and Cramér's V.
- Candidate H05: OTP15 is independent of destination airport; chi-square and Cramér's V.
- Candidate H06: OTP15 is independent of operator; chi-square and Cramér's V,
  with an explicit route-mix warning.
- Candidate H07: each eligible route has stable OTP15 across periods; per-route
  chi-square tests, maximum percentage-point change and Benjamini-Hochberg.
- Candidate H08: delay distributions are equal across departure-hour bands;
  Kruskal-Wallis and epsilon squared.
- Candidate H09: scheduled duration has zero Spearman association with delay.
- Candidate H10: adjusted operator effects are jointly zero after controlling
  for route, time and duration; logistic regression and adjusted odds ratios.
- Do not describe a tiny but significant effect as operationally important.

### 14. Business implications

- High-volume route monitoring priorities.
- Schedule-buffer and turnaround investigations.
- Operator/airport discussions requiring adjusted analysis.
- Data acquisition priorities: consecutive periods first, weather later.

### 15. Limitations and next steps

- Non-continuous monthly snapshots.
- Operated-flight bias.
- No passenger weighting.
- No causal claims.
- Blind test preserved.
- Recommended future data and validation plan.

## Tables and callouts

- Header row: dark blue fill with white text.
- Alternating white and very-light-blue rows.
- Positive differences: green text plus upward/downward symbol as appropriate.
- Warnings: orange left border, not a fully orange table.
- Maximum 10–15 rows in the main report; complete rankings go to the appendix.
- Each table includes “Minimum flights”, “Active periods” and “Denominator”.

## Chart explanation template

Every important chart will be followed by a compact method box:

> **How this chart was generated**  
> Unit of analysis: operated scheduled-commercial flight.  
> Grouping: directional route (`ADEP → ADES`).  
> Metric: arrivals delayed more than 15 minutes / observed arrivals.  
> Reliability protection: minimum 500 flights, three periods and a 95% Wilson interval.  
> Interpretation: higher OTP15 is better; wider intervals mean greater uncertainty.

## Quality assurance

- All displayed values must originate from exported CSV tables.
- Figure captions identify source files and development periods.
- March 2023 must not appear in any analysis table or chart.
- KPI totals must reconcile across the executive page and appendix.
- Word and PDF versions must be rendered and visually inspected page by page.
- Charts must remain understandable in greyscale and at 100% zoom.
- No chart may imply passenger volume or causal effects without the required data.
