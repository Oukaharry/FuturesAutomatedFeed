"""
MT5 Comment Parser Module
Parses MT5 trade comments from TradeAccountConnector to extract account info and phase data.

Comment Format: {TradovateAccountNumber}{PhaseSuffix}
Example: MFFUEVSTP326057008_CH1

Phase Suffix Reference:
- _CH1-4: Challenge Trade 1-4
- _FD0: Funded Base (MFFU style)
- _FD1-4: Funded/Payout 1-4
- _DD1-4: Double Dip 1-4
- _FA: Farming/Consistency
- _FA_DDMMYY: Farming with date (e.g., _FA_210126 = Jan 21, 2026)
- _UNK: Unknown phase
"""
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum


class Phase(Enum):
    """Trading phase types."""
    CHALLENGE = "CH"       # Challenge trades
    FUNDED = "FD"          # Funded/Payout trades
    DOUBLE_DIP = "DD"      # Double Dip trades
    FARMING = "FA"         # Farming/Consistency phase
    UNKNOWN = "UNK"        # Unknown phase
    LEGACY = "LEGACY"      # Legacy Combine format


@dataclass
class ParsedComment:
    """Parsed MT5 comment data."""
    account_number: Optional[str] = None
    phase: Optional[Phase] = None
    phase_code: Optional[str] = None  # Raw phase code (CH, FD, DD, FA, UNK)
    trade_number: Optional[int] = None
    farming_date: Optional[datetime] = None
    raw_comment: str = ""
    is_valid: bool = False
    
    def __str__(self):
        if not self.is_valid:
            return f"Invalid: {self.raw_comment}"
        
        date_str = f" ({self.farming_date.strftime('%d/%m/%y')})" if self.farming_date else ""
        trade_str = f" Trade #{self.trade_number}" if self.trade_number else ""
        return f"{self.account_number} | {self.phase.name}{trade_str}{date_str}"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "account_number": self.account_number,
            "phase": self.phase.value if self.phase else None,
            "phase_name": self.phase.name if self.phase else None,
            "phase_code": self.phase_code,
            "trade_number": self.trade_number,
            "farming_date": self.farming_date.isoformat() if self.farming_date else None,
            "raw_comment": self.raw_comment,
            "is_valid": self.is_valid
        }


def get_account_signature(account: str) -> str:
    """
    Generate account signature from first 4 + last 4/5 characters.
    Used for matching truncated account numbers.
    
    Handles truncated format with '...' like: FNFT...59574
    
    Examples:
        MFFUEVSTP326057008 -> mffu7008 (full account)
        FNFT...59574 -> fnft59574 (truncated - use last 5)
        MFFU7008 -> mffu7008 (short account)
    """
    if not account:
        return ""
    account = account.strip()
    
    # Handle truncated format: PREFIX...SUFFIX
    if '...' in account:
        parts = account.split('...')
        if len(parts) == 2:
            prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
            suffix = parts[1]  # Keep full suffix (usually 5 digits)
            return (prefix + suffix).lower()
    
    # Standard format: first 4 + last 4
    if len(account) <= 8:
        return account.lower()
    return (account[:4] + account[-4:]).lower()


@dataclass
class AggregatedTrade:
    """Aggregated trade data for a specific account/phase combination."""
    account_number: str
    phase: Phase
    phase_code: str
    trade_number: Optional[int] = None
    farming_date: Optional[datetime] = None
    total_profit: float = 0.0
    total_commission: float = 0.0
    total_swap: float = 0.0
    total_fee: float = 0.0
    deal_count: int = 0
    deals: List[Dict] = field(default_factory=list)
    
    @property
    def net_profit(self) -> float:
        """Net profit including all costs."""
        return self.total_profit + self.total_commission + self.total_swap + self.total_fee
    
    @property
    def account_signature(self) -> str:
        """Get first4+last4 account signature for matching."""
        return get_account_signature(self.account_number)
    
    def get_key(self) -> str:
        """Get unique key for this aggregation."""
        date_suffix = f"_{self.farming_date.strftime('%d%m%y')}" if self.farming_date else ""
        trade_suffix = str(self.trade_number) if self.trade_number else ""
        return f"{self.account_number}_{self.phase_code}{trade_suffix}{date_suffix}"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "account_number": self.account_number,
            "phase": self.phase.value,
            "phase_name": self.phase.name,
            "phase_code": self.phase_code,
            "trade_number": self.trade_number,
            "farming_date": self.farming_date.isoformat() if self.farming_date else None,
            "total_profit": round(self.total_profit, 2),
            "total_commission": round(self.total_commission, 2),
            "total_swap": round(self.total_swap, 2),
            "total_fee": round(self.total_fee, 2),
            "net_profit": round(self.net_profit, 2),
            "deal_count": self.deal_count,
            "key": self.get_key(),
            "account_signature": self.account_signature
        }


