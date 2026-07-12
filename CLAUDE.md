# AI Trading Platform — Claude Development Instructions

## Architectural Self Review

Before presenting any implementation:

1. Review the implementation against SOLID principles.
2. Identify unnecessary complexity.
3. Identify hidden coupling.
4. Identify possible future bottlenecks.
5. Compare your chosen design with at least one alternative.
6. Explain why your chosen solution is preferable.
7. Identify any technical debt introduced.
8. Recommend one future improvement that is intentionally deferred.
9. Confirm the implementation follows the repository architecture.
10. State whether you would merge this implementation into production yourself.

Do not stop after making the code compile.
Review it like a Senior Software Architect.

## 1. Project purpose

This repository contains a modular AI-assisted trading platform.

The platform is being developed to support:

- market research;
- market scanning;
- strategy development;
- historical backtesting;
- strategy optimisation;
- paper trading;
- broker integration;
- portfolio management;
- risk management;
- analytics;
- machine-learning models;
- controlled live trading.

The system must prioritise correctness, maintainability, testability, safety, and auditable trading decisions.

---

## 2. Required working process

Before changing any code:

1. Inspect the repository structure.
2. Read `README.md`.
3. Read `CHANGELOG.md`.
4. Read all relevant files under `docs/`.
5. Read the files directly involved in the requested task.
6. Identify existing implementations before proposing new files.
7. Explain the current behaviour.
8. Present a concise implementation plan.

Do not modify files until the existing implementation and dependencies have been understood.

During implementation:

1. Make the smallest coherent change that fully completes the task.
2. Preserve existing working behaviour unless the task explicitly requires a change.
3. Avoid unrelated refactoring.
4. Do not duplicate functionality that already exists.
5. Use existing project patterns where they are suitable.
6. Maintain backward compatibility where reasonable.
7. Add or update tests for behavioural changes.
8. Update documentation when architecture or usage changes.

After implementation:

1. Show every changed file.
2. Summarise the purpose of each change.
3. Run targeted tests.
4. Run the full available test suite.
5. Run formatting, linting and type checking where configured.
6. Report all commands executed.
7. Report passed tests, failed tests and unresolved warnings.
8. Do not commit, push or merge unless explicitly instructed.

---

## 3. Approval boundaries

Do not perform any of the following without explicit permission:

- commit changes;
- push branches;
- merge pull requests;
- delete large sections of working code;
- remove configuration options;
- introduce paid external services;
- change broker credentials;
- enable live trading;
- submit real orders;
- modify production infrastructure;
- expose secrets;
- rewrite Git history.

When uncertain, stop before the destructive or irreversible action and clearly explain the decision required.

---

## 4. Architectural boundaries

Use the following separation of responsibilities.

### `main.py`

`main.py` must remain a minimal application entry point.

It may:

- initialise the application;
- load the selected runtime mode;
- handle top-level exceptions;
- start the application;
- perform safe shutdown.

It must not contain:

- strategy calculations;
- indicator calculations;
- broker-specific logic;
- portfolio logic;
- risk calculations;
- database queries;
- dashboard business logic.

### `config/`

Contains:

- default settings;
- runtime settings;
- environment-specific configuration;
- validation;
- persistent configuration management.

Configuration code must not contain trading decisions.

### `core/`

Contains broker-independent trading-domain logic.

This includes:

- market-data models;
- indicators;
- strategies;
- signals;
- scanning;
- backtesting;
- optimisation;
- risk management;
- portfolio logic;
- orders;
- execution interfaces.

The `core` package must not depend directly on Streamlit, FastAPI or a specific broker SDK.

### `brokers/`

Contains broker adapters and broker-specific integrations.

Each broker must implement a shared broker interface.

Supported or planned adapters include:

- paper broker;
- Interactive Brokers;
- OANDA;
- Alpaca.

Broker-specific models must be mapped into shared internal domain models before reaching the core system.

### `services/`

Contains application-level orchestration.

Services coordinate:

- data retrieval;
- strategies;
- scanning;
- backtesting;
- risk;
- portfolio management;
- execution;
- analytics;
- notifications.

Services should orchestrate domain components rather than duplicate their logic.

### `database/`

Contains:

- database connections;
- sessions;
- persistence models;
- repositories;
- migrations.

Trading-domain components must not perform raw database operations directly.

### `dashboard/`

Contains the Streamlit user interface.

The dashboard may:

- display data;
- collect user input;
- call application services;
- display errors and status information.

The dashboard must not implement core trading logic.

### `api/`

Contains FastAPI routes, request schemas, dependencies and middleware.

API routes must call services rather than contain trading logic.

### `ai/`

Contains:

- feature engineering;
- datasets;
- model training;
- inference;
- sentiment analysis;
- market-regime detection;
- model registry functionality.

AI predictions must never bypass strategy validation, portfolio checks or risk controls.

### `analytics/`

Contains:

- returns analysis;
- risk metrics;
- drawdown analysis;
- trade metrics;
- attribution;
- benchmarking;
- reporting.

### `tests/`

Tests should be separated into:

- unit;
- integration;
- functional;
- regression;
- performance;
- end-to-end.

---

## 5. Runtime modes

The platform should support clearly separated runtime modes:

- `research`;
- `scanner`;
- `backtest`;
- `optimisation`;
- `paper`;
- `live`.

Each runtime mode must have an explicit handler or service.

Runtime routing must not rely on a long chain of loosely controlled `if` statements inside `main.py`.

Invalid runtime modes must fail with a clear configuration error.

Live mode must remain disabled by default.

---

## 6. Strategy architecture

Every strategy must implement a shared strategy interface.

A strategy should define:

- unique name;
- version;
- description;
- required indicators;
- required data columns;
- configurable parameters;
- validation rules;
- signal-generation method.

Strategies must not:

- submit broker orders directly;
- access broker credentials;
- alter portfolio balances;
- bypass signal validation;
- bypass risk controls;
- perform raw database writes.

Use the strategy registry to locate and instantiate strategies.

Do not add large `if/elif` blocks for selecting strategies.

Example intended flow:

```text
Strategy Registry
    -> Strategy Factory
    -> Strategy Instance
    -> Candidate Signal
    -> Signal Validation
    -> Risk Validation
    -> Portfolio Validation
    -> Order Creation
    -> Execution