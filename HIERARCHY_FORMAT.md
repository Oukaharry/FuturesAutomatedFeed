# Hierarchy JSON Format Reference

This is the exact format our system expects in `config/hierarchy.json`.

```json
{
    "super_admin": {
        "name": "baller",
        "email": "ballerquotesvpf@gmail.com"
    },
    "traders": {
        "Trader Name": {
            "email": "trader@gmail.com"
        }
    },
    "admins": {
        "Admin Name": {
            "email": "admin@gmail.com",
            "slack_user_id": "U0XXXXXXXX",
            "clients": [
                {
                    "name": "Client Name",
                    "email": "client@gmail.com",
                    "category": "Private",
                    "assigned_trader": "Trader Name"
                }
            ]
        }
    }
}
```

## Structure Rules

- **super_admin**: Single object with `name` and `email`
- **traders**: Top-level registry of all traders (key = trader name, value = `{ "email": "..." }`)
- **admins**: Each admin has:
  - `email` (string)
  - `slack_user_id` (string, optional)
  - `clients` (array of client objects)
- **clients**: Each client has:
  - `name` (string)
  - `email` (string)
  - `category` ("Private", "BEF", or "")
  - `assigned_trader` (string, must match a key in the top-level `traders` object)

## Current Traders (15)

| Trader | Email |
|--------|-------|
| Fabian Omondi | fabianlouis99@gmail.com |
| Paul Ayieko | paulayieko123@gmail.com |
| Steve Okok | otienookok19@gmail.com |
| Hezill Hill | hezilhill@gmail.com |
| Gideon Oruma | orumagideon535@gmail.com |
| Felix Ondiek | leexfredleex@gmail.com |
| Tangara | tangsphilip@gmail.com |
| Wayne Ogolla | ogollawayne@gmail.com |
| Julieth Munialo | sharonjulieth002@gmail.com |
| Vincent Odhiambo | odhiambovincentmax@gmail.com |
| Caroline Misoy | carolmisoy@gmail.com |
| Albert Andati | albertandati2@gmail.com |
| Hillary Litali | litalihillary@gmail.com |
| Hesbon Okumu | hezimstingofficial@gmail.com |
| Samuel Tangara | tangarasamuel18@gmail.com |

## Current Admins (8)

| Admin | Email | Slack ID |
|-------|-------|----------|
| Marion Nyika | marionnyika00@gmail.com | U0A09PM2155 |
| Dennis Muthee | dennismuthee.dm@gmail.com | U09QFKLPT3R |
| Kellen Njeri | njerikellen01@gmail.com | U0ACANGNF6H |
| Philip Tangara | tangsphilip@gmail.com | U09N4J4NNGL |
| Joy Ndua | nduajoy43@gmail.com | U0A7H70GW1W |
| Vivian Miano | mianowakini@gmail.com | U0ANM5DE807 |
| Shalline Mukholi | shallinemukholi4@gmail.com | U0AP0GE9H9C |
| Shila Orori | ororilauryn@gmail.com | U0ANM5FRRGX |
