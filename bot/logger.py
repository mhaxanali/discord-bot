# bot/logger.py
from datetime import datetime

class Colors:
    RESET = "\033[0m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD_RED = "\033[1;31m"
    MAGENTA = "\033[35m"
    BLUE = "\033[34m"
    GRAY = "\033[90m"


class Logger:
    def _timestamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _print(self, tag: str, color: str, message: str):
        ts = f"{Colors.GRAY}[{self._timestamp()}]{Colors.RESET}"
        tag_fmt = f"{color}[{tag}]{Colors.RESET}"
        print(f"{ts} {tag_fmt} {message}")

    def bot_start(self, user: str, guild_count: int):
        self._print("STARTUP", Colors.GREEN, f"Logged in as {user} | {guild_count} guilds")

    def cog_load(self, name: str, success: bool = True, error: str = None):
        if success:
            self._print("COG", Colors.CYAN, f"Loaded: {name}")
        else:
            self._print("COG", Colors.RED, f"Failed: {name} -> {error}")

    def command(self, user: str, command_name: str, guild: str = "DM"):
        self._print("COMMAND", Colors.MAGENTA, f"{user} ran '{command_name}' in {guild}")

    def error(self, message: str):
        self._print("ERROR", Colors.BOLD_RED, message)

    def warning(self, message: str):
        self._print("WARN", Colors.YELLOW, message)

    def info(self, message: str):
        self._print("INFO", Colors.BLUE, message)
