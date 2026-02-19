import requests
import re
import json

def get_sheet_gid(url, tab_name):
    """
    Fetches the public Google Sheet HTML and extracts the GID for a given tab name.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        html = response.text
        
        # Google Sheets embeds data in a script tag, often in `var bootstrapData = ...` or inside `WIZ_global_data`
        # A simple way is to look for the tab name and the gid near it.
        # The structure is often `[...,"Tab Name",...,gid,...]`
        # But parsing is hard. 
        
        # Searching for the tab name might reveal the GID nearby.
        # Let's try a regex that looks for the name and captures numbers around it.
        
        # Pattern analysis: ["Profitability Waterlog",null,"1234567890"
        # Or: {name: "Profitability Waterlog", id: "1234567890"}
        
        # Let's just print a snippet around the tab name to debug, 
        # as the format changes often.
        
        match = re.search(f'"{tab_name}"', html)
        if match:
            start = max(0, match.start() - 100)
            end = min(len(html), match.end() + 100)
            snippet = html[start:end]
            return snippet
        else:
            return "Tab name not found in HTML"
            
    except Exception as e:
        return str(e)

if __name__ == "__main__":
    url = "https://docs.google.com/spreadsheets/d/10eGsivGm5GOaH0orB2AAbjpXzDwDkYY1gIZgux9nIjI/edit?usp=sharing"
    print(get_sheet_gid(url, "Profitability Waterlog"))
