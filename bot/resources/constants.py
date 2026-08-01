from dotenv import load_dotenv
import os
import json

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment, check your .env file")


with open("config.json", "r") as f:
    data = json.load(f)

DB_PATH = data["db_path"]
TOD_TRUTHS = data["tod_truths"]
TOD_DARES = data["tod_dares"]
PREFIX = data["global_prefix"]