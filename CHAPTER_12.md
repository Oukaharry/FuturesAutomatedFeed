# Chapter 12 — Deployment

_Exported from CODEBASE_REFERENCE.pdf as plain Markdown. Paste this into another Claude conversation, Notion, or any Markdown viewer._

Last phase. We add the entry points the production server (Gunicorn) calls, a CLI for managing users, a wrapper around Alembic migrations, the script that bundles the dashboard for deployment to PythonAnywhere, and the PyInstaller build script that packages the desktop companion into a Windows executable.

**Files in this chapter:**

- `manage_users.py`
- `migrations.py`
- `wsgi.py`
- `gunicorn.conf.py`
- `prepare_deployment.py`
- `build.py`

---

### `manage_users.py`

> File not present in this checkout — skipped.

### `migrations.py`

> File not present in this checkout — skipped.

### `wsgi.py`

_109 loc · 0 classes · 2 functions · 2 imports_

**Module docstring**

> WSGI Entry Point for MT5 Hedging Dashboard =========================================== This is the entry point for production WSGI servers like Gunicorn.
> Usage:     gunicorn wsgi:app     gunicorn -c gunicorn.conf.py wsgi:app
> For development:     python wsgi.py

**Imports**

```python
import os
import sys
```

**Functions**

#### `_maintenance_fallback`

```python
def _maintenance_fallback(environ, start_response)
```
> Static WSGI app returned when Flask itself fails to load.

**What it does, step by step:**

