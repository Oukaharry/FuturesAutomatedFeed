"""
Production Configuration for MT5 Hedging Dashboard
===================================================
This module provides environment-specific configurations.
Use environment variables to override settings in production.
"""

import os
from datetime import timedelta


class Config:
    """Base configuration class."""
    
    # Flask Core
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'change-this-in-production')
    DEBUG = False
    TESTING = False
    
    # Application
    APP_NAME = 'MT5 Hedging Dashboard'
    APP_VERSION = '1.0.1'
    
    # Session Configuration
    SESSION_TYPE = 'filesystem'  # Options: 'filesystem', 'redis', 'sqlalchemy'
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_COOKIE_SECURE = True  # HTTPS only
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Database
    DATABASE_TYPE = os.getenv('DATABASE_TYPE', 'sqlite')  # 'sqlite' or 'postgresql'
    
    # SQLite (Development/Small deployments)
    SQLITE_PATH = os.getenv('SQLITE_PATH', 'dashboard/dashboard.db')
    
    # PostgreSQL (Production)
    POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
    POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
    POSTGRES_DB = os.getenv('POSTGRES_DB', 'mt5_dashboard')
    POSTGRES_USER = os.getenv('POSTGRES_USER', 'dashboard_user')
    POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')
    
    @property
    def DATABASE_URL(self):
        """Generate database URL based on configuration."""
        if self.DATABASE_TYPE == 'postgresql':
            return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        return f"sqlite:///{self.SQLITE_PATH}"
    
    # Redis Configuration (for caching and rate limiting)
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # Rate Limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URL = os.getenv('RATELIMIT_STORAGE_URL', 'memory://')
    RATELIMIT_DEFAULT = "10000 per day;2000 per hour"
    RATELIMIT_HEADERS_ENABLED = True
    
    # Caching
    CACHE_TYPE = os.getenv('CACHE_TYPE', 'simple')  # 'simple', 'redis', 'filesystem'
    CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes
    CACHE_REDIS_URL = os.getenv('CACHE_REDIS_URL', 'redis://localhost:6379/1')
    
    # Email (SMTP)
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    SMTP_USE_TLS = True
    EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'
    
    # Security
    PASSWORD_HASH_ITERATIONS = 100000
    API_KEY_LENGTH = 32
    SESSION_TOKEN_LENGTH = 64
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    LOG_FILE = os.getenv('LOG_FILE', 'logs/dashboard.log')
    
    # CORS (Cross-Origin Resource Sharing)
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')
    
    # File Upload Limits
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # Feature flags
    # Toggle to enable GPT-5 mini for clients. Default true; can be overridden via ENV.
    ENABLE_GPT5_MINI = os.getenv('ENABLE_GPT5_MINI', 'true').lower() == 'true'


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    DATABASE_TYPE = 'sqlite'
    RATELIMIT_STORAGE_URL = 'memory://'
    CACHE_TYPE = 'simple'
    LOG_LEVEL = 'DEBUG'


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    DATABASE_TYPE = os.getenv('DATABASE_TYPE', 'postgresql')
    RATELIMIT_STORAGE_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    CACHE_TYPE = 'redis'
    LOG_LEVEL = 'WARNING'
    
    # Enhanced security for production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    DEBUG = True
    DATABASE_TYPE = 'sqlite'
    SQLITE_PATH = ':memory:'
    RATELIMIT_ENABLED = False
    EMAIL_ENABLED = False


# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}


def get_config(env=None):
    """Get configuration based on environment."""
    if env is None:
        env = os.getenv('FLASK_ENV', 'development')
    return config.get(env, config['default'])()
