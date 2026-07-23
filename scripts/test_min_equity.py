"""Test get_min_equity() on the running AlphaTrader Chrome session."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from connectors.alphatrader_connector import AlphaTraderConnector
import json

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

# Patch the connector to reuse the running driver
conn = object.__new__(AlphaTraderConnector)
conn._driver = driver
conn._connected = True

stats = conn._get_stats()
print("Header stats:", json.dumps(stats, indent=2))

min_eq = conn.get_min_equity()
print("\nget_min_equity():", json.dumps(min_eq, indent=2))

driver.service.stop()
