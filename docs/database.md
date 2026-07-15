# Database

The platform uses a single local SQLite file, `data/trading_platform.db` (`DB_PATH` / `DATABASE_PATH`). There is no ORM: `core/database/database.py` owns connection handling (`get_connection`) and idempotent schema creation/migration (`initialise_database`, `add_column_if_missing`). Domain-specific persistence lives in flat, table-scoped modules that hand-write SQL against that connection - `core/scanner/scanner_repository.py`, `core/execution/trade_queue.py`, `core/execution/paper_trader.py` (legacy), and `core/execution/paper_orders_repository.py` (used by `PaperTradingService`) - rather than a generic repository/DAO base class.

Schema changes are always additive: `initialise_database()` is safe to call repeatedly (`CREATE TABLE IF NOT EXISTS` + `PRAGMA table_info`-guarded `ALTER TABLE ... ADD COLUMN`), and no existing table or column has ever been renamed or removed.

## Tables

### `account_state`
Singleton paper-account row (`id` is `CHECK`-constrained to `1`).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | always `1` |
| `starting_balance` | REAL | set once at account creation |
| `cash` | REAL | mutated by every fill |
| `updated_at` | TEXT | |
| `realised_pnl` | REAL | added for `PaperTradingService`; cumulative net P&L across closed trades, cross-checked by `reconcile()` against `SUM(paper_trades.net_pnl)` |
| `reserved_cash` | REAL | added for `PaperTradingService`; always `0` in this milestone (no working/partially-filled orders hold cash aside yet) |

### `paper_positions`
One row per open symbol (`symbol` is the primary key - no lot/tranche tracking, no short positions).

| Column | Type | Notes |
|---|---|---|
| `symbol` | TEXT PK | |
| `shares`, `entry_price`, `current_price`, `market_value`, `unrealised_pnl`, `updated_at` | | original columns; `entry_price` is a weighted average on adds |
| `stop_loss`, `take_profit`, `trailing_stop` | REAL | migrated in by the original paper-trading milestone; `trailing_stop` is legacy-`PaperTrader`-only, `PaperTradingService` does not read/write it |
| `realised_pnl` | REAL | added for `PaperTradingService`; accumulates P&L from partial closes while the position stays open (reset implicitly when the row is deleted on a full close and a fresh position is later opened) |
| `opened_at` | REAL | added for `PaperTradingService`; distinct from `updated_at`, which the legacy `PaperTrader` already mutates on every price refresh |
| `strategy_name`, `strategy_mode` | TEXT | added for `PaperTradingService`; carried from the `TradingDecision`/order that opened the position |

### `paper_trades`
Flat, append-only fill ledger - one row per fill (both entries and exits), written by both the legacy `PaperTrader` and `PaperTradingService`.

| Column | Type | Notes |
|---|---|---|
| `id`, `timestamp`, `symbol`, `side`, `shares`, `price`, `value`, `cash_after_trade` | | original columns |
| `order_id` | INTEGER | added for `PaperTradingService`; links a fill back to `paper_orders.id` (nullable - legacy `PaperTrader` rows have none) |
| `entry_price`, `gross_pnl`, `fees`, `net_pnl`, `exit_reason` | REAL/TEXT | added for `PaperTradingService`; populated **only on exit fills**, turning that row into a round-trip trade record. Entry-only fill rows leave these `NULL`. `PaperTradingService.get_trades()` returns exactly the rows where `exit_reason IS NOT NULL`. |
| `strategy_name`, `strategy_mode` | TEXT | added for `PaperTradingService` |

### `paper_orders` (new)
The validated order lifecycle (`CREATED -> VALIDATED -> SUBMITTED -> FILLED`, or `REJECTED`/`CANCELLED`/`EXPIRED`) that did not exist before this milestone - distinct from `trade_queue`, which is a pre-execution staging status only.

| Column | Type |
|---|---|
| `id` | INTEGER PK |
| `symbol`, `side`, `quantity`, `order_type` | |
| `requested_price`, `stop_loss`, `take_profit` | REAL |
| `strategy_name`, `strategy_mode`, `source_reference` | TEXT |
| `status`, `rejection_reason` | TEXT |
| `fill_price`, `fill_timestamp`, `fees` | |
| `created_at`, `updated_at` | TEXT |

### `paper_audit_events` (new)
Append-only audit trail of order/position lifecycle events (`ORDER_CREATED`, `ORDER_VALIDATED`, `ORDER_SUBMITTED`, `ORDER_FILLED`, `ORDER_REJECTED`, `ORDER_CANCELLED`, `POSITION_CLOSED`), used for diagnostics.

| Column | Type |
|---|---|
| `id` | INTEGER PK |
| `timestamp`, `event_type` | TEXT |
| `symbol` | TEXT, nullable |
| `order_id` | INTEGER, nullable |
| `details` | TEXT, nullable |

### `trade_queue`
Unchanged pre-execution staging table (`status`: `"PENDING"` on insert, then free-text via `update_trade_status`). `PaperTradingService.process_queue()` reads `PENDING` rows via the existing `get_pending_trades`/`update_trade_status` functions (reused, not reimplemented) and marks each `EXECUTED` or `REJECTED` after attempting to turn it into a paper order.

### `scanner_results`
Unchanged; unrelated to paper trading.

## Atomicity

Every multi-step paper-trading state change (debit/credit cash, upsert/delete the position, write the fill/trade row, update the order's status) is performed inside a single connection/transaction in `core/execution/paper_orders_repository.py` (`apply_entry_fill`, `apply_exit_fill`), with a `rollback()` on any failure before the exception propagates as `PaperTradingPersistenceError`. This is an approved correctness fix relative to the legacy `PaperTrader.buy()`/`sell()`, which perform the position/cash update and the `paper_trades` insert as two separate connections/commits with no rollback path; `paper_trader.py` itself is left untouched.

## Test isolation

No test in this repository may use the default `db_path` (`data/trading_platform.db`). Every `PaperTradingService`/repository-function test passes an explicit `tmp_path`-derived SQLite file.
