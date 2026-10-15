"""Test suite for the birthday bot.

Importing this package prepares the environment so ``config`` can be imported
without a real bot token and without ever touching the production database.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Must be set before ``config`` is imported (it reads env at import time).
# ``load_dotenv`` never overrides variables that already exist, so a developer's
# local .env cannot leak real values into the tests.
os.environ.setdefault('BOT_TOKEN', '123456:TEST-TOKEN-FOR-UNIT-TESTS')
os.environ.setdefault('ADMIN_IDS', '1001,1002')
os.environ.setdefault('DB_PATH', ':memory:')
os.environ.setdefault('WEBAPP_URL', '')
