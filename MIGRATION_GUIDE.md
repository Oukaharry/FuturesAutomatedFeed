# Migration Guide: PythonAnywhere to Custom Domain (ballerquotes.com)

This guide covers two ways to use your domain `ballerquotes.com` with your dashboard:
1.  **Option A**: Keep using PythonAnywhere but with your custom domain (Requires Paid Account).
2.  **Option B**: Migrate to a self-hosted VPS (e.g., DigitalOcean, Linode, AWS) (Requires server setup).

---

## Option A: PythonAnywhere Custom Domain (Easiest)
*Prerequisite: You must upgrade to the "Hacker" plan ($5/mo) on PythonAnywhere to use custom domains.*

### 1. Configure PythonAnywhere
1.  Log in to PythonAnywhere.
2.  Go to the **Web** tab.
3.  Click the **Edit** icon (pencil) next to your web app address (e.g., `harrytrader.pythonanywhere.com`).
4.  Change the address to `www.ballerquotes.com`.
5.  Click **Next/Save**.
6.  PythonAnywhere will provide a **CNAME** target (e.g., `webapp-123456.pythonanywhere.com`). Copy this.

### 2. Configure DNS (GoDaddy Instructions)
1.  Log in to [GoDaddy](https://dcc.godaddy.com/control/portfolio) and go to your **Domain Portfolio**.
2.  Select `ballerquotes.com` and click **DNS**.
3.  **Check for existing "www" record:**
    *   Look through the list of records.
    *   If you see a record with Name `www` (Type "A" or "CNAME"), you **must delete it** first.
    *   *The error "Record name www conflicts with another record" means GoDaddy sees a duplicate.*

4.  **Add the CNAME Record (Points `www` to PythonAnywhere):**
    *   Click **Add New Record**.
    *   **Type**: `CNAME`
    *   **Name**: `www`
    *   **Value**: `webapp-2913221.pythonanywhere.com`
    *   **TTL**: `1 Hour` (or Default).
    *   Click **Save**.

5.  **Setup Forwarding (Points `ballerquotes.com` to `www`):**
    *   PythonAnywhere only supports the `www` subdomain properly for CNAMEs. You must forward the root "naked" domain.
    *   In the GoDaddy DNS page, look for the **Forwarding** tab or menu.
    *   **Domain**: Click **Add Forwarding**.
    *   **Destination URL**: `https://www.ballerquotes.com`
    *   **Forward Type**: `Permanent (301)`
    *   **Save**.

### 3. Finalize
1.  Back in PythonAnywhere **Web** tab, click **Reload**.
2.  Scroll down to "Security" and click **HTTPS certificate** -> **Auto-provision Let's Encrypt certificate** (Takes a few minutes).

---

## Option B: Migrate to a VPS (DigitalOcean/Linode/Ubuntu)
*Recommended if you want full control or cheaper scaling.*

### 1. Provision Server
1.  Create a standard **Ubuntu 22.04 / 24.04** Droplet/VPS (DigitalOcean, Linode, AWS, etc.).
2.  **GoDaddy DNS Configuration**:
    *   Go to **DNS Management** for `ballerquotes.com`.
    *   **Add "A" Record**:
        *   **Type**: `A`
        *   **Name**: `@`
        *   **Value**: `Your_VPS_IP_Address`
    *   **Add "CNAME" Record**:
        *   **Type**: `CNAME`
        *   **Name**: `www`
        *   **Value**: `ballerquotes.com` (or `@`)

### 2. Prepare Server
SSH into your server: `ssh root@ballerquotes.com`
```bash
# Update system
apt update && apt upgrade -y
apt install python3-pip python3-venv nginx -y
```

### 3. Transfer Data (From PythonAnywhere or Local)
You need to move your code **AND** your database.

**If moving from PythonAnywhere:**
1.  Download `dashboard/dashboard.db` (contains users/history).
2.  Download `config/hierarchy.json` (contains admin structure).
3.  Download the codebase.

**Upload to VPS (using SCP or FileZilla):**
Destination: `/opt/MT5HedgingEngine`

### 4. Setup Python Environment
```bash
cd /opt/MT5HedgingEngine
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

### 5. Configure Gunicorn (App Server)
Create service file: `/etc/systemd/system/mt5.service`
```ini
[Unit]
Description=Gunicorn instance to serve MT5 Dashboard
After=network.target

[Service]
User=root
Group=www-data
WorkingDirectory=/opt/MT5HedgingEngine
Environment="PATH=/opt/MT5HedgingEngine/venv/bin"
Environment="ADMIN_PASSWORD=YourSecurePassword"
ExecStart=/opt/MT5HedgingEngine/venv/bin/gunicorn --workers 3 --bind unix:mt5.sock -m 007 dashboard.app:app

[Install]
WantedBy=multi-user.target
```

Start the service:
```bash
systemctl start mt5
systemctl enable mt5
```

### 6. Configure Nginx (Web Server)
Create config: `/etc/nginx/sites-available/ballerquotes`
```nginx
server {
    listen 80;
    server_name ballerquotes.com www.ballerquotes.com;

    location / {
        include proxy_params;
        proxy_pass http://unix:/opt/MT5HedgingEngine/mt5.sock;
    }
}
```

Enable site:
```bash
ln -s /etc/nginx/sites-available/ballerquotes /etc/nginx/sites-enabled
nginx -t
systemctl restart nginx
```

### 7. Setup SSL (HTTPS)
```bash
apt install certbot python3-certbot-nginx
certbot --nginx -d ballerquotes.com -d www.ballerquotes.com
```

---

## ⚠️ Important: Data Continuity
If you have live users on PythonAnywhere, you **must** copy the `dashboard/dashboard.db` file to your new location. This file contains:
*   User accounts & passwords
*   API Keys
*   Trade history & stats

If you simply redeploy the code, a new empty database will be created, and users will lose access.
