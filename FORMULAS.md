# Formulas Documentation

This document outlines the formulas used in the MT5 Hedging Engine codebase, specifically within `utils/data_processor.py`. These formulas are derived from the project's Google Sheet to ensure data consistency between the dashboard and the spreadsheet.

## 1. Derived Metrics (Row-Level Calculations)

These formulas are applied to each row of the fetched Google Sheet data to calculate missing or dependent values.

### Hedge Net (Phase 1)
Calculates the net result for Phase 1 evaluations that have failed.

*   **Condition:** `Status P1` == "Fail" AND `Hedge Result 1` is not blank.
*   **Excel Formula:**
    ```excel
    =IF(OR(ISBLANK(I3), G3<>"Fail"), "", -D3 + I3 + J3+K3+L3+M3)
    ```
    *(Where D=Fee, I..M=Hedge Results 1-5)*
*   **Python Implementation:**
    ```python
    net = -fee + h1 + h2 + h3 + h4 + h5
    ```

### Hedge Net.1 (Funded Phase)
Calculates the net result for the funded phase, accounting for payouts, fees, and hedging results.

*   **Condition 1:** `Status` == "Completed"
    *   **Excel Formula:**
        ```excel
        SUM(Payouts) + SUM(Funded Hedge) + SUM(Phase 1 Hedge) - Fee - Activation Fee + SUM(Hedge Days)
        ```
    *   **Python Implementation:**
        ```python
        val = sum_payouts + sum_funded_hedge + sum_phase1_hedge - fee - activation_fee + sum_hedge_days
        ```

*   **Condition 2:** `Status` == "Fail"
    *   **Excel Formula:**
        ```excel
        SUM(Funded Hedge) + SUM(Phase 1 Hedge) - Fee - Activation Fee
        ```
    *   **Python Implementation:**
        ```python
        val = sum_funded_hedge + sum_phase1_hedge - fee - activation_fee
        ```

---

## 2. Statistics Calculations (Aggregates)

These formulas are used to generate the summary statistics shown on the dashboard (Profitability, Cashflow, Expected Value, etc.).

### Profitability - Completed Section

#### Challenge Fees Completed
Sum of fees for accounts that have ended (Phase 1 failed OR Funded ended).

*   **Excel Formula:**
    ```excel
    =(SUMIF(Fee,P1="Fail") + SUMIF(Fee,Status="Completed") + SUMIF(Fee,Status="Fail")) * -1
    ```
*   **Python Implementation:**
    Sum Fee where `Status P1 == "Fail"` OR `Status == "Fail"` OR `Status == "Completed"` (using OR logic, no double-counting)

#### Hedging Results Completed
Sum of all hedge results for ended accounts.

*   **Excel Formula:**
    ```excel
    =SUMIF(J:N, H="Fail") + SUMIF(U:AA, T="Fail") + SUMIF(U:AA, T="Completed") + SUMIF(J:N, T="Fail") + SUMIF(J:N, T="Completed")
    ```
*   **Parts:**
    - Part 1: P1 hedges (J-N) where Status P1 = "Fail"
    - Part 2: Funded hedges (U-AA) where Status = "Fail" or "Completed"
    - Part 3: P1 hedges (J-N) where Status = "Fail" or "Completed"

#### Farming Results Completed
Sum of Hedge Day columns ONLY where Status = "Completed".

*   **Excel Formula:**
    ```excel
    =SUMIFS(AM:DA, T:T, "Completed")  (alternating columns AM, AO, AQ... DA)
    ```

#### Payouts Completed
Sum of payouts where Status = "Fail" or "Completed".

*   **Excel Formula:**
    ```excel
    =SUMIF(Payout columns, Status="Fail") + SUMIF(Payout columns, Status="Completed")
    ```

#### Net Profit Completed
*   **Excel Formula:**
    ```excel
    =B6+B3+B4+B5+B25
    ```
    Where B3=Challenge Fees (negative), B4=Hedging, B5=Farming, B6=Payouts, B25=Activation Fee (TBD)

---

### Cashflow - In Progress Section

These sum ALL records without status filtering.

#### Challenge Fees In Progress
*   **Excel Formula:**
    ```excel
    =-SUM(Evaluations!D:D)
    ```
    Negative sum of ALL fees in the Fee column.

#### Hedging Results In Progress
*   **Excel Formula:**
    ```excel
    =SUM(Evaluations!J:N) + SUM(Evaluations!U:AA)
    ```
    Sum of ALL hedge result columns (Phase 1 + Funded).

#### Farming Results In Progress
*   **Excel Formula:**
    ```excel
    =SUM(Evaluations!AM:AM, AO:AO, AQ:AQ, ... DA:DA)
    ```
    Sum of ALL Hedge Day columns (34 columns).

#### Payouts In Progress
*   **Excel Formula:**
    ```excel
    =SUM(Evaluations!AC:AC)+SUM(Evaluations!AE:AE)+SUM(Evaluations!AG:AG)+SUM(Evaluations!AI:AI)
    ```
    Sum of ALL payout columns.

#### Net Profit In Progress
*   **Excel Formula:**
    ```excel
    =B16+B13+B14+B15+B25
    ```
    Where B13=Challenge Fees, B14=Hedging, B15=Farming, B16=Payouts, B25=Activation Fee (TBD)

---

### Other Statistics

### Funded Rate
The percentage of evaluations that passed Phase 1.

*   **Formula:**
    ```python
    funded_rate = (total_passed / (total_passed + total_failed)) * 100
    ```

### Average Net Failed (Evaluation)
The average cost/loss of failed evaluations.

*   **Formula:**
    ```python
    avg_net_failed = net_failed_sum / total_failed
    ```

### Average Net Completed (Funded)
The average profit from completed funded accounts.

*   **Formula:**
    ```python
    avg_net_completed = net_completed_sum / completed
    ```

### Expected Value (EV)
A projection of the expected value of a single account based on historical performance.

*   **Formula:**
    ```python
    expected_value = (funded_rate * avg_funded_val) + ((1 - funded_rate) * avg_fail_cost)
    ```
    *   `funded_rate`: % of accounts that pass Phase 1 (as a decimal).
    *   `avg_funded_val`: Average net profit of completed funded accounts.
    *   `avg_fail_cost`: Average net loss of failed evaluations.

---

## 3. Hedging Review Formulas

These formulas compare the Google Sheet data against the raw MT5 trading history.

### Sheet Hedging Results
The total hedging result as recorded in the Google Sheet.

*   **Formula:**
    ```python
    sheet_hedge_total = SUM(Hedge Net) + SUM(Hedge Net.1)
    ```

### Actual Hedging Results (MT5)
The actual profit generated from trading activities on the MT5 account.

*   **Formula:**
    ```python
    actual_profit = SUM(deal.profit + deal.swap + deal.commission)
    ```
    *(Excludes balance operations like deposits/withdrawals)*

### Discrepancy
The difference between the actual MT5 profit and what is recorded in the sheet.

*   **Formula:**
    ```python
    discrepancy = actual_profit - sheet_hedge_total
    ```
    *(Note: This often equals the total fees paid, as the Sheet formula subtracts fees while MT5 raw data does not.)*
