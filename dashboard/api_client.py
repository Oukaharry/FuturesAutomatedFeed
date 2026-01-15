"""
Dashboard API Client for MT5 Traders
This module allows traders to send data from their local MT5 software to the hosted dashboard.
"""

import requests
import json
from datetime import datetime
from typing import Dict, List, Optional


class DashboardAPIClient:
    """Client to communicate with the hosted dashboard API."""
    
    def __init__(self, api_url: str, api_key: str, client_id: Optional[str] = None):
        """
        Initialize the Dashboard API client.
        
        Args:
            api_url: Base URL of the dashboard API (e.g., 'https://yourusername.pythonanywhere.com')
            api_key: API key for authentication
            client_id: Optional client ID (if not set in API key)
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.client_id = client_id
        self.headers = {
            'Content-Type': 'application/json',
            'X-API-Key': self.api_key
        }
    
    def _post(self, endpoint: str, data: dict) -> dict:
        """Make a POST request to the API."""
        try:
            response = requests.post(
                f"{self.api_url}{endpoint}",
                headers=self.headers,
                json=data,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API Error: {e}")
            return {"status": "error", "message": str(e)}
    
    def _get(self, endpoint: str) -> dict:
        """Make a GET request to the API."""
        try:
            response = requests.get(
                f"{self.api_url}{endpoint}",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API Error: {e}")
            return {"status": "error", "message": str(e)}
    
    def push_account_data(self, account: dict, client_id: Optional[str] = None) -> dict:
        """
        Push account information to the dashboard.
        
        Args:
            account: Dictionary containing account info (balance, equity, margin, etc.)
            client_id: Optional client ID override
            
        Returns:
            API response dictionary
        """
        data = {
            "account": account,
            "client_id": client_id or self.client_id
        }
        return self._post("/api/trader/push_account", data)
    
    def push_positions(self, positions: List[dict], client_id: Optional[str] = None) -> dict:
        """
        Push current positions to the dashboard.
        
        Args:
            positions: List of position dictionaries
            client_id: Optional client ID override
            
        Returns:
            API response dictionary
        """
        data = {
            "positions": positions,
            "client_id": client_id or self.client_id
        }
        return self._post("/api/trader/push_positions", data)
    
    def push_deals(self, deals: List[dict], client_id: Optional[str] = None) -> dict:
        """
        Push deal history to the dashboard.
        
        Args:
            deals: List of deal dictionaries
            client_id: Optional client ID override
            
        Returns:
            API response dictionary
        """
        data = {
            "deals": deals,
            "client_id": client_id or self.client_id
        }
        return self._post("/api/trader/push_deals", data)
    
    def push_evaluations(self, evaluations: List[dict], client_id: Optional[str] = None) -> dict:
        """
        Push evaluation data to the dashboard.
        
        Args:
            evaluations: List of evaluation dictionaries
            client_id: Optional client ID override
            
        Returns:
            API response dictionary
        """
        data = {
            "evaluations": evaluations,
            "client_id": client_id or self.client_id
        }
        return self._post("/api/trader/push_evaluations", data)
    
    def push_all_data(self, data: dict) -> dict:
        """
        Push all data at once (account, positions, deals, evaluations).
        
        Args:
            data: Dictionary containing all data types with identity info
            
        Returns:
            API response dictionary
        """
        return self._post("/api/update_data", data)
    
    def health_check(self) -> dict:
        """Check if the dashboard API is accessible."""
        return self._get("/api/health")
    
    def get_client_data(self, client_id: Optional[str] = None) -> dict:
        """
        Retrieve client data from the dashboard.
        
        Args:
            client_id: Optional client ID override
            
        Returns:
            Client data dictionary
        """
        cid = client_id or self.client_id
        return self._get(f"/api/data?client_id={cid}")


# Example usage
if __name__ == "__main__":
    # Example configuration
    API_URL = "http://localhost:5001"  # Change to your hosted URL
    API_KEY = "your-api-key-here"  # Get this from admin
    CLIENT_ID = "Chris"
    
    # Initialize client
    client = DashboardAPIClient(API_URL, API_KEY, CLIENT_ID)
    
    # Check health
    health = client.health_check()
    print(f"Dashboard health: {health}")
    
    # Example: Push account data
    account_info = {
        "balance": 50000.00,
        "equity": 50125.50,
        "margin": 1250.00,
        "free_margin": 48875.50,
        "margin_level": 4010.04,
        "profit": 125.50
    }
    result = client.push_account_data(account_info)
    print(f"Account push result: {result}")
    
    # Example: Push positions
    positions = [
        {
            "ticket": 123456,
            "symbol": "EURUSD",
            "type": "BUY",
            "volume": 0.1,
            "price": 1.0850,
            "current_price": 1.0855,
            "profit": 5.00,
            "sl": 1.0840,
            "tp": 1.0870
        }
    ]
    result = client.push_positions(positions)
    print(f"Positions push result: {result}")
