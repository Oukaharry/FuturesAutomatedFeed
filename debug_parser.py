from trader_companion.mt5_comment_parser import MT5CommentParser

parser = MT5CommentParser()

test_comments = [
    "Unknown_UNK",
    "Unknown_CH1",
    "FTDF...23575_FD2",
    "FTDFYSLX...23575_FD2",
    "V2-4047_FA",
    "V2-4047_FA_300126",
    "V2-1797_CH1",
    "MFFUEVSTP326057008_CH1",
    "Unknown_FD2"
]

print("--- Testing Comment Parser ---")
for comm in test_comments:
    parsed = parser.parse(comm)
    print(f"Comment: '{comm}'")
    print(f"  Account: {parsed.account_number}")
    print(f"  Phase: {parsed.phase_code}")
    print(f"  Trade #: {parsed.trade_number}")
    print(f"  Valid: {parsed.is_valid}")
    print("-" * 30)
