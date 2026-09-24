"""Report-service history parsing: CSV -> daily P&L merge for reference history."""

from trader_companion.tradovate import TradovateAccount


# Verbatim shape of a live Cash History report response (data field contents).
LIVE_CSV = (
    "Account,Transaction ID,Timestamp,Date,Delta,Amount,Cash Change Type,Currency,Contract\r\n"
    'FTDFYSLX50969754357,660575010003,09/15/2026 07:46:55,2026-09-15,"50,000.00","50,000.00", Fund Transaction,USD,\r\n'
    'FTDFYSLX50969754357,660575010008,09/15/2026 08:54:45,2026-09-15,-2.76,"49,997.24", Exchange Fee,USD,NQU6\r\n'
    'FTDFYSLX50969754357,660575010011,09/15/2026 08:54:45,2026-09-15,-2.58,"49,994.24", Commission,USD,NQU6\r\n'
    'FTDFYSLX50969754357,660575010027,09/15/2026 11:08:05,2026-09-15,"5,400.00","55,388.48", Trade Paired,USD,NQU6\r\n'
    'FTDFYSLX50969754357,660575010059,09/16/2026 12:43:42,2026-09-16,145.00,"55,529.68", Trade Paired,USD,MNQU6\r\n'
)


def test_parse_report_csv_live_format():
    rows = TradovateAccount._parse_report_csv(LIVE_CSV)
    assert len(rows) == 5
    assert rows[3]["Date"] == "2026-09-15"
    assert rows[3]["Delta"] == "5,400.00"
    assert rows[3]["Cash Change Type"] == "Trade Paired"
    assert rows[3]["Contract"] == "NQU6"


def test_parse_report_csv_strips_underscore_prefixes():
    rows = TradovateAccount._parse_report_csv("_tradeDate,_delta\r\n2026-09-15,10\r\n")
    assert rows == [{"tradeDate": "2026-09-15", "delta": "10"}]


def test_parse_report_csv_empty_and_header_only():
    assert TradovateAccount._parse_report_csv(None) == []
    assert TradovateAccount._parse_report_csv("") == []
    assert TradovateAccount._parse_report_csv("_tradeDate,_delta\r\n") == []


def test_daily_pnl_aggregates_live_rows():
    daily = TradovateAccount._daily_pnl_from_report_rows(
        TradovateAccount._parse_report_csv(LIVE_CSV)
    )
    assert set(daily) == {"2026-09-15", "2026-09-16"}
    d15 = daily["2026-09-15"]
    assert d15["trades"] == 1
    assert d15["gross_pnl"] == 5400.0
    assert round(d15["fees"], 2) == -5.34  # exchange fee + commission
    assert d15["balance_eod"] == 55388.48
    d16 = daily["2026-09-16"]
    assert d16["trades"] == 1
    assert d16["gross_pnl"] == 145.0


def test_daily_pnl_ignores_fund_transactions():
    rows = [{"Date": "2026-09-22", "Delta": "-2,995.74", "Amount": "52,995.74",
             "Cash Change Type": "Fund Transaction"}]
    daily = TradovateAccount._daily_pnl_from_report_rows(rows)
    d = daily["2026-09-22"]
    assert d["trades"] == 0
    assert d["gross_pnl"] == 0.0
    assert d["fees"] == 0.0
    assert d["balance_eod"] == 52995.74


def test_daily_pnl_normalizes_us_dates():
    rows = [{"tradeDate": "09/15/2026", "cashChangeType": "TradePaired", "delta": "5"}]
    daily = TradovateAccount._daily_pnl_from_report_rows(rows)
    assert "2026-09-15" in daily


def test_daily_pnl_skips_rows_without_date():
    rows = [{"cashChangeType": "TradePaired", "delta": "5"}]
    assert TradovateAccount._daily_pnl_from_report_rows(rows) == {}


def _bare_account():
    acct = object.__new__(TradovateAccount)
    return acct


def test_chunked_fetch_stops_after_data_then_empty(monkeypatch):
    acct = _bare_account()
    calls = []

    def fake_fetch(report, account, start, end):
        calls.append((start, end))
        return LIVE_CSV if len(calls) == 1 else "Account,Date\r\n"

    acct._report_fetch = fake_fetch
    rows = acct._fetch_report_rows_chunked("Cash History", "FTDFYSLX50969754357")
    assert len(rows) == 5
    assert len(calls) == 2  # first chunk has data, second empty stops the walk


def test_chunked_fetch_stops_on_error(monkeypatch):
    acct = _bare_account()
    calls = []

    def fake_fetch(report, account, start, end):
        calls.append((start, end))
        return None

    acct._report_fetch = fake_fetch
    rows = acct._fetch_report_rows_chunked("Cash History", "X")
    assert rows == []
    assert len(calls) == 1


MNQ_CSV = (
    "Account,Transaction ID,Timestamp,Date,Delta,Amount,Cash Change Type,Currency,Contract\r\n"
    'X,1,09/15/2026 08:54:45,2026-09-15,"5,400.00","55,388.48", Trade Paired,USD,NQU6\r\n'
    'X,2,09/16/2026 12:43:42,2026-09-16,145.00,"55,529.68", Trade Paired,USD,MNQU6\r\n'
    'X,3,09/16/2026 12:43:42,2026-09-16,-1.90,"55,527.78", Commission,USD,MNQU6\r\n'
    'X,4,09/17/2026 09:59:03,2026-09-17,154.00,"55,691.08", Trade Paired,USD,MNQZ6\r\n'
    'X,5,09/22/2026 04:04:41,2026-09-22,"-2,995.74","52,995.74", Fund Transaction,USD,\r\n'
)


def test_mnq_daily_pnl_only_counts_mnq_days():
    rows = TradovateAccount._parse_report_csv(MNQ_CSV)
    days = TradovateAccount._mnq_daily_pnl_from_report_rows(rows)
    assert [d["date"] for d in days] == ["2026-09-16", "2026-09-17"]
    assert days[0]["net_pnl"] == 143.10  # 145.00 - 1.90 fees
    assert days[1]["net_pnl"] == 154.00


def test_mnq_daily_pnl_excludes_nq_only_and_payout_days():
    rows = TradovateAccount._parse_report_csv(MNQ_CSV)
    dates = {d["date"] for d in TradovateAccount._mnq_daily_pnl_from_report_rows(rows)}
    assert "2026-09-15" not in dates  # NQ funded trade, not farming
    assert "2026-09-22" not in dates  # payout withdrawal only
