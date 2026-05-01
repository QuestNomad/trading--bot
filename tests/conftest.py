"""
pytest conftest fuer Trading-Bot
Sorgt dafuer dass das code/ Verzeichnis im sys.path landet, damit
Tests `import bot`, `import universe` etc. ohne Installation nutzen koennen.
"""
import os
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

# Verhindere echte Telegram-Calls in Tests
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "0")
