from dashboard.app import app
import os

if __name__ == "__main__":
    port = 5002
    print(f"Starting MT5 Dashboard on port {port}")
    # force debug=True to enable reloading for future edits
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)