from dotenv import load_dotenv
from pathlib import Path
import os
import json

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment, check your .env file")


with open("config.json", "r") as f:
    data = json.load(f)

DB_PATH = Path(data["db_path"])
SCHEMA_PATH = Path(data["schema_path"])
TOD_TRUTHS = Path(data["tod_truths"])
TOD_DARES = Path(data["tod_dares"])
PREFIX = data["global_prefix"]