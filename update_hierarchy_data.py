import json
import os

hierarchy = {
    "super_admin": {
        "name": "baller",
        "email": "ballerquotesvpf@gmail.com"
    },
    "admins": {
        "Philip": {
            "email": "tangsphilip@gmail.com",
            "traders": {
                "Philip": {
                    "email": "tangsphilip@gmail.com",
                    "clients": [
                        {"name": "Chris", "email": "chris@blueedgefinancial.com"},
                        {"name": "Joe", "email": "joehickenfpf@gmail.com"},
                        {"name": "Davy", "email": "davyhickenfpf@gmail.com"},
                        {"name": "Soklay", "email": ""},
                        {"name": "Tyler", "email": "tyler.arthur.turner@gmail.com"}
                    ]
                }
            }
        },
        "Samuel": {
            "email": "tangarasamuel18@gmail.com",
            "traders": {
                "Samuel": {
                    "email": "tangarasamuel18@gmail.com",
                    "clients": [
                        {"name": "Nikki", "email": ""},
                        {"name": "Jon", "email": "jonathon_rylatt@yahoo.com"}
                    ]
                },
                "Kelvin": {
                    "email": "ocharokevinraul17@gmail.com",
                    "clients": [
                        {"name": "Cole", "email": "goodwin.icon@gmail.com"},
                        {"name": "Ed", "email": "302shmed@gmail.com"},
                        {"name": "Thak", "email": "thakmano2@gmail.com"},
                        {"name": "Steven", "email": "stevefishbach@gmail.com"}
                    ]
                },
                "Fred": {
                    "email": "Leexfredleex@gmail.com",
                    "clients": [
                        {"name": "Sagen", "email": ""},
                        {"name": "Aaron", "email": "millearron1231@icloud.com"},
                        {"name": "Jono", "email": ""},
                        {"name": "Halli", "email": ""},
                        {"name": "Alex M.", "email": "mostertalex8@gmail.com"}
                    ]
                },
                "Oscar": {
                    "email": "odhiambooscar438@gmail.com",
                    "clients": [
                        {"name": "J-mark", "email": "traderjmark@gmail.com"},
                        {"name": "Barry", "email": "barrywohl78@gmail.com"},
                        {"name": "Daniel P.", "email": ""}
                    ]
                },
                "Hesbon": {
                    "email": "hezimstingofficial@gmail.com",
                    "clients": [
                        {"name": "Taras", "email": "taras@anatsko.com"},
                        {"name": "Nate", "email": "natetrade123456@gmail.com"},
                        {"name": "David S.", "email": ""},
                        {"name": "Reece", "email": "reecewebb758@outlook.com"}
                    ]
                }
            }
        },
        "Max": {
            "email": "odhiambovincentmax@gmail.com",
            "traders": {
                "Max": {
                    "email": "odhiambovincentmax@gmail.com",
                    "clients": [
                        {"name": "Tsubasa", "email": "tsubasa.mnb@gmail.com"},
                        {"name": "Watkins", "email": "jpw.northstar77@gmail.com"},
                        {"name": "Rob", "email": "berobsfundsok@gmail.com"}
                    ]
                },
                "Carol": {
                    "email": "carolmisoy@gmail.com",
                    "clients": [
                        {"name": "Ariel", "email": "ariel@blueedgefinancial.com"},
                        {"name": "Josh B.", "email": "josh.blackman.investing@gmail.com"},
                        {"name": "Merrison", "email": ""},
                        {"name": "Jake Lloyd", "email": "jacoblloyd1214@gmail.com"}
                    ]
                },
                "Dennis": {
                    "email": "dennismuthee.dm@gmail.com",
                    "clients": [
                        {"name": "Bec", "email": ""},
                        {"name": "Nitin", "email": "Nitinmalhotra20@gmail.com"},
                        {"name": "Brian S.", "email": "bshore17@gmail.com"},
                        {"name": "Jason", "email": "jasontracy724@gmail.com"}
                    ]
                },
                "Hillary": {
                    "email": "litalihillary@gmail.com",
                    "clients": [
                        {"name": "Ian", "email": "vpfianh@gmail.com"},
                        {"name": "Kevin W.", "email": ""},
                        {"name": "Marcus", "email": "turnermarcus60@gmail.com"}
                    ]
                },
                "Marion": {
                    "email": "marionnyika00@gmail.com",
                    "clients": [
                        {"name": "Grzegorz", "email": "fxglobaltrust@gmail.com"},
                        {"name": "Andrew", "email": "mackayfutures@gmail.com"}
                    ]
                }
            }
        }
    }
}

with open('config/hierarchy.json', 'w') as f:
    json.dump(hierarchy, f, indent=4)

print("Hierarchy updated successfully.")