1. Assigns <code>_html</code> = <code>open(os.path.join(os.path.dirname(os.path.abspath(__file_...</code>.
2. Assigns <code>status</code> = <code>'500 Internal Server Error'</code>.
3. Assigns <code>headers</code> = <code>[('Content-Type', 'text/html; charset=utf-8'), ('Content-...</code>.
4. Calls <code>start_response(...)</code> for its side effect.
5. <b>return</b> <code>[_html]</code>.

```python
def _maintenance_fallback(environ, start_response):
    """Static WSGI app returned when Flask itself fails to load."""
    _html = open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'dashboard', 'templates', '500.html'),
        'rb'
    ).read()
    status = '500 Internal Server Error'
    headers = [('Content-Type', 'text/html; charset=utf-8'),
               ('Content-Length', str(len(_html)))]
    start_response(status, headers)
    return [_html]
```

#### `configure_app`

```python
def configure_app(app)
```
> Apply production-specific configurations.

**What it does, step by step:**

1. Lazy import from <code>config.production</code>.
2. Assigns <code>config</code> = <code>get_config(os.getenv('FLASK_ENV', 'production'))</code>.
3. Assigns <code>app.config['SECRET_KEY']</code> = <code>config.SECRET_KEY</code>.
4. Assigns <code>app.config['DEBUG']</code> = <code>config.DEBUG</code>.
5. Assigns <code>app.config['TESTING']</code> = <code>config.TESTING</code>.
6. Assigns <code>app.config['SESSION_COOKIE_SECURE']</code> = <code>config.SESSION_COOKIE_SECURE</code>.
7. Assigns <code>app.config['SESSION_COOKIE_HTTPONLY']</code> = <code>config.SESSION_COOKIE_HTTPONLY</code>.
8. Assigns <code>app.config['SESSION_COOKIE_SAMESITE']</code> = <code>config.SESSION_COOKIE_SAMESITE</code>.
9. Assigns <code>app.config['PERMANENT_SESSION_LIFETIME']</code> = <code>config.PERMANENT_SESSION_LIFETIME</code>.
10. Assigns <code>app.config['MAX_CONTENT_LENGTH']</code> = <code>config.MAX_CONTENT_LENGTH</code>.
11. <b>return</b> <code>app</code>.

```python
def configure_app(app):
    """Apply production-specific configurations."""
    from config.production import get_config
    
    config = get_config(os.getenv('FLASK_ENV', 'production'))
    
    # Apply configuration to app
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['DEBUG'] = config.DEBUG
    app.config['TESTING'] = config.TESTING
    
    # Session configuration
    app.config['SESSION_COOKIE_SECURE'] = config.SESSION_COOKIE_SECURE
    app.config['SESSION_COOKIE_HTTPONLY'] = config.SESSION_COOKIE_HTTPONLY
    app.config['SESSION_COOKIE_SAMESITE'] = config.SESSION_COOKIE_SAMESITE
    app.config['PERMANENT_SESSION_LIFETIME'] = config.PERMANENT_SESSION_LIFETIME
    
    # File size limits
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
    
    return app
```

---

### `gunicorn.conf.py`

_173 loc · 0 classes · 11 functions · 2 imports_

**Module docstring**

> Gunicorn Configuration for MT5 Hedging Dashboard ================================================= Production WSGI server configuration.
> Usage:     gunicorn -c gunicorn.conf.py wsgi:app
> Or with custom settings:     gunicorn --bind 0.0.0.0:8000 --workers 4 wsgi:app

**Imports**

```python
import os
import multiprocessing
```

**Functions**

#### `on_starting`

```python
def on_starting(server)
```
> Called just before the master process is initialized.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.

```python
def on_starting(server):
    """Called just before the master process is initialized."""
    print("🚀 Starting MT5 Dashboard Gunicorn server...")
```

#### `on_reload`

```python
def on_reload(server)
```
> Called before reloading the configuration.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.

```python
def on_reload(server):
    """Called before reloading the configuration."""
    print("🔄 Reloading MT5 Dashboard server configuration...")
```

#### `when_ready`

```python
def when_ready(server)
```
> Called just after the server is started.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.
2. Calls <code>print(...)</code> for its side effect.
3. Calls <code>print(...)</code> for its side effect.

```python
def when_ready(server):
    """Called just after the server is started."""
    print(f"✅ MT5 Dashboard server ready at {bind}")
    print(f"   Workers: {workers}")
    print(f"   Worker class: {worker_class}")
```

#### `worker_int`

```python
def worker_int(worker)
```
> Called when a worker receives SIGINT or SIGQUIT.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.

```python
def worker_int(worker):
    """Called when a worker receives SIGINT or SIGQUIT."""
    print(f"⚠️ Worker {worker.pid} received interrupt signal")
```

#### `worker_abort`

```python
def worker_abort(worker)
```
> Called when a worker receives SIGABRT.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.

```python
def worker_abort(worker):
    """Called when a worker receives SIGABRT."""
    print(f"❌ Worker {worker.pid} was aborted")
```

#### `pre_fork`

```python
def pre_fork(server, worker)
```
> Called just before a worker is forked.

**What it does, step by step:**

1. <b>pass</b> (placeholder).

```python
def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass
```

#### `post_fork`

```python
def post_fork(server, worker)
```
> Called just after a worker has been forked.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.

```python
def post_fork(server, worker):
    """Called just after a worker has been forked."""
    print(f"👷 Worker {worker.pid} spawned")
```

#### `post_worker_init`

```python
def post_worker_init(worker)
```
> Called just after a worker has initialized the application.

**What it does, step by step:**

1. <b>pass</b> (placeholder).

```python
def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    pass
```

#### `worker_exit`

```python
def worker_exit(server, worker)
```
> Called just after a worker has been exited.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.

```python
def worker_exit(server, worker):
    """Called just after a worker has been exited."""
    print(f"👋 Worker {worker.pid} exited")
```

#### `nworkers_changed`

```python
def nworkers_changed(server, new_value, old_value)
```
> Called when the number of workers has been changed.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.

```python
def nworkers_changed(server, new_value, old_value):
    """Called when the number of workers has been changed."""
    print(f"📊 Workers changed: {old_value} → {new_value}")
```

#### `on_exit`

```python
def on_exit(server)
```
> Called just before exiting Gunicorn.

**What it does, step by step:**

1. Calls <code>print(...)</code> for its side effect.

```python
def on_exit(server):
    """Called just before exiting Gunicorn."""
    print("🛑 MT5 Dashboard server shutting down...")
```

---

### `prepare_deployment.py`

> File not present in this checkout — skipped.

### `build.py`

_87 loc · 0 classes · 1 functions · 4 imports_

**Imports**

```python
import os
import sys
import shutil
import subprocess
```

**Module constants**

```python
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
```
_Filesystem path resolved relative to the source file at import time — portable across machines._

```python
TRADER_APP = os.path.join(PROJECT_ROOT, 'trader_companion', 'trader_app.py')
```
_Module-level constant — bound once at import time and referenced from the functions and classes below._

```python
LOGO_SRC = os.path.join(PROJECT_ROOT, 'trader_companion', 'logo.png')
```
_Module-level constant — bound once at import time and referenced from the functions and classes below._

```python
UTILS_SRC = os.path.join(PROJECT_ROOT, 'utils')
```
_Module-level constant — bound once at import time and referenced from the functions and classes below._

```python
TRADER_COMPANION_DIR = os.path.join(PROJECT_ROOT, 'trader_companion')
```
_Module-level constant — bound once at import time and referenced from the functions and classes below._

```python
DIST_DIR = os.path.join(PROJECT_ROOT, 'dist')
```
_Module-level constant — bound once at import time and referenced from the functions and classes below._

```python
BUILD_DIR = os.path.join(PROJECT_ROOT, 'build')
```
_Module-level constant — bound once at import time and referenced from the functions and classes below._

```python
VERSION = get_version()
```
_Module-level constant — bound once at import time and referenced from the functions and classes below._

```python
BUILD_NAME = f'TradeopssAI_v{VERSION}'
```
_Module-level constant — bound once at import time and referenced from the functions and classes below._

**Functions**

#### `get_version`

```python
def get_version()
```
> Extract version from trader_app.py

**What it does, step by step:**

1. <b>with</b> <code>open(TRADER_APP, 'r', encoding='utf-8')</code>: enters a context manager.
2. <b>return</b> <code>'1.0.0'</code>.

```python
def get_version():
    """Extract version from trader_app.py"""
    with open(TRADER_APP, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('APP_VERSION'):
                return line.split('=')[1].strip().replace('"', '').replace("'", "")
    return '1.0.0'
```

---
