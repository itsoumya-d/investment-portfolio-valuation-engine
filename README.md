# investment-portfolio-valuation-engine

Reference data pipeline and financial portfolio valuation reconciliation engine: models multi-asset investment book of record (IBOR) positions, daily mark-to-market valuations, realized and unrealized P&L calculations, and automated discrepancy reconciliation across heterogeneous custodian feeds.

## Architecture & Guarantees

- **Portfolio Position Tracking (IBOR)**: Maintains position balances across equities, fixed income, and derivatives with point-in-time trade lifecycle tracking.
- **Mark-to-Market Valuation**: Computes portfolio valuations across local and base currencies with automated FX conversion and pricing tolerance checks.
- **P&L Attribution Engine**: Segregates daily realized P&L from price movement and currency impact.
- **Discrepancy Reconciler**: Compares internal transaction journals against external custodian statements with configurable tolerance thresholds.

## Run Tests Locally

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

## CI/CD

Automated GitHub Actions workflow runs unit tests, type-checking, and linting on every push and pull request.
