# WSGI Configuration for PythonAnywhere
# Copy this content to your WSGI configuration file

import sys
import os

# ============================================================================
# CONFIGURATION - Update these values
# ============================================================================
USERNAME = "ballerquotes"  # Your PythonAnywhere username
ADMIN_PASSWORD = "YourSecurePassword123"  # CHANGE THIS to your admin password
# ============================================================================

# Add project directory to path
project_home = f'/home/{USERNAME}/TrackingDashboard'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# Set environment variables
os.environ['ADMIN_PASSWORD'] = ADMIN_PASSWORD

# Import Flask application
from dashboard.app import app as application

# Uncomment for debugging (remove in production)
# application.debug = True
