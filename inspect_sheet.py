import pandas as pd
try:
    url = 'https://docs.google.com/spreadsheets/d/1NX46wyWWGVOyb9IyTAEnjQUKfQ6A53Yr8MazhIJVOAY/export?format=csv'
    df = pd.read_csv(url, header=1)
    with open('sheet_info.txt', 'w') as f:
        f.write(str(df.columns.tolist()))
        f.write("\nPROP FIRMS: " + str(df['Prop Firm'].unique()))
except Exception as e:
    print(f"Error: {e}")
