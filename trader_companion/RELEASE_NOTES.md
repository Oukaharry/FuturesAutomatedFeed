# MT5 Trader Companion - Release Notes

## Version 1.0.8 (2026-02-23)

### New Features
- **Smart Auto-Push**: The auto-push system now intelligently polls MT5 deal history every 10 seconds but *only* transmits data if a new trade is detected.
- **Active State Indicator**: The Auto-Push button now changes color to Light Blue/Green when monitoring is active.
- **Bandwidth Optimization**: Silent polling reduces unnecessary API calls when no trading activity occurs.

### Changes
- Updated protocol for consistent communication with backend.
- Minor stability improvements in data parsing.

## Version 1.0.7 (2026-02-15)

## Version 1.0.1 (2026-02-02)

### Overview
This is the first official release of the MT5 Trader Companion desktop application. The app is designed to help traders easily push their MT5 trading data to the BallerQuotes dashboard and manage essential trading operations from a simple, user-friendly interface.

### Key Features
- **Push Data**: Instantly send your MT5 trading data to the dashboard with a single click.
- **Auto-Push**: Enable automatic data pushing at regular intervals for seamless updates.
- **Save Config**: Save your configuration and preferences for future sessions.
- **Read-Only Dashboard URL**: The dashboard URL is hardcoded to https://www.ballerquotes.com for security and simplicity.
- **Compact, Modern UI**: Clean, minimal interface with only the essential controls. Window size set to 620x700 for optimal usability.
- **Standalone Executable**: No Python installation required. Just run the provided `.exe` file.

### Improvements & Fixes
- Reduced button count from 9 to 3 for a streamlined experience.
- Removed unnecessary debug and advanced controls.
- Improved layout, spacing, and font sizes for better readability.
- Enhanced reliability and error handling for data push operations.

### Known Issues
- None reported for this release.

### Getting Started
1. Download and run `MT5TraderCompanion.exe` from the `dist` folder.
2. Use the Push Data, Auto-Push, and Save Config buttons as needed.
3. All data is sent securely to the BallerQuotes dashboard.

---
For support or feedback, please contact the development team.
