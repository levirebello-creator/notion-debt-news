import os
import requests
from datetime import date
from urllib.parse import quote

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]
GNEWS_API_KEY = os.environ["GNEWS_API_KEY"]

# Search query
query = quote("India debt market")

# GNews API URL
url = (
    f"https://gnews.io/api/v4/search"
    f"?q={query}"
    f"&lang=en"
    f"&max=2"
    f"&apikey={GNEWS_API_KEY}"
)

# Fetch news
response = requests.get(url)
response.raise_for_status()

articles = response.json().get("articles", [])

if len(articles) < 2:
    raise Exception("Less than 2 news articles returned.")

# Notion headers
headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# Create Notion page
payload = {
    "parent": {
        "database_id": DATABASE_ID
    },
    "properties": {
        "News 1 Headline": {
            "title": [
                {
                    "text": {
                        "content": articles[0]["title"]
                    }
                }
            ]
        },
        "Date": {
            "date": {
                "start": str(date.today())
            }
        },
        "Link 1": {
            "url": articles[0]["url"]
        },
        "News 2 Headline": {
    "rich_text": [
        {
            "type": "text",
            "text": {
                "content": articles[1]["title"]
            }
        }
    ]
},
        "Link 2": {
            "url": articles[1]["url"]
        }
    }
}

response = requests.post(
    "https://api.notion.com/v1/pages",
    headers=headers,
    json=payload
)

print(response.status_code)
print(response.text)

response.raise_for_status()

print("✅ Successfully added today's news to Notion.")
