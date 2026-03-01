# Technology Stack Breakdown

## Overview
The system is split into two independent applications that communicate over HTTP:

1. **Dashboard** — a web server (cloud-hosted) that stores and serves all client trading data
2. **Trader Companion** — a Windows desktop app that connects to MetaTrader 5 and pushes data to the dashboard

---

## BACKEND

### Web Framework
| Technology | Purpose |
|---|---|
| **Flask** `>=3.0.0` | Core Python web framework. Handles all HTTP routing, request/response lifecycle, template rendering, and JSON APIs |
| **Gunicorn** `>=21.2.0` | Production WSGI server. Runs the Flask app in production with multi-process worker support |
| **gevent** `>=23.9.1` | Async worker library for Gunicorn. Allows high-concurrency handling of many simultaneous connections |

### Database
| Technology | Purpose |
|---|---|
| **SQLite** (built-in) | Development/lightweight database. Stores all client data, sessions, API keys, audit logs, and version history in `dashboard.db` |
| **psycopg2-binary** `>=2.9.9` | PostgreSQL driver for production deployments. Replaces SQLite in cloud environments |
| **Flask-SQLAlchemy** `>=3.1.1` | ORM layer for database model definitions and query building |
| **Flask-Migrate** `>=4.0.5` | Database migration manager (wraps Alembic). Handles schema changes across environments without data loss |

### Caching & Sessions
| Technology | Purpose |
|---|---|
| **Redis** `>=5.0.0` | In-memory store used for rate limiting state, caching, and session storage in production |
| **Flask-Caching** `>=2.1.0` | Caching decorator layer on top of Redis. Reduces DB hits for frequently read data |
| **Flask-Session** `>=0.5.0` | Server-side session storage. Session tokens are stored in Redis, not in the browser cookie |

### Rate Limiting & Security
| Technology | Purpose |
|---|---|
| **Flask-Limiter** `>=3.5.0` | Per-route rate limiting (e.g. 5 rollbacks/hour, 60 API calls/minute). Prevents abuse |
| **python-dotenv** `>=1.0.0` | Loads `.env` files so secrets (API keys, DB passwords) are never hardcoded |
| **cryptography** `>=41.0.0` | Enhanced encryption for data-at-rest and secure token handling |
| **hashlib** (built-in) | SHA-256 hashing of passwords and API keys before storage |
| **secrets** (built-in) | Cryptographically secure random token generation for sessions and API keys |

### Data Processing
| Technology | Purpose |
|---|---|
| **pandas** `>=2.0.0` | Data manipulation for Google Sheets imports, column normalization, and evaluation processing |
| **openpyxl** | Excel/spreadsheet file parsing — used when importing evaluation data from `.xlsx` files |
| **requests** `>=2.31.0` | HTTP client — used server-side to fetch Google Sheets data and call external APIs |

### Scheduling
| Technology | Purpose |
|---|---|
| **threading** (built-in) | Background thread scheduler for the midnight watermark update job (`scheduler.py`) |
| **datetime / timedelta** (built-in) | Date arithmetic for watermark periods, session expiry, and history timestamping |

### Monitoring & Logging
| Technology | Purpose |
|---|---|
| **logging** (built-in) | Structured application logging to both console and `server.log`. Custom `UnbufferedFileHandler` forces disk flush after every log write |
| **structlog** `>=23.2.0` | Structured/JSON-formatted logging for production log aggregation |
| **sentry-sdk[flask]** `>=1.34.0` | Error tracking and alerting — captures unhandled exceptions with full stack traces |

### Testing
| Technology | Purpose |
|---|---|
| **pytest** `>=7.4.0` | Test framework. Runs all unit and integration tests |
| **pytest-flask** `>=1.2.0` | Flask-specific test helpers (test client, request context) |
| **coverage** `>=7.3.0` | Measures what percentage of code is covered by tests |

