import json
import os

# Define the data based on user input
data = {
    "super_admin": {
        "name": "baller",
        "email": "ballerquotesvpf@gmail.com"
    },
    "admins": {}
}

# Helper to find email for a client
client_emails = {
    "Chris": "chris@blueedgefinancial.com", # VIP
    "Nitin": "Nitinmalhotra20@gmail.com",
    "Cole": "goodwin.icon@gmail.com",
    "J-mark": "traderjmark@gmail.com", # Jmark
    "Jmark": "traderjmark@gmail.com",
    "Tsubasa": "tsubasa.mnb@gmail.com",
    "Taras": "taras@anatsko.com",
    "Ed": "302shmed@gmail.com",
    "Nikita": "nvandervleuten@yahoo.com",
    "Josh B.": "josh.blackman.investing@gmail.com",
    "Josh": "josh.blackman.investing@gmail.com",
    "Jon": "jonathon_rylatt@yahoo.com", # Jonathon
    "Ariel": "ariel@blueedgefinancial.com",
    "Alex M": "mostertalex8@gmail.com",
    "Alex M.": "mostertalex8@gmail.com",
    "Reece": "reecewebb758@outlook.com",
    "Brian S.": "bshore17@gmail.com", # Brian Shore
    "Jason": "jasontracy724@gmail.com",
    "Marcus": "turnermarcus60@gmail.com", # Marcus Turner
    "Thak": "thakmano2@gmail.com", # Thak Mano
    "Barry": "barrywohl78@gmail.com",
    "Steven": "stevefishbach@gmail.com", # Stephen
    "Grzegorz": "fxglobaltrust@gmail.com",
    
    # Private Clients
    "Joe": "joehickenfpf@gmail.com",
    "Tyler": "tyler.arthur.turner@gmail.com",
    "Nate": "natetrade123456@gmail.com", # Nate Hicken
    "Davy": "davyhickenfpf@gmail.com",
    "Rob": "berobsfundsok@gmail.com",
    "Aaron": "millearron1231@icloud.com",
    "Ian": "vpfianh@gmail.com", # Ian Hullinger
    "Kresha": "kreshatrading123@gmail.com",
    "Chanae": "chanaec55@gmail.com",
    "Skyler": "cantrellsky2013@gmail.com",
    "Jeniffer": "jennifermccammon91@gmail.com",
    "Watkins": "jpw.northstar77@gmail.com",
    "Jake Lloyd": "jacoblloyd1214@gmail.com", # Jacob Lyood
    "Andrew": "mackayfutures@gmail.com", # Andrew Mackay
    
    # Others inferred or missing
    "Soklay": "",
    "Nikki": "",
    "Bec": "",
    "Kevin W.": "",
    "David S.": "",
    "Merrison": "",
    "Sagen": "",
    "Jono": "",
    "Halli": "",
    "Daniel P.": ""
}

trader_emails = {
    "Samuel": "tangarasamuel18@gmail.com",
    "Philip": "tangsphilip@gmail.com",
    "Oscar": "odhiambooscar438@gmail.com",
    "Dennis": "dennismuthee.dm@gmail.com",
    "Max": "odhiambovincentmax@gmail.com",
    "Marion": "marionnyika00@gmail.com",
    "Hillary": "litalihillary@gmail.com",
    "Kelvin": "ocharokevinraul17@gmail.com",
    "Fred": "Leexfredleex@gmail.com",
    "Carol": "carolmisoy@gmail.com",
    "Hesbon": "hezimstingofficial@gmail.com"
}

admin_emails = {
    "Philip": "tangsphilip@gmail.com",
    "Max": "odhiambovincentmax@gmail.com",
    "Samuel": "tangarasamuel18@gmail.com"
}

# Hierarchy Structure
hierarchy_structure = {
    "Philip": {
        "Philip": ["Chris", "Joe", "Davy", "Soklay", "Tyler"]
    },
    "Samuel": {
        "Samuel": ["Nikki", "Jon"],
        "Kelvin": ["Cole", "Ed", "Thak", "Steven"],
        "Fred": ["Sagen", "Aaron", "Jono", "Halli", "Alex M."],
        "Oscar": ["J-mark", "Barry", "Daniel P."],
        "Hesbon": ["Taras", "Nate", "David S.", "Reece"]
    },
    "Max": {
        "Max": ["Tsubasa", "Watkins", "Rob"],
        "Carol": ["Ariel", "Josh B.", "Merrison", "Jake Lloyd"],
        "Dennis": ["Bec", "Nitin", "Brian S.", "Jason"],
        "Hillary": ["Ian", "Kevin W.", "Marcus"],
        "Marion": ["Grzegorz", "Andrew"] # Added Marion based on user request "Marion - Grzegorz, Andrew"
    }
}

# Build the JSON
for admin_name, traders in hierarchy_structure.items():
    data["admins"][admin_name] = {
        "email": admin_emails.get(admin_name, ""),
        "traders": {}
    }
    
    for trader_name, clients in traders.items():
        client_objects = []
        for client_name in clients:
            client_objects.append({
                "name": client_name,
                "email": client_emails.get(client_name, "")
            })
            
        data["admins"][admin_name]["traders"][trader_name] = {
            "email": trader_emails.get(trader_name, ""),
            "clients": client_objects
        }

# Save to file
output_path = os.path.join(os.path.dirname(__file__), 'config', 'hierarchy.json')
with open(output_path, 'w') as f:
    json.dump(data, f, indent=4)

print(f"Migration complete. Data saved to {output_path}")
