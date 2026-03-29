"""
title: Mealie Recipes
author: Alex Norum
version: 0.1.0
description: Query Mealie for recipes, meal plans, and meal suggestions.
"""

import urllib.request
import json
from typing import Any


class Tools:
    def __init__(self):
        self.mealie_url = "http://mealie.mealie:9000"

    def search_recipes(self, query: str) -> str:
        """
        Search for recipes in Mealie by keyword.
        Call this when the user asks about recipes, what to cook, or meal ideas.

        :param query: Search term for recipes (e.g. "chicken", "pasta", "soup")
        :return: List of matching recipes with names and descriptions
        """
        try:
            url = f"{self.mealie_url}/api/recipes?search={urllib.parse.quote(query)}&perPage=10"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                items = data.get("items", [])
                if not items:
                    return f"No recipes found matching '{query}'."
                lines = []
                for r in items:
                    name = r.get("name", "Untitled")
                    desc = r.get("description", "")
                    desc_preview = (desc[:80] + "...") if len(desc) > 80 else desc
                    lines.append(f"- {name}: {desc_preview}" if desc_preview else f"- {name}")
                return f"Found {len(items)} recipes:\n" + "\n".join(lines)
        except Exception as e:
            return f"Error querying Mealie: {e}"

    def get_meal_plan(self) -> str:
        """
        Get the current week's meal plan from Mealie.
        Call this when the user asks what's for dinner, this week's meals, or the meal plan.
        """
        import datetime

        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        end = start + datetime.timedelta(days=6)

        try:
            url = f"{self.mealie_url}/api/groups/mealplans?start_date={start}&end_date={end}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                items = data.get("items", [])
                if not items:
                    return "No meal plan set for this week."
                lines = []
                for m in items:
                    date = m.get("date", "?")
                    entry_type = m.get("entryType", "")
                    title = m.get("title", "") or (m.get("recipe", {}) or {}).get("name", "Untitled")
                    lines.append(f"- {date} ({entry_type}): {title}")
                return "This week's meal plan:\n" + "\n".join(lines)
        except Exception as e:
            return f"Error getting meal plan: {e}"
