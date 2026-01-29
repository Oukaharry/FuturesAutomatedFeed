"""
WSGI Entry Point for MT5 Hedging Dashboard
===========================================
This is the entry point for production WSGI servers like Gunicorn.

Usage:
    gunicorn wsgi:app
    gunicorn -c gunicorn.conf.py wsgi:app

For development:
    python wsgi.py
"""

import os
import sys

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set default environment
if not os.getenv('FLASK_ENV'):
    os.environ['FLASK_ENV'] = 'production'

# Import the Flask application
from dashboard.app import app

# Apply production configurations
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


# Configure the app for production
app = configure_app(app)


# Note: /health endpoint is already defined in dashboard/app.py
# Only add /ready if it doesn't exist
if '/ready' not in [rule.rule for rule in app.url_map.iter_rules()]:
    @app.route('/ready')
    def readiness_check():
        """Readiness check - verifies the app can serve requests."""
        try:
            # Quick database connectivity check
            from dashboard.database import get_connection
            with get_connection() as conn:
                conn.execute('SELECT 1')
            return {'status': 'ready', 'database': 'connected'}, 200
        except Exception as e:
            return {'status': 'not ready', 'error': str(e)}, 503


if __name__ == '__main__':
    # Run development server
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV') == 'development'
    
    print(f"🚀 Starting MT5 Dashboard in {'development' if debug else 'production'} mode")
    print(f"   URL: http://localhost:{port}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug
    )
