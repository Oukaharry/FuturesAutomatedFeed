
import requests
import urllib.parse
from io import BytesIO
import sys

try:
    import openpyxl
except ImportError:
    print("Openpyxl not installed")

def test_fetch(sheet_url):
    print(f"Testing URL: {sheet_url}")
    
    # Extract Key
    try:
        if '/d/' in sheet_url:
            sheet_key = sheet_url.split('/d/')[1].split('/')[0]
            print(f"Key: {sheet_key}")
        else:
            print("Could not extract key")
            return
    except:
        print("Error extracting key")
        return

    # Try XLSX Export
    base_url_xlsx = f"https://docs.google.com/spreadsheets/d/{sheet_key}/export"
    params_xlsx = {'format': 'xlsx'}
    
    # Check for GID in URL
    gid = None
    if 'gid=' in sheet_url:
        try:
            # Handle ?gid=123 (query) or #gid=123 (fragment)
            if '?gid=' in sheet_url:
                gid = sheet_url.split('gid=')[1].split('&')[0].split('#')[0]
            elif '#gid=' in sheet_url:
                gid = sheet_url.split('#gid=')[1].split('&')[0]
            
            if gid:
                params_xlsx['gid'] = gid
                print(f"Using GID: {gid}")
        except:
            print("Could not extract GID")
    
    xlsx_url = base_url_xlsx + "?" + urllib.parse.urlencode(params_xlsx)
    
    print(f"Attempting XLSX fetch: {xlsx_url}")
    try:
        resp = requests.get(xlsx_url, timeout=30)
        print(f"XLSX Status Code: {resp.status_code}")
        if resp.status_code == 200:
            if b'<html' in resp.content.lower():
                 print("XLSX returned HTML (likely login page/error)")
            else:
                try:
                    wb = openpyxl.load_workbook(filename=BytesIO(resp.content), data_only=True)
                    ws = wb.active
                    print(f"XLSX Success. Active sheet: {ws.title}")
                    
                    # Also count comments
                    comment_count = 0
                    for row in ws.iter_rows():
                        for cell in row:
                            if cell.comment:
                                comment_count += 1
                    print(f"Found {comment_count} comments.")
                                
                except Exception as e:
                    print(f"XLSX Parse Error: {e}")
        else:
            print(f"XLSX Failed")
    except Exception as e:
        print(f"XLSX Request Error: {e}")

    # Try CSV Export
    base_url_csv = f"https://docs.google.com/spreadsheets/d/{sheet_key}/export"
    params_csv = {'format': 'csv'}
    if gid:
        params_csv['gid'] = gid
        
    csv_url = base_url_csv + "?" + urllib.parse.urlencode(params_csv)
    
    print(f"Attempting CSV fetch: {csv_url}")
    try:
        resp = requests.get(csv_url, timeout=30)
        print(f"CSV Status Code: {resp.status_code}")
        if resp.status_code == 200:
            if '<html' in resp.text.lower():
                print("CSV returned HTML (likely login page/error)")
            else:
                print("CSV Success (Content detected)")
                print(resp.text[:200])
        else:
             print(f"CSV Failed")
    except Exception as e:
        print(f"CSV Request Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = "https://docs.google.com/spreadsheets/d/1ivVtySJKJveJHNg9Hs4kH8fTqWDgMQMOxkYCPxIMtQM/edit?usp=sharing"
    test_fetch(url)
