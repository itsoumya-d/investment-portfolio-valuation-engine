"""Investment Book of Record (IBOR) valuation and custodian reconciliation engine.

Provides position lifecycle modeling, mark-to-market valuation across multi-currency
asset classes, realized/unrealized P&L calculation, and automated custodian discrepancy reconciliation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class TradeType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class BreakType(str, Enum):
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    VALUATION_MISMATCH = "VALUATION_MISMATCH"
    MISSING_INTERNAL = "MISSING_INTERNAL"
    MISSING_CUSTODIAN = "MISSING_CUSTODIAN"


@dataclass(frozen=True)
class Transaction:
    instrument_id: str
    asset_class: str
    trade_type: TradeType
    quantity: float
    price: float
    currency: str
    trade_id: str = ""
    timestamp: str = ""


@dataclass
class Position:
    instrument_id: str
    asset_class: str
    quantity: float
    cost_basis: float  # Total cost basis in local currency
    currency: str

    @property
    def unit_cost_basis(self) -> float:
        if abs(self.quantity) < 1e-9:
            return 0.0
        return self.cost_basis / self.quantity


@dataclass(frozen=True)
class MarketQuote:
    instrument_id: str
    price: float
    currency: str


@dataclass(frozen=True)
class ValuationItem:
    instrument_id: str
    asset_class: str
    quantity: float
    unit_price: float
    local_currency: str
    local_market_value: float
    fx_rate_to_base: float
    base_market_value: float
    cost_basis_base: float
    unrealized_pnl_base: float


@dataclass(frozen=True)
class ValuationSummary:
    base_currency: str
    total_market_value: float
    total_cost_basis: float
    total_unrealized_pnl: float
    total_realized_pnl: float
    items: Dict[str, ValuationItem] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationBreak:
    instrument_id: str
    break_type: BreakType
    internal_value: float
    custodian_value: float
    variance: float
    comment: str = ""


class PortfolioValuationEngine:
    """Manages investment portfolio positions, multi-currency valuation, and reconciliation."""

    def __init__(self, base_currency: str = "GBP"):
        self.base_currency = base_currency.upper()
        self._positions: Dict[str, Position] = {}
        self._realized_pnl_base: float = 0.0
        self._transactions: List[Transaction] = []

    @property
    def positions(self) -> Dict[str, Position]:
        return {k: v for k, v in self._positions.items() if abs(v.quantity) > 1e-9}

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl_base

    def _convert_to_base(self, amount: float, currency: str, fx_rates: Dict[str, float]) -> float:
        currency = currency.upper()
        if currency == self.base_currency:
            return amount
        pair = f"{currency}/{self.base_currency}"
        inv_pair = f"{self.base_currency}/{currency}"
        if pair in fx_rates:
            return amount * fx_rates[pair]
        elif inv_pair in fx_rates and fx_rates[inv_pair] != 0:
            return amount / fx_rates[inv_pair]
        raise ValueError(f"Missing FX rate for conversion from {currency} to {self.base_currency}")

    def record_transaction(self, tx: Transaction, fx_rates: Optional[Dict[str, float]] = None) -> None:
        """Applies a transaction to position balances and updates realized P&L on sales."""
        if tx.quantity <= 0 or tx.price < 0:
            raise ValueError("Transaction quantity must be positive and price non-negative")

        self._transactions.append(tx)
        inst_id = tx.instrument_id

        if inst_id not in self._positions:
            self._positions[inst_id] = Position(
                instrument_id=inst_id,
                asset_class=tx.asset_class,
                quantity=0.0,
                cost_basis=0.0,
                currency=tx.currency.upper(),
            )

        pos = self._positions[inst_id]

        if tx.trade_type == TradeType.BUY:
            pos.quantity += tx.quantity
            pos.cost_basis += tx.quantity * tx.price
        elif tx.trade_type == TradeType.SELL:
            if tx.quantity > pos.quantity + 1e-9:
                raise ValueError(
                    f"Insufficient position to sell {tx.quantity} of {inst_id} (held: {pos.quantity})"
                )

            avg_cost = pos.unit_cost_basis
            cost_of_sold = tx.quantity * avg_cost
            proceeds = tx.quantity * tx.price
            realized_local = proceeds - cost_of_sold

            rates = fx_rates or {f"{tx.currency.upper()}/{self.base_currency}": 1.0}
            self._realized_pnl_base += self._convert_to_base(realized_local, tx.currency, rates)

            pos.quantity -= tx.quantity
            pos.cost_basis -= cost_of_sold
            if abs(pos.quantity) < 1e-9:
                pos.cost_basis = 0.0

    def value_portfolio(
        self, quotes: Dict[str, MarketQuote], fx_rates: Dict[str, float]
    ) -> ValuationSummary:
        """Computes mark-to-market portfolio value in base currency."""
        items: Dict[str, ValuationItem] = {}
        total_market_val = 0.0
        total_cost_basis_base = 0.0
        total_unrealized_base = 0.0

        for inst_id, pos in self.positions.items():
            if inst_id not in quotes:
                raise KeyError(f"Missing market quote for position {inst_id}")

            quote = quotes[inst_id]
            price = quote.price
            local_mv = pos.quantity * price

            fx = 1.0
            if quote.currency.upper() != self.base_currency:
                pair = f"{quote.currency.upper()}/{self.base_currency}"
                inv_pair = f"{self.base_currency}/{quote.currency.upper()}"
                if pair in fx_rates:
                    fx = fx_rates[pair]
                elif inv_pair in fx_rates and fx_rates[inv_pair] != 0:
                    fx = 1.0 / fx_rates[inv_pair]
                else:
                    raise ValueError(f"Missing FX rate for {quote.currency} to {self.base_currency}")

            base_mv = local_mv * fx
            base_cost = self._convert_to_base(pos.cost_basis, pos.currency, fx_rates)
            unrealized = base_mv - base_cost

            items[inst_id] = ValuationItem(
                instrument_id=inst_id,
                asset_class=pos.asset_class,
                quantity=pos.quantity,
                unit_price=price,
                local_currency=quote.currency.upper(),
                local_market_value=round(local_mv, 4),
                fx_rate_to_base=fx,
                base_market_value=round(base_mv, 4),
                cost_basis_base=round(base_cost, 4),
                unrealized_pnl_base=round(unrealized, 4),
            )

            total_market_val += base_mv
            total_cost_basis_base += base_cost
            total_unrealized_base += unrealized

        return ValuationSummary(
            base_currency=self.base_currency,
            total_market_value=round(total_market_val, 4),
            total_cost_basis=round(total_cost_basis_base, 4),
            total_unrealized_pnl=round(total_unrealized_base, 4),
            total_realized_pnl=round(self._realized_pnl_base, 4),
            items=items,
        )

    def reconcile_with_custodian(
        self,
        custodian_records: Dict[str, Dict],
        quotes: Dict[str, MarketQuote],
        fx_rates: Dict[str, float],
        qty_tolerance: float = 1e-4,
        value_tolerance: float = 1.0,
    ) -> List[ReconciliationBreak]:
        """Detects breaks between internal IBOR positions and external custodian holdings."""
        breaks: List[ReconciliationBreak] = []
        internal_positions = self.positions
        all_ids = set(internal_positions.keys()) | set(custodian_records.keys())

        for inst_id in sorted(all_ids):
            in_internal = inst_id in internal_positions
            in_custodian = inst_id in custodian_records

            if in_internal and not in_custodian:
                breaks.append(
                    ReconciliationBreak(
                        instrument_id=inst_id,
                        break_type=BreakType.MISSING_CUSTODIAN,
                        internal_value=internal_positions[inst_id].quantity,
                        custodian_value=0.0,
                        variance=internal_positions[inst_id].quantity,
                        comment=f"Position present in internal IBOR but missing from custodian feed",
                    )
                )
                continue

            if not in_internal and in_custodian:
                breaks.append(
                    ReconciliationBreak(
                        instrument_id=inst_id,
                        break_type=BreakType.MISSING_INTERNAL,
                        internal_value=0.0,
                        custodian_value=custodian_records[inst_id].get("quantity", 0.0),
                        variance=-custodian_records[inst_id].get("quantity", 0.0),
                        comment=f"Position reported by custodian but absent from internal IBOR",
                    )
                )
                continue

            int_pos = internal_positions[inst_id]
            cust_rec = custodian_records[inst_id]
            cust_qty = cust_rec.get("quantity", 0.0)

            # Check quantity break
            qty_variance = int_pos.quantity - cust_qty
            if abs(qty_variance) > qty_tolerance:
                breaks.append(
                    ReconciliationBreak(
                        instrument_id=inst_id,
                        break_type=BreakType.QUANTITY_MISMATCH,
                        internal_value=int_pos.quantity,
                        custodian_value=cust_qty,
                        variance=round(qty_variance, 4),
                        comment=f"Quantity mismatch: internal={int_pos.quantity}, custodian={cust_qty}",
                    )
                )

            # Check valuation break if custodian provided market value
            if "market_value_base" in cust_rec and inst_id in quotes:
                quote = quotes[inst_id]
                int_local_mv = int_pos.quantity * quote.price
                fx = 1.0
                if quote.currency.upper() != self.base_currency:
                    pair = f"{quote.currency.upper()}/{self.base_currency}"
                    fx = fx_rates.get(pair, 1.0)
                int_base_mv = int_local_mv * fx
                cust_mv = cust_rec["market_value_base"]
                val_variance = int_base_mv - cust_mv
                if abs(val_variance) > value_tolerance:
                    breaks.append(
                        ReconciliationBreak(
                            instrument_id=inst_id,
                            break_type=BreakType.VALUATION_MISMATCH,
                            internal_value=round(int_base_mv, 2),
                            custodian_value=round(cust_mv, 2),
                            variance=round(val_variance, 2),
                            comment=f"Valuation variance exceeding threshold {value_tolerance}",
                        )
                    )

        return breaks
