"""
Quick Test Script for Dashboard API
Use this to verify your dashboard API is working correctly before deployment.
"""

import requests
import json
from datetime import datetime


class DashboardTester:
    """Test the dashboard API endpoints."""
    
    def __init__(self, base_url="http://localhost:5001"):
        self.base_url = base_url.rstrip('/')
        self.api_key = None
        self.admin_password = "change_me_in_production"
        
    def test_health(self):
        """Test health check endpoint."""
        print("\n" + "="*60)
        print("TEST: Health Check")
        print("="*60)
        
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=5)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_generate_key(self, admin="TestAdmin", trader="TestTrader", client="TestClient"):
        """Test API key generation."""
        print("\n" + "="*60)
        print("TEST: Generate API Key")
        print("="*60)
        
        data = {
            "admin_password": self.admin_password,
            "trader_info": {
                "admin": admin,
                "trader": trader,
                "client": client
            }
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/admin/generate_key",
                json=data,
                timeout=5
            )
            print(f"Status Code: {response.status_code}")
            result = response.json()
            print(f"Response: {json.dumps(result, indent=2)}")
            
            if result.get("status") == "success":
                self.api_key = result.get("api_key")
                print(f"\n✓ API Key saved for subsequent tests")
                return True
            return False
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_list_keys(self):
        """Test listing API keys."""
        print("\n" + "="*60)
        print("TEST: List API Keys")
        print("="*60)
        
        try:
            response = requests.get(
                f"{self.base_url}/api/admin/list_keys",
                headers={"X-Admin-Password": self.admin_password},
                timeout=5
            )
            print(f"Status Code: {response.status_code}")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_push_account(self):
        """Test pushing account data."""
        print("\n" + "="*60)
        print("TEST: Push Account Data")
        print("="*60)
        
        if not self.api_key:
            print("Error: No API key available. Run test_generate_key first.")
            return False
        
        data = {
            "client_id": "TestClient",
            "account": {
                "balance": 50000.00,
                "equity": 50250.50,
                "margin": 1200.00,
                "free_margin": 49050.50,
                "margin_level": 4187.54,
                "profit": 250.50
            }
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/trader/push_account",
                headers={"X-API-Key": self.api_key},
                json=data,
                timeout=5
            )
            print(f"Status Code: {response.status_code}")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_push_positions(self):
        """Test pushing positions."""
        print("\n" + "="*60)
        print("TEST: Push Positions")
        print("="*60)
        
        if not self.api_key:
            print("Error: No API key available. Run test_generate_key first.")
            return False
        
        data = {
            "client_id": "TestClient",
            "positions": [
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
                },
                {
                    "ticket": 123457,
                    "symbol": "GBPUSD",
                    "type": "SELL",
                    "volume": 0.05,
                    "price": 1.2650,
                    "current_price": 1.2645,
                    "profit": 2.50,
                    "sl": 1.2660,
                    "tp": 1.2630
                }
            ]
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/trader/push_positions",
                headers={"X-API-Key": self.api_key},
                json=data,
                timeout=5
            )
            print(f"Status Code: {response.status_code}")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_push_deals(self):
        """Test pushing deals."""
        print("\n" + "="*60)
        print("TEST: Push Deals")
        print("="*60)
        
        if not self.api_key:
            print("Error: No API key available. Run test_generate_key first.")
            return False
        
        data = {
            "client_id": "TestClient",
            "deals": [
                {
                    "ticket": 789012,
                    "time": "2026-01-07 10:00:00",
                    "symbol": "EURUSD",
                    "type": "BUY",
                    "volume": 0.1,
                    "price": 1.0850,
                    "profit": 15.50
                },
                {
                    "ticket": 789013,
                    "time": "2026-01-07 11:30:00",
                    "symbol": "EURUSD",
                    "type": "SELL",
                    "volume": 0.1,
                    "price": 1.0865,
                    "profit": 15.50
                }
            ]
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/trader/push_deals",
                headers={"X-API-Key": self.api_key},
                json=data,
                timeout=5
            )
            print(f"Status Code: {response.status_code}")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_get_data(self):
        """Test retrieving client data."""
        print("\n" + "="*60)
        print("TEST: Get Client Data")
        print("="*60)
        
        try:
            response = requests.get(
                f"{self.base_url}/api/data?client_id=TestClient",
                timeout=5
            )
            print(f"Status Code: {response.status_code}")
            result = response.json()
            # Pretty print with truncation for large data
            print(f"Response keys: {list(result.keys())}")
            print(f"Account: {result.get('account', {})}")
            print(f"Positions count: {len(result.get('positions', []))}")
            print(f"Deals count: {len(result.get('deals', []))}")
            print(f"Last updated: {result.get('last_updated', 'Never')}")
            return response.status_code == 200
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def test_authentication(self):
        """Test that authentication is required."""
        print("\n" + "="*60)
        print("TEST: Authentication Required")
        print("="*60)
        
        data = {"client_id": "TestClient", "account": {}}
        
        try:
            # Try without API key
            response = requests.post(
                f"{self.base_url}/api/trader/push_account",
                json=data,
                timeout=5
            )
            print(f"Without API Key - Status Code: {response.status_code}")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
            
            # Try with invalid API key
            response = requests.post(
                f"{self.base_url}/api/trader/push_account",
                headers={"X-API-Key": "invalid_key_123"},
                json=data,
                timeout=5
            )
            print(f"\nWith Invalid Key - Status Code: {response.status_code}")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
            
            return True
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("\n" + "#"*60)
        print("# DASHBOARD API TEST SUITE")
        print("#"*60)
        print(f"# Target: {self.base_url}")
        print(f"# Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("#"*60)
        
        results = {}
        
        # Test 1: Health check
        results['health'] = self.test_health()
        
        # Test 2: Generate API key
        results['generate_key'] = self.test_generate_key()
        
        # Test 3: List keys
        results['list_keys'] = self.test_list_keys()
        
        # Test 4: Push account data
        results['push_account'] = self.test_push_account()
        
        # Test 5: Push positions
        results['push_positions'] = self.test_push_positions()
        
        # Test 6: Push deals
        results['push_deals'] = self.test_push_deals()
        
        # Test 7: Get data
        results['get_data'] = self.test_get_data()
        
        # Test 8: Authentication
        results['authentication'] = self.test_authentication()
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        for test_name, passed in results.items():
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"{status:10} {test_name}")
        
        total = len(results)
        passed = sum(results.values())
        print("="*60)
        print(f"Results: {passed}/{total} tests passed")
        print("="*60 + "\n")
        
        return all(results.values())


def main():
    """Main test runner."""
    import sys
    
    # Get base URL from command line or use default
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5001"
    
    print(f"\nTesting dashboard at: {base_url}")
    print("Make sure the dashboard is running first!\n")
    
    tester = DashboardTester(base_url)
    
    # Run all tests
    success = tester.run_all_tests()
    
    if success:
        print("🎉 All tests passed! Dashboard is ready for deployment.\n")
        return 0
    else:
        print("⚠️  Some tests failed. Check the errors above.\n")
        return 1


if __name__ == "__main__":
    exit(main())