### Internal Python Modules (Custom)
| Module | Purpose |
|---|---|
| `dashboard/database.py` | All DB operations: client data CRUD, session management, API key hashing, audit log, version history, rollback |
| `dashboard/financial_overview.py` | Financial calculations — prop firm P&L, payout history, portfolio growth curves, trader stats |
| `dashboard/notes_service.py` | Per-cell sticky note storage and retrieval (stored separately from evaluation data) |
| `dashboard/scheduler.py` | Midnight watermark snapshot job — records daily profit high/low watermarks |
| `dashboard/watermark_service.py` | Watermark business logic — bi-weekly period calculation and tracking |
| `dashboard/phase_manager.py` | Trading phase (Eval → Funded → Farming) transition detection and status management |
| `dashboard/utils/trade_matcher.py` | `UnifiedTradeMatcher` — matches MT5 deal comments to evaluation rows to auto-fill hedge results |
| `config/hierarchy.py` | Admin → Trader → Client hierarchy management. Role lookups, access control, email-to-client mapping |
| `config/settings.py` | Centralised app settings and feature flags |
| `config/production.py` | Production-only config: secure cookies, strict CORS, production DB settings |

---

## FRONTEND

The entire frontend is a **single HTML page** (`dashboard/templates/index.html`) styled with a custom CSS file (`dashboard/static/css/style.css`). There is no frontend build step — no bundler, no npm.

### Rendering
| Technology | Purpose |
|---|---|
| **Jinja2** (Flask built-in) | Server-side HTML templating. Injects user type, client ID, feature flags into the HTML at request time. Controls what sections render for `client` vs `admin` vs `super_admin` |

### CSS & Styling
| Technology | Purpose |
|---|---|
| **Custom CSS** (`style.css`) | Full dark-theme design system with CSS variables for colors, gradients, shadows, and spacing. Handles all layout including the sticky two-row header, sticky table columns, responsive scroll controls |
| **CSS Custom Properties (`--vars`)** | Token system for the brand palette (gold accent, dark navy backgrounds, text hierarchy) |
| **CSS Grid & Flexbox** | Layout for the header rows, stats cards, control bars, and tab panels |
| **CSS `position: sticky`** | Keeps table column/row headers in view as the user scrolls both horizontally and vertically. Carefully z-indexed across 5 stacking layers |
| **CSS Animations (`@keyframes`)** | Slide-up fade for tab transitions, pulse highlight for deep-linked cells, spinner for loading states |

### External CSS Libraries (CDN)
| Library | Purpose |
|---|---|
| **Font Awesome 6** | Icon set used throughout — history icon, sign-out, coins, users, etc. |
| **Flag Icon CSS** | Country flag icons displayed next to client IDs |

### JavaScript
All JS is **vanilla (no frameworks, no bundler)**. Written inline in `<script>` tags inside `index.html`.

| Area | Purpose |
|---|---|
| **Data Fetching** (`fetch` API) | Polls `/api/data` to load client evaluations. All saves go to `/api/update_data` via `POST`. Uses `async/await` and `.then()` chains with retry logic (exponential backoff, up to 3 retries) |
| **Table Rendering** (`renderEvaluationsTable()`) | Builds the entire evaluations table from JS data — inline dropdowns, date pickers, text inputs, delete buttons, contextmenu note editors. Renders 50 rows at a time with a paginated "Show More" bar |
| **Soft Delete** | Marks rows `_deleted: true` instead of splicing. Deleted flag is saved to DB and survives any data sync |
| **Section Position Tracking** (`calculateSectionPositions()`) | Measures pixel positions of each section header (EVAL INFO, EVAL PHASE, FUNDED PHASE, FARMING PHASE) after render |
| **Horizontal Scroll Tracking** (`updateScrollIndicator()`) | Listens to `scroll` events on the table container. Updates the active section button and the sticky section-label pill dynamically |
| **Sticky Section Label** | A pill badge inside the EVAL INFO sticky header that updates its text and color as the user scrolls through sections — blue for Eval Info, green for Eval Phase, pink-red for Funded Phase, purple for Farming Phase |
| **Tab System** (`openTab()`) | Shows/hides tab panels. Loads waterlog and stats lazily on first open |
| **Version History Panel** | slide-in sidebar showing version list from `/api/client/history`. Select a version → diff view → restore via `/api/client/rollback` |
| **Cell Editing** | Double-click or typing on any cell creates an inline `<input>`. On blur or Enter, value is saved to `currentData` and `saveData()` is called |
| **Context Menu Notes** | Right-click any cell to open a floating note editor. Notes are saved per `(row, column)` independently from evaluation data |
| **Deep Linking** | URL `?range=N5` highlights a specific cell (column N, row 5) and scrolls it into view on load |
| **Keyboard Shortcuts** | `Alt+→/←` scrolls the table, `Alt+Home/End` jumps to section starts, `Ctrl+H` opens version history |
| **Save Status Indicator** | In-header status badge shows live feedback: ✅ Saved, ⏳ Retrying (1/3), ⚠️ Save failed |

