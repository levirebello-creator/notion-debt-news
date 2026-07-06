"""
check_schema.py
================
One-off diagnostic. Prints the EXACT property names and types Notion
has on record for your database, so we can make config.py match them
byte-for-byte. Run this locally or as a temporary GitHub Actions step,
then paste the output back.

Usage:
    export NOTION_TOKEN=secret_xxx
    export DATABASE_ID=xxxxxxxx
    python check_schema.py
"""
import json
import os

import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]

resp = requests.get(
    f"https://api.notion.com/v1/databases/{DATABASE_ID}",
    headers={
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
    },
)
resp.raise_for_status()
data = resp.json()

print("Database title:", "".join(t["plain_text"] for t in data.get("title", [])))
print()
print("Properties (exact name -> type):")
for name, prop in data.get("properties", {}).items():
    print(f"  {name!r:35s} -> {prop['type']}")