class MT5CommentParser:
    """
    Parser for MT5 trade comments following TradeAccountConnector format.
    
    Comment Format: {TradovateAccountNumber}{PhaseSuffix}
    
    Examples:
        MFFUEVSTP326057008_CH1  -> Account MFFUEVSTP326057008, Challenge Trade 1
        MFFUEVSTP326057008_FD2  -> Account MFFUEVSTP326057008, Funded/Payout 2
        MFFUEVSTP326057008_FA   -> Account MFFUEVSTP326057008, Farming phase
        MFFUEVSTP326057008_FA_210126 -> Farming on Jan 21, 2026
        MFFUEVSTP326057008_DD1  -> Double Dip Trade 1
    """
    
    # Phase mappings by prop firm
    PHASE_MEANINGS = {
        "MFFU": {
            "CH": "Challenge trades",
            "FD0": "Base funded trade",
            "FD": "Payout",
            "DD": "Double Dip",
            "FA": "Farming/Consistency (5 days)"
        },
        "Tradeify": {
            "CH": "Challenge trades",
            "FD": "Payout",
            "DD": "Double Dip",
            "FA": "Consistency"
        },
        "FundingTicks": {
            "CH": "Challenge trades",
            "FD": "Payout",
            "DD": "Double Dip",
            "FA": "Farming (6 days)"
        },
        "AlphaFutures": {
            "CH": "Challenge trades",
            "FD": "Payout",
            "DD": "Double Dip",
            "FA": "Farming"
        }
    }
    
    def __init__(self):
        """Initialize the parser with regex patterns."""
        # Patterns ordered by specificity (most specific first)
        self.patterns = [
            # Numbered phases: _CH1, _FD2, _DD3
            (r'^(.+?)_(CH|FD|DD)(\d+)$', self._parse_numbered_phase),
            # Farming with date: _FA_DDMMYY
            (r'^(.+?)_FA_(\d{6})$', self._parse_farming_with_date),
            # Simple farming: _FA
            (r'^(.+?)_FA$', self._parse_simple_farming),
            # Unknown phase: _UNK
            (r'^(.+?)_UNK$', self._parse_unknown_phase),
            # Legacy Combine format
            (r'^Combine(\d+)_(.*)$', self._parse_legacy_combine),
        ]
    
    def parse(self, comment: str) -> ParsedComment:
        """
        Parse an MT5 trade comment.
        
        Args:
            comment: The MT5 order comment string
            
        Returns:
            ParsedComment object with extracted data
        """
        result = ParsedComment(raw_comment=comment or "")
        
        if not comment:
            return result
        
        comment = comment.strip()
        
        # Try each pattern
        for pattern, handler in self.patterns:
            match = re.match(pattern, comment, re.IGNORECASE)
            if match:
                return handler(match, comment)
        
        # No pattern matched - check if it's just an account number
        # (comment without phase suffix)
        if comment and not comment.startswith("Combine"):
            result.account_number = comment
            result.is_valid = False  # Mark as not fully valid without phase
        
        return result
    
    def _parse_numbered_phase(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse numbered phases: CH, FD, DD with trade number."""
        account = match.group(1)
        phase_code = match.group(2).upper()
        trade_num = int(match.group(3))
        
        phase_map = {
            "CH": Phase.CHALLENGE,
            "FD": Phase.FUNDED,
            "DD": Phase.DOUBLE_DIP
        }
        
        return ParsedComment(
            account_number=account,
            phase=phase_map.get(phase_code, Phase.UNKNOWN),
            phase_code=phase_code,
            trade_number=trade_num,
            raw_comment=comment,
            is_valid=True
        )
    
    def _parse_farming_with_date(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse farming phase with date: _FA_DDMMYY."""
        account = match.group(1)
        date_str = match.group(2)  # DDMMYY format
        
        farming_date = None
        try:
            farming_date = datetime.strptime(date_str, "%d%m%y")
        except ValueError:
            pass
        
        return ParsedComment(
            account_number=account,
            phase=Phase.FARMING,
            phase_code="FA",
            farming_date=farming_date,
            raw_comment=comment,
            is_valid=True
        )
    
    def _parse_simple_farming(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse simple farming phase: _FA."""
        return ParsedComment(
            account_number=match.group(1),
            phase=Phase.FARMING,
            phase_code="FA",
            raw_comment=comment,
            is_valid=True
        )
    
    def _parse_unknown_phase(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse unknown phase: _UNK."""
        return ParsedComment(
            account_number=match.group(1),
            phase=Phase.UNKNOWN,
            phase_code="UNK",
            raw_comment=comment,
            is_valid=True
        )
    
    def _parse_legacy_combine(self, match: re.Match, comment: str) -> ParsedComment:
        """Parse legacy Combine format: Combine{N}_."""
        combinenum = match.group(1)
        rest = match.group(2)
        # Usually Combine1_Account
        return ParsedComment(
            account_number=rest,
            phase=Phase.CHALLENGE,
            phase_code="CH",
            trade_number=int(combinenum),
            raw_comment=comment,
            is_valid=True
        )

    def get_phase_meaning(self, phase_code: str, prop_firm: str = "MFFU") -> str:
        """
        Get human-readable meaning for a phase code.
        
        Args:
            phase_code: Phase code (CH, FD, DD, FA)
            prop_firm: Prop firm name for context-specific meaning
            
        Returns:
            Description of the phase
        """
        firm_meanings = self.PHASE_MEANINGS.get(prop_firm, self.PHASE_MEANINGS["MFFU"])
        return firm_meanings.get(phase_code, f"Unknown phase: {phase_code}")


class MT5DealAggregator:
    """
    Aggregates MT5 deals by account and phase based on comment parsing.
    """
    
    def __init__(self):
        """Initialize the aggregator."""
        self.parser = MT5CommentParser()
        self.aggregations: Dict[str, AggregatedTrade] = {}
        self.unmatched_deals: List[Dict] = []
        self.parse_log: List[str] = []
    
    def reset(self):
        """Reset aggregation state."""
        self.aggregations = {}
        self.unmatched_deals = []
        self.parse_log = []
    
    def add_deal(self, deal: Dict) -> Optional[str]:
        """
        Add a single deal to the aggregation.
        
        Args:
            deal: MT5 deal dictionary with fields like:
                  - comment: Order comment
                  - profit: Deal profit
                  - commission: Commission
                  - swap: Swap charges
                  - fee: Additional fees
                  - type: Deal type (BUY, SELL, BALANCE, etc.)
                  - entry: Entry type (IN, OUT, INOUT)
                  
        Returns:
            Aggregation key if matched, None if unmatched
        """
        # Skip balance/credit operations
        deal_type = str(deal.get('type', '')).upper()
        if deal_type in ['BALANCE', 'CREDIT', '2', '3', 'CHARGE', 'CORRECTION', 'BONUS']:
            return None
        
        # Parse the comment
        comment = deal.get('comment', '')
        parsed = self.parser.parse(comment)
        
        if not parsed.is_valid or not parsed.account_number:
            self.unmatched_deals.append(deal)
            self.parse_log.append(f"⚠️ Unmatched: {comment or '(empty)'}")
            return None
        
        # Get deal date for clustering
        deal_time_str = deal.get('time', '')
        deal_date = None
        try:
            if deal_time_str:
                # Handle ISO format string (YYYY-MM-DDTHH:MM:SS)
                if isinstance(deal_time_str, str):
                    if 'T' in deal_time_str:
                        deal_date = datetime.fromisoformat(deal_time_str).date()
                    else:
                        # Fallback parsing if just YYYY-MM-DD
                        deal_date = datetime.strptime(deal_time_str.split()[0], '%Y-%m-%d').date()
                # Handle timestamp
                elif isinstance(deal_time_str, (int, float)):
                    deal_date = datetime.fromtimestamp(deal_time_str).date()
        except:
            pass # Keep deal_date as None if parsing fails

        # For Farming (FA), if no date in comment, use deal date
        # For Reset Accounts (CH/FD), we also want to separate by date to distinguish resets
        # So we update parsed.farming_date if it's currently None, using the deal date
        
        # Override/Set farming_date for grouping if not present in comment
        if not parsed.farming_date and deal_date:
            # We treat 'farming_date' field as 'grouping_date' effectively
            parsed.farming_date = datetime(deal_date.year, deal_date.month, deal_date.day)

        # Build aggregation key
        key = self._build_key(parsed)
        
        # Create or update aggregation
        if key not in self.aggregations:
            self.aggregations[key] = AggregatedTrade(
                account_number=parsed.account_number,
                phase=parsed.phase,
                phase_code=parsed.phase_code,
                trade_number=parsed.trade_number,
                farming_date=parsed.farming_date
            )
        
        agg = self.aggregations[key]
        agg.total_profit += deal.get('profit', 0) or 0
        agg.total_commission += deal.get('commission', 0) or 0
        agg.total_swap += deal.get('swap', 0) or 0
        agg.total_fee += deal.get('fee', 0) or 0
        agg.deal_count += 1
        agg.deals.append(deal)
        
        return key
    
    def _build_key(self, parsed: ParsedComment) -> str:
        """Build a unique key for an aggregation."""
        parts = [parsed.account_number, parsed.phase_code]
        
        if parsed.trade_number is not None:
            parts.append(str(parsed.trade_number))
        
        # Always append date if available (now populated from deal time too)
        # This breaks simple CH1 aggregation into CH1_Date1, CH1_Date2...
        # Which is exactly what we want for Reset Account handling
        if parsed.farming_date:
            parts.append(parsed.farming_date.strftime('%d%m%y'))
        
        return "_".join(parts)
    
    def process_deals(self, deals: List[Dict]) -> Tuple[Dict[str, AggregatedTrade], List[Dict]]:
        """
        Process a list of deals and aggregate by account/phase.
        
        Args:
            deals: List of MT5 deal dictionaries
            
        Returns:
            Tuple of (aggregations dict, unmatched deals list)
        """
        self.reset()
        
        for deal in deals:
            self.add_deal(deal)
        
        return self.aggregations, self.unmatched_deals
    
    def get_summary(self) -> Dict:
        """Get a summary of the aggregation."""
        return {
            "total_aggregations": len(self.aggregations),
            "total_unmatched": len(self.unmatched_deals),
            "by_phase": self._summarize_by_phase(),
            "by_account": self._summarize_by_account(),
            "parse_log": self.parse_log
        }
    
    def _summarize_by_phase(self) -> Dict[str, Dict]:
        """Summarize aggregations by phase."""
        summary = {}
        for key, agg in self.aggregations.items():
            phase_name = agg.phase.name
            if phase_name not in summary:
                summary[phase_name] = {"count": 0, "total_net_profit": 0.0}
            summary[phase_name]["count"] += 1
            summary[phase_name]["total_net_profit"] += agg.net_profit
        return summary
    
    def _summarize_by_account(self) -> Dict[str, Dict]:
        """Summarize aggregations by account."""
        summary = {}
        for key, agg in self.aggregations.items():
            account = agg.account_number
            if account not in summary:
                summary[account] = {"phases": {}, "total_net_profit": 0.0}
            
            phase_key = f"{agg.phase_code}{agg.trade_number or ''}"
            summary[account]["phases"][phase_key] = agg.net_profit
            summary[account]["total_net_profit"] += agg.net_profit
        
        return summary
    
    def to_dashboard_format(self) -> List[Dict]:
        """
        Convert aggregations to dashboard-compatible format.
        
        Returns list of dicts with:
        - account_number: Account identifier
        - phase: Phase code (CH, FD, DD, FA)
        - trade_number: Trade number (1-4) or None
        - farming_date: Date if farming phase
        - net_profit: Total net profit for this combination
        - deal_count: Number of deals
        """
        result = []
        for key, agg in self.aggregations.items():
            result.append(agg.to_dict())
        return result


def parse_mt5_comment(comment: str) -> Dict:
    """
    Convenience function to parse a single MT5 comment.
    
    Args:
        comment: MT5 order comment string
        
    Returns:
        Dictionary with parsed data:
        - account_number: Tradovate account number
        - phase: Phase code (CH, FD, DD, FA)
        - trade_number: Trade number (1-4) or None for farming
        - farming_date: Date if farming phase with date suffix
        - is_valid: Whether the comment was successfully parsed
    """
    parser = MT5CommentParser()
    result = parser.parse(comment)
    return result.to_dict()


def aggregate_deals_by_comment(deals: List[Dict]) -> Tuple[List[Dict], List[Dict], List[str]]:
    """
    Convenience function to aggregate deals by parsed comments.
    
    Args:
        deals: List of MT5 deal dictionaries
        
    Returns:
        Tuple of (aggregated_data, unmatched_deals, log_messages)
    """
    aggregator = MT5DealAggregator()
    aggregator.process_deals(deals)
    
    return (
        aggregator.to_dashboard_format(),
        aggregator.unmatched_deals,
        aggregator.parse_log
    )


def aggregate_deals_by_position(deals: List[Any]) -> Tuple[List[Dict], List[Dict], List[str]]:
    """
    Aggregate deals by position_id first, then by comment/phase.
    
    Also handles "Farming" cluster logic:
    - If Phase is FARMING (FA) and no date in comment, uses Trade Date (Time).
    
    Args:
        deals: List of MT5 deal objects or dicts
        
    Returns:
        Tuple of (aggregated_data, unmatched_positions, log_messages)
    """
    parser = MT5CommentParser()
    log_messages = []
    
    # Step 1: Group deals by position_id
    positions = {}
    for deal in deals:
        # Handle both MT5 deal objects and dicts
        if hasattr(deal, '_asdict'):
            d = deal._asdict()
        elif hasattr(deal, 'position_id'):
            d = {
                'position_id': deal.position_id,
                'ticket': deal.ticket,
                'comment': deal.comment,
                'profit': deal.profit,
                'commission': getattr(deal, 'commission', 0),
                'swap': getattr(deal, 'swap', 0),
                'fee': getattr(deal, 'fee', 0),
                'entry': deal.entry,
                'type': deal.type,
                'volume': getattr(deal, 'volume', 0),
                'symbol': getattr(deal, 'symbol', ''),
                'time': getattr(deal, 'time', 0),
            }
        else:
            d = deal
        
        pid = d.get('position_id', 0)
        if pid == 0:
            continue  # Skip balance/credit operations
            
        if pid not in positions:
            positions[pid] = []
        positions[pid].append(d)
    
    log_messages.append(f"Found {len(positions)} positions from {len(deals)} deals")
    
    # Step 2: For each position, find entry deal with comment and sum profits
    position_data = []
    unmatched = []
    
    for pid, deal_list in positions.items():
        # Find entry deal (entry=0 is DEAL_ENTRY_IN) with valid comment
        entry_deal = None
        exit_time = 0 
        
        total_profit = 0.0
        total_commission = 0.0
        total_swap = 0.0
        total_fee = 0.0
        
        for d in deal_list:
            # entry: 0=IN, 1=OUT, 2=INOUT, 3=OUT_BY
            if d.get('entry', 1) == 0:  # Entry deal
                entry_deal = d
            
            # Track latest time (exit time)
            t = d.get('time_raw', d.get('time', 0))
            if isinstance(t, str):
                try:
                    t = datetime.fromisoformat(t).timestamp()
                except (ValueError, AttributeError):
                    t = 0
            
            if isinstance(t, (int, float)) and t > exit_time:
                exit_time = t
                
            total_profit += d.get('profit', 0) or 0
            total_commission += d.get('commission', 0) or 0
            total_swap += d.get('swap', 0) or 0
            total_fee += d.get('fee', 0) or 0
        
        # If no entry deal found, try to find any deal with a valid comment
        if not entry_deal:
            for d in deal_list:
                comment = d.get('comment', '')
                if comment and ('CH' in comment or 'FD' in comment or 'FA' in comment or 'DD' in comment):
                    entry_deal = d
                    break
        
        if not entry_deal:
            entry_deal = deal_list[0]  # Fallback to first deal
        
        comment = entry_deal.get('comment', '')
        parsed = parser.parse(comment)
        
        if not parsed.is_valid or not parsed.account_number:
            unmatched.append({
                'position_id': pid,
                'comment': comment,
                'total_profit': total_profit,
                'deal_count': len(deal_list)
            })
            continue
            
        # --- FARMING DATE INFERENCE ---
        # If Phase is FA but no farming_date, use the exit time date
        if parsed.phase_code == 'FA' and not parsed.farming_date:
            if exit_time > 0:
                parsed.farming_date = datetime.fromtimestamp(exit_time) 
        # -----------------------------
        
        position_data.append({
            'position_id': pid,
            'account_number': parsed.account_number,
            'phase': parsed.phase.value if parsed.phase else None,
            'phase_name': parsed.phase.name if parsed.phase else None,
            'phase_code': parsed.phase_code,
            'trade_number': parsed.trade_number,
            'farming_date': parsed.farming_date.isoformat() if parsed.farming_date else None,
            'timestamp': exit_time, # Store timestamp for sorting
            'total_profit': round(total_profit, 2),
            'total_commission': round(total_commission, 2),
            'total_swap': round(total_swap, 2),
            'total_fee': round(total_fee, 2),
            'net_profit': round(total_profit + total_commission + total_swap + total_fee, 2),
            'deal_count': len(deal_list),
            'account_signature': get_account_signature(parsed.account_number),
            'raw_comment': comment
        })
    
    log_messages.append(f"Matched {len(position_data)} positions, {len(unmatched)} unmatched")
    
    # Step 3: Aggregate by account + phase (in case multiple positions have same account/phase)
    # ALSO group by DATE for Farming if not already specific
    aggregated = {}
    
    for pos in position_data:
        key = f"{pos['account_number']}_{pos['phase_code']}{pos['trade_number'] or ''}"
        
        # For Farming, always append Date to key to separate days
        if pos['phase_code'] == 'FA' and pos.get('farming_date'):
            # Convert ISO string back to date for key or use string slice
            # ISO format: YYYY-MM-DDTHH:MM:SS
            date_str = pos['farming_date'][:10] # YYYY-MM-DD
            key += f"_{date_str}"
        elif pos.get('farming_date'):
            # Some other phases might have dates too (rare)
            date_str = pos['farming_date'][:10].replace('-', '')
            key += f"_{date_str}"
        
        if key not in aggregated:
            aggregated[key] = {
                'account_number': pos['account_number'],
                'phase': pos['phase'],
                'phase_name': pos['phase_name'],
                'phase_code': pos['phase_code'],
                'trade_number': pos['trade_number'],
                'farming_date': pos['farming_date'],
                'total_profit': 0.0,
                'total_commission': 0.0,
                'total_swap': 0.0,
                'total_fee': 0.0,
                'net_profit': 0.0,
                'deal_count': 0,
                'position_count': 0,
                'account_signature': pos['account_signature'],
                'key': key,
                'timestamp': pos['timestamp'] # Keep one timestamp
            }
        
        agg = aggregated[key]
        agg['total_profit'] += pos['total_profit']
        agg['total_commission'] += pos['total_commission']
        agg['total_swap'] += pos['total_swap']
        agg['total_fee'] += pos['total_fee']
        agg['net_profit'] += pos['net_profit']
        agg['deal_count'] += pos['deal_count']
        agg['position_count'] += 1
        
        # Update timestamp to latest in group (usually irrelevant for same day)
        if pos['timestamp'] > agg['timestamp']:
            agg['timestamp'] = pos['timestamp']
    
    # Round final values
    for key, agg in aggregated.items():
        agg['total_profit'] = round(agg['total_profit'], 2)
        agg['total_commission'] = round(agg['total_commission'], 2)
        agg['total_swap'] = round(agg['total_swap'], 2)
        agg['total_fee'] = round(agg['total_fee'], 2)
        agg['net_profit'] = round(agg['net_profit'], 2)
    
    return (
        list(aggregated.values()),
        unmatched,
        log_messages
    )


# Example usage and testing
if __name__ == "__main__":
    print("=" * 60)
    print("MT5 Comment Parser - Test Suite")
    print("=" * 60)
    
    # Test comments
    test_comments = [
        "MFFUEVSTP326057008_CH1",      # Challenge Trade 1
        "MFFUEVSTP326057008_CH2",      # Challenge Trade 2
        "MFFUEVSTP326057008_FD0",      # Funded Base
        "MFFUEVSTP326057008_FD1",      # Funded/Payout 1
        "MFFUEVSTP326057008_FD2",      # Funded/Payout 2
        "MFFUEVSTP326057008_DD1",      # Double Dip 1
        "MFFUEVSTP326057008_DD2",      # Double Dip 2
        "MFFUEVSTP326057008_FA",       # Farming (simple)
        "MFFUEVSTP326057008_FA_210126",# Farming with date (Jan 21, 2026)
        "MFFUEVSTP326057008_FA_150226",# Farming with date (Feb 15, 2026)
        "MFFUEVSTP326057008_UNK",      # Unknown phase
        "Combine1_",                    # Legacy format
        "Combine3_some_extra",          # Legacy with extra
        "",                             # Empty
        "RandomComment",                # No phase
        "TRADEIFY98765_CH1",           # Different prop firm
    ]
    
    parser = MT5CommentParser()
    
    print("\n--- Comment Parsing Results ---\n")
    for comment in test_comments:
        result = parser.parse(comment)
        print(f"Input:  '{comment}'")
        print(f"Output: {result}")
        if result.is_valid:
            print(f"  -> Account: {result.account_number}")
            print(f"  -> Phase: {result.phase.name} ({result.phase_code})")
            if result.trade_number:
                print(f"  -> Trade #: {result.trade_number}")
            if result.farming_date:
                print(f"  -> Date: {result.farming_date.strftime('%Y-%m-%d')}")
        print()
    
    # Test deal aggregation
    print("\n--- Deal Aggregation Test ---\n")
    
    test_deals = [
        {"comment": "MFFUEVSTP326057008_CH1", "profit": 150.00, "commission": -2.50, "swap": 0, "fee": 0, "type": "SELL", "entry": "OUT"},
        {"comment": "MFFUEVSTP326057008_CH1", "profit": 75.25, "commission": -1.25, "swap": -0.50, "fee": 0, "type": "BUY", "entry": "OUT"},
        {"comment": "MFFUEVSTP326057008_CH2", "profit": 200.00, "commission": -3.00, "swap": 0, "fee": 0, "type": "SELL", "entry": "OUT"},
        {"comment": "MFFUEVSTP326057008_FD1", "profit": 500.00, "commission": -5.00, "swap": -1.00, "fee": 0, "type": "SELL", "entry": "OUT"},
        {"comment": "MFFUEVSTP326057008_FA_210126", "profit": 50.00, "commission": -1.00, "swap": 0, "fee": 0, "type": "BUY", "entry": "OUT"},
        {"comment": "MFFUEVSTP326057008_FA_210126", "profit": 45.00, "commission": -1.00, "swap": 0, "fee": 0, "type": "BUY", "entry": "OUT"},
        {"comment": "BALANCE", "profit": 10000.00, "type": "BALANCE"},  # Should be skipped
        {"comment": "", "profit": 25.00, "commission": -0.50, "type": "BUY", "entry": "OUT"},  # Unmatched
    ]
    
    aggregated, unmatched, log = aggregate_deals_by_comment(test_deals)
    
    print(f"Aggregated: {len(aggregated)} groups")
    print(f"Unmatched: {len(unmatched)} deals")
    print()
    
    for agg in aggregated:
        print(f"  {agg['key']}: Net ${agg['net_profit']:.2f} ({agg['deal_count']} deals)")
    
    print("\nLog:")
    for entry in log:
        print(f"  {entry}")
    
    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)
