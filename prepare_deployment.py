"""
Deployment Preparation Script
This script helps prepare your dashboard for PythonAnywhere deployment.
"""

import os
import shutil
import json
from pathlib import Path


def create_deployment_package():
    """Create a deployment-ready package."""
    
    print("\n" + "="*60)
    print("PREPARING DASHBOARD FOR DEPLOYMENT")
    print("="*60 + "\n")
    
    # Create deployment directory
    deploy_dir = Path("deployment_package")
    if deploy_dir.exists():
        print(f"Removing existing {deploy_dir}...")
        shutil.rmtree(deploy_dir)
    
    deploy_dir.mkdir()
    print(f"✓ Created {deploy_dir}/\n")
    
    # Files and directories to copy
    items_to_copy = [
        ("dashboard", ["app.py", "api_client.py", "manage_api_keys.py"]),
        ("dashboard/templates", None),  # Copy entire directory
        ("dashboard/static", None),     # Copy entire directory
        ("config", ["hierarchy.py", "hierarchy.json", "settings.py"]),
        ("utils", ["__init__.py", "data_processor.py"]),
        ("", ["requirements.txt"]),  # Root files
    ]
    
    # Copy files
    for source_dir, files in items_to_copy:
        source_path = Path(source_dir) if source_dir else Path(".")
        dest_path = deploy_dir / source_dir if source_dir else deploy_dir
        
        if files is None:
            # Copy entire directory
            if source_path.exists():
                dest_path.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                print(f"✓ Copied {source_path}/ -> {dest_path}/")
        else:
            # Copy specific files
            dest_path.mkdir(parents=True, exist_ok=True)
            for file in files:
                src_file = source_path / file
                dst_file = dest_path / file
                if src_file.exists():
                    shutil.copy2(src_file, dst_file)
                    print(f"✓ Copied {src_file} -> {dst_file}")
                else:
                    print(f"⚠ Skipped {src_file} (not found)")
    
    # Create .gitignore for deployment
    gitignore_content = """# Deployment .gitignore
api_keys.json
dashboard_data.json
*.pyc
__pycache__/
.env
*.log
"""
    
    with open(deploy_dir / ".gitignore", "w") as f:
        f.write(gitignore_content)
    print(f"\n✓ Created .gitignore")
    
    # Create empty api_keys.json and dashboard_data.json
    with open(deploy_dir / "dashboard" / "api_keys.json", "w") as f:
        json.dump({}, f)
    print(f"✓ Created empty api_keys.json")
    
    with open(deploy_dir / "dashboard" / "dashboard_data.json", "w") as f:
        json.dump({"clients_db": {}}, f)
    print(f"✓ Created empty dashboard_data.json")
    
    # Create deployment instructions
    instructions = """
DEPLOYMENT INSTRUCTIONS
=======================

1. CREATE PYTHONANYWHERE ACCOUNT
   - Go to https://www.pythonanywhere.com
   - Sign up for FREE account
   - Remember your username (e.g., "harrytrader")

2. UPLOAD FILES
   - Go to "Files" tab
   - Create directory: /home/yourusername/MT5Dashboard
   - Upload ALL files from this deployment_package folder

3. INSTALL DEPENDENCIES
   - Go to "Consoles" tab
   - Start a "Bash" console
   - Run:
     cd MT5Dashboard
     pip3.10 install --user -r requirements.txt

4. SET ADMIN PASSWORD
   - In the Bash console:
     echo 'export ADMIN_PASSWORD="YourSecurePassword123"' >> ~/.bashrc
     source ~/.bashrc

5. CREATE WEB APP
   - Go to "Web" tab
   - Click "Add a new web app"
   - Choose "Flask" -> Python 3.10
   - Set source code: /home/yourusername/MT5Dashboard

6. CONFIGURE WSGI
   - Click "WSGI configuration file" link
   - Replace contents with:

import sys
import os

# Add project directory
project_home = '/home/yourusername/MT5Dashboard'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# Set admin password
os.environ['ADMIN_PASSWORD'] = 'YourSecurePassword123'

# Import Flask app
from dashboard.app import app as application

7. RELOAD WEB APP
   - Click green "Reload" button
   - Visit: https://yourusername.pythonanywhere.com

8. GENERATE API KEYS (from your local machine)
   - Run: python dashboard/manage_api_keys.py
   - URL: https://yourusername.pythonanywhere.com
   - Password: YourSecurePassword123
   - Generate keys for each trader

DONE! Your dashboard is now live.
"""
    
    with open(deploy_dir / "DEPLOY_INSTRUCTIONS.txt", "w") as f:
        f.write(instructions)
    print(f"✓ Created DEPLOY_INSTRUCTIONS.txt")
    
    # Create requirements.txt without Windows-specific packages
    requirements = """flask>=2.3.0
requests>=2.28.0
python-dotenv>=1.0.0
"""
    
    with open(deploy_dir / "requirements.txt", "w") as f:
        f.write(requirements)
    print(f"✓ Created requirements.txt (cloud-compatible)")
    
    print("\n" + "="*60)
    print("DEPLOYMENT PACKAGE READY!")
    print("="*60)
    print(f"\nLocation: {deploy_dir.absolute()}")
    print(f"\nNext steps:")
    print(f"1. Read: {deploy_dir}/DEPLOY_INSTRUCTIONS.txt")
    print(f"2. Upload all files to PythonAnywhere")
    print(f"3. Follow the 8 steps in DEPLOY_INSTRUCTIONS.txt")
    print("\n" + "="*60 + "\n")
    
    return deploy_dir