---

## DESKTOP APP (Trader Companion)

The Trader Companion is a standalone Windows `.exe` built with **PyInstaller**.

### GUI Framework
| Technology | Purpose |
|---|---|
| **tkinter** (built-in) | Python's standard GUI toolkit. Provides the main window, tabs, buttons, scrollable log output, and all input dialogs |
| **ttk** (built-in) | Themed tkinter widgets — styled tabs, progress bars, comboboxes |

### MT5 Integration
| Technology | Purpose |
|---|---|
| **MetaTrader5** (Python package) | Official MT5 Python API. Used to connect to the MT5 terminal, fetch account info, open deals/positions history, and read trade comments |

### Parsing & Logic
| Module | Purpose |
|---|---|
| `trader_companion/mt5_comment_parser.py` | Custom parser for MT5 deal comments (`{Account}_CH1`, `_FU2`, `_FA3` etc). Extracts account number and phase so hedge results can be matched back to evaluation rows |
| `MT5DealAggregator` | Groups individual deals by comment tag into sessions (net profit per account/phase) |
| `MT5CommentParser` | Validates and interprets each comment format, returns structured `Phase` objects |

### Networking
| Technology | Purpose |
|---|---|
| **requests** `>=2.31.0` | All HTTP communication with the dashboard — login via email, fetch evaluations (`GET /api/data`), push hedge results (`POST /api/client/push`), push raw MT5 data (`POST /api/update_data`) |

### Packaging
| Technology | Purpose |
|---|---|
| **PyInstaller** | Bundles the entire Python app + all dependencies into a single `Trader_Companion_vX.Y.Z.exe` with no Python installation required |
| **pyinstaller `.spec` files** | One spec file per version (e.g. `Trader_Companion_v1.2.0.spec`). Controls which files are bundled, icon, app name, hidden imports |
| **`build.py`** | Custom build script that runs PyInstaller and copies assets into the output folder |

---

## DEPLOYMENT INFRASTRUCTURE

| Technology | Purpose |
|---|---|
| **Gunicorn** | Production-grade WSGI server. Configured via `gunicorn.conf.py` — workers = `(2 × CPU cores) + 1`, 120s timeout |
| **`wsgi.py`** | WSGI entry point. Imports the Flask app and applies production config (secure cookies, session config) before Gunicorn binds |
| **`deploy.sh` / `deploy.ps1`** | Shell scripts for deploying to the cloud server — pulls latest code, installs deps, restarts Gunicorn |
| **`config/production.py`** | Production-only settings — `SESSION_COOKIE_SECURE=True`, `DEBUG=False`, production DB URL |
| **Git / GitHub** | Version control. The dashboard code (`dashboard/`, `config/`, static assets) is tracked and pushed to `github.com/Oukaharry/FuturesAutomatedFeed` |
| **`.env` / `python-dotenv`** | Environment-specific secrets (DB URL, secret key, Redis URL) loaded from `.env` file — never committed to Git |
