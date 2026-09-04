from dotenv import load_dotenv
from pathlib import Path
import os
import json

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment, check your .env file")

BOT_OWNER_ID = os.getenv("BOT_OWNER_ID")
if not BOT_OWNER_ID:
    raise ValueError("BOT_OWNER_ID not found in environment, check your .env file")
BOT_OWNER_ID = int(BOT_OWNER_ID)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.json"

with open(CONFIG_PATH, "r") as f:
    data = json.load(f)

REPO_ROOT = CONFIG_PATH.parent

DB_PATH = REPO_ROOT / data["db_path"]
SCHEMA_PATH = REPO_ROOT / data["schema_path"]
TOD_TRUTHS = REPO_ROOT / data["tod_truths"]
TOD_DARES = REPO_ROOT / data["tod_dares"]
PREFIX = data["global_prefix"]

COG_METADATA = data["cogs"]  # {cog_name: {"is_default": bool, "required_permissions": list[str]}}
DEFAULT_COGS = {name for name, meta in COG_METADATA.items() if meta.get("is_default")}