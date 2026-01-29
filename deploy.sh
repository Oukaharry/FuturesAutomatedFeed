#!/bin/bash
# =============================================================================
# Deployment Script for MT5 Hedging Dashboard
# =============================================================================
# This script prepares and deploys the application to a production server.
#
# Prerequisites:
#   - Python 3.9+
#   - PostgreSQL (optional, can use SQLite)
#   - Redis (optional, for caching)
#   - Nginx (for reverse proxy)
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh [setup|start|stop|restart|status|logs]
# =============================================================================

set -e

# Configuration
APP_NAME="mt5-dashboard"
APP_DIR="/opt/mt5-dashboard"
VENV_DIR="$APP_DIR/venv"
LOG_DIR="/var/log/$APP_NAME"
PID_FILE="/var/run/$APP_NAME.pid"
GUNICORN_SOCKET="/var/run/$APP_NAME.sock"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# =============================================================================
# Setup Functions
# =============================================================================

setup_directories() {
    log_info "Creating directories..."
    sudo mkdir -p $APP_DIR
    sudo mkdir -p $LOG_DIR
    sudo mkdir -p /var/run
    sudo chown -R $USER:$USER $APP_DIR
    sudo chown -R $USER:$USER $LOG_DIR
}

setup_virtualenv() {
    log_info "Setting up Python virtual environment..."
    python3 -m venv $VENV_DIR
    source $VENV_DIR/bin/activate
    pip install --upgrade pip
    pip install -r requirements-production.txt
    deactivate
}

setup_env_file() {
    if [ ! -f "$APP_DIR/.env" ]; then
        log_info "Creating .env file from template..."
        cp .env.example $APP_DIR/.env
        log_warn "Please edit $APP_DIR/.env with your production values!"
    else
        log_info ".env file already exists"
    fi
}

setup_systemd() {
    log_info "Creating systemd service..."
    
    sudo tee /etc/systemd/system/$APP_NAME.service > /dev/null << EOF
[Unit]
Description=MT5 Hedging Dashboard
After=network.target

[Service]
User=$USER
Group=$USER
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_DIR/bin/gunicorn -c gunicorn.conf.py wsgi:app
ExecReload=/bin/kill -s HUP \$MAINPID
ExecStop=/bin/kill -s TERM \$MAINPID
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable $APP_NAME
    log_info "Systemd service created and enabled"
}

setup_nginx() {
    log_info "Creating Nginx configuration..."
    
    sudo tee /etc/nginx/sites-available/$APP_NAME > /dev/null << EOF
server {
    listen 80;
    server_name your-domain.com;  # Change this!

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 60s;
        proxy_read_timeout 60s;
    }

    location /static {
        alias $APP_DIR/dashboard/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Gzip compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
}
EOF

    sudo ln -sf /etc/nginx/sites-available/$APP_NAME /etc/nginx/sites-enabled/
    sudo nginx -t && sudo systemctl reload nginx
    log_info "Nginx configured"
}

# =============================================================================
# Management Functions
# =============================================================================

copy_files() {
    log_info "Copying application files..."
    rsync -av --exclude='.venv' --exclude='*.pyc' --exclude='__pycache__' \
          --exclude='.git' --exclude='*.db' --exclude='.env' \
          ./ $APP_DIR/
}

start_app() {
    log_info "Starting $APP_NAME..."
    sudo systemctl start $APP_NAME
    sleep 2
    status_app
}

stop_app() {
    log_info "Stopping $APP_NAME..."
    sudo systemctl stop $APP_NAME
}

restart_app() {
    log_info "Restarting $APP_NAME..."
    sudo systemctl restart $APP_NAME
    sleep 2
    status_app
}

status_app() {
    sudo systemctl status $APP_NAME --no-pager
}

show_logs() {
    sudo journalctl -u $APP_NAME -f
}

# =============================================================================
# Main Script
# =============================================================================

case "$1" in
    setup)
        log_info "Starting full setup..."
        setup_directories
        copy_files
        setup_virtualenv
        setup_env_file
        setup_systemd
        echo ""
        log_info "Setup complete!"
        log_warn "Next steps:"
        echo "  1. Edit $APP_DIR/.env with your production values"
        echo "  2. Run: ./deploy.sh setup-nginx"
        echo "  3. Run: ./deploy.sh start"
        ;;
    
    setup-nginx)
        setup_nginx
        ;;
    
    deploy)
        log_info "Deploying updates..."
        copy_files
        restart_app
        log_info "Deployment complete!"
        ;;
    
    start)
        start_app
        ;;
    
    stop)
        stop_app
        ;;
    
    restart)
        restart_app
        ;;
    
    status)
        status_app
        ;;
    
    logs)
        show_logs
        ;;
    
    *)
        echo "MT5 Hedging Dashboard Deployment Script"
        echo ""
        echo "Usage: $0 {setup|setup-nginx|deploy|start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  setup       - Full initial setup (directories, venv, systemd)"
        echo "  setup-nginx - Configure Nginx reverse proxy"
        echo "  deploy      - Deploy code updates"
        echo "  start       - Start the application"
        echo "  stop        - Stop the application"
        echo "  restart     - Restart the application"
        echo "  status      - Show application status"
        echo "  logs        - Tail application logs"
        exit 1
        ;;
esac