def create_wsgi_template():
    """Create a WSGI configuration template."""
    
    wsgi_template = """# WSGI Configuration for PythonAnywhere
# Copy this content to your WSGI configuration file

import sys
import os

# ============================================================================
# CONFIGURATION - Update these values
# ============================================================================
USERNAME = "yourusername"  # Your PythonAnywhere username
ADMIN_PASSWORD = "YourSecurePassword123"  # Your admin password
# ============================================================================

# Add project directory to path
project_home = f'/home/{USERNAME}/MT5Dashboard'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# Set environment variables
os.environ['ADMIN_PASSWORD'] = ADMIN_PASSWORD

# Import Flask application
from dashboard.app import app as application

# Uncomment for debugging (remove in production)
# application.debug = True
"""
    
    deploy_dir = Path("deployment_package")
    with open(deploy_dir / "wsgi_config_template.py", "w") as f:
        f.write(wsgi_template)
    
    print(f"✓ Created wsgi_config_template.py")


def create_test_script():
    """Create a script to test the deployed dashboard."""
    
    test_script = """#!/usr/bin/env python3
\"\"\"
Test your deployed dashboard
Usage: python test_deployed.py https://yourusername.pythonanywhere.com
\"\"\"

import sys
import requests

if len(sys.argv) < 2:
    print("Usage: python test_deployed.py <dashboard_url>")
    print("Example: python test_deployed.py https://harrytrader.pythonanywhere.com")
    sys.exit(1)

url = sys.argv[1].rstrip('/')

print(f"Testing dashboard at: {url}\\n")

# Test health endpoint
try:
    response = requests.get(f"{url}/api/health", timeout=10)
    if response.status_code == 200:
        data = response.json()
        print("✓ Dashboard is online!")
        print(f"  Status: {data.get('status')}")
        print(f"  Clients: {data.get('clients_count')}")
    else:
        print(f"✗ Health check failed: {response.status_code}")
except Exception as e:
    print(f"✗ Connection failed: {e}")
    print("\\nMake sure:")
    print("  1. Dashboard is deployed and running")
    print("  2. URL is correct (should start with https://)")
    print("  3. You clicked 'Reload' on PythonAnywhere")
"""
    
    deploy_dir = Path("deployment_package")
    with open(deploy_dir / "test_deployed.py", "w") as f:
        f.write(test_script)
    
    print(f"✓ Created test_deployed.py")


if __name__ == "__main__":
    deploy_dir = create_deployment_package()
    create_wsgi_template()
    create_test_script()
    
    print("\\n🚀 Ready to deploy!")
    print(f"\\nAll files are in: {deploy_dir.absolute()}")
