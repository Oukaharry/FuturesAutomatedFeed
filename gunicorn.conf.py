"""
Gunicorn Configuration for MT5 Hedging Dashboard
=================================================
Production WSGI server configuration.

Usage:
    gunicorn -c gunicorn.conf.py wsgi:app

Or with custom settings:
    gunicorn --bind 0.0.0.0:8000 --workers 4 wsgi:app
"""

import os
import multiprocessing

# =============================================================================
# Server Socket
# =============================================================================
bind = os.getenv('GUNICORN_BIND', '0.0.0.0:8000')
backlog = 2048

# =============================================================================
# Worker Processes
# =============================================================================
# Rule of thumb: (2 x CPU cores) + 1
workers = int(os.getenv('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1))

# Worker class - options: 'sync', 'gevent', 'eventlet', 'tornado'
# 'gevent' is recommended for high-concurrency applications
worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'sync')

# Worker connections (only for async workers like gevent)
worker_connections = 1000

# Timeout for worker processes (seconds)
timeout = 120

# Graceful timeout
graceful_timeout = 30

# Keep-alive timeout
keepalive = 5

# =============================================================================
# Server Mechanics
# =============================================================================
# Daemonize the Gunicorn process (set to False if using systemd/supervisor)
daemon = False

# PID file location
pidfile = os.getenv('GUNICORN_PID_FILE', '/tmp/gunicorn.pid')

# User and group to run workers as (uncomment for production)
# user = 'www-data'
# group = 'www-data'

# Working directory
chdir = os.path.dirname(os.path.abspath(__file__))

# Umask for file creation
umask = 0o022

# Temp directory for worker heartbeat
tmp_upload_dir = None

# =============================================================================
# Logging
# =============================================================================
# Access log - set to '-' for stdout
accesslog = os.getenv('GUNICORN_ACCESS_LOG', '-')

# Error log - set to '-' for stderr
errorlog = os.getenv('GUNICORN_ERROR_LOG', '-')

# Log level: 'debug', 'info', 'warning', 'error', 'critical'
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')

# Access log format
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Capture output from stdout/stderr
capture_output = True

# Enable access log
disable_redirect_access_to_syslog = True

# =============================================================================
# Process Naming
# =============================================================================
proc_name = 'mt5-dashboard'

# =============================================================================
# SSL (uncomment if using HTTPS directly with Gunicorn)
# =============================================================================
# keyfile = '/path/to/server.key'
# certfile = '/path/to/server.crt'
# ssl_version = 'TLSv1_2'
# cert_reqs = 0  # ssl.CERT_NONE
# ca_certs = None
# suppress_ragged_eofs = True
# do_handshake_on_connect = False

# =============================================================================
# Server Hooks
# =============================================================================

def on_starting(server):
    """Called just before the master process is initialized."""
    print("🚀 Starting MT5 Dashboard Gunicorn server...")


def on_reload(server):
    """Called before reloading the configuration."""
    print("🔄 Reloading MT5 Dashboard server configuration...")


def when_ready(server):
    """Called just after the server is started."""
    print(f"✅ MT5 Dashboard server ready at {bind}")
    print(f"   Workers: {workers}")
    print(f"   Worker class: {worker_class}")


def worker_int(worker):
    """Called when a worker receives SIGINT or SIGQUIT."""
    print(f"⚠️ Worker {worker.pid} received interrupt signal")


def worker_abort(worker):
    """Called when a worker receives SIGABRT."""
    print(f"❌ Worker {worker.pid} was aborted")


def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass


def post_fork(server, worker):
    """Called just after a worker has been forked."""
    print(f"👷 Worker {worker.pid} spawned")


def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    pass


def worker_exit(server, worker):
    """Called just after a worker has been exited."""
    print(f"👋 Worker {worker.pid} exited")


def nworkers_changed(server, new_value, old_value):
    """Called when the number of workers has been changed."""
    print(f"📊 Workers changed: {old_value} → {new_value}")


def on_exit(server):
    """Called just before exiting Gunicorn."""
    print("🛑 MT5 Dashboard server shutting down...")


# =============================================================================
# Environment-specific overrides
# =============================================================================
if os.getenv('FLASK_ENV') == 'development':
    # Development settings
    workers = 2
    reload = True  # Auto-reload on code changes
    loglevel = 'debug'
    timeout = 300  # Longer timeout for debugging
