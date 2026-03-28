import unittest
import sqlite3
import os
import sys
from unittest.mock import MagicMock

# Mock dependencies before importing app
sys.modules['httpx'] = MagicMock()
sys.modules['fastapi'] = MagicMock()
sys.modules['google'] = MagicMock()
sys.modules['google.generativeai'] = MagicMock()
sys.modules['uvicorn'] = MagicMock()

from app import init_db

class TestDatabase(unittest.TestCase):
    def test_init_db_creates_table(self):
        # Use an in-memory database for testing
        db_path = ':memory:'
        init_db(db_path)

        # Connect to the same in-memory database to verify
        # Note: In-memory databases are connection-specific, but init_db closes the connection.
        # Wait, :memory: is unique per connection. So if init_db closes it, the data is gone.
        # I should use a temporary file instead.

        import tempfile

        fd, test_db = tempfile.mkstemp()
        os.close(fd)

        try:
            init_db(test_db)

            conn = sqlite3.connect(test_db)
            c = conn.cursor()

            # Check if table exists
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pr_tracking'")
            table = c.fetchone()
            self.assertIsNotNone(table, "Table 'pr_tracking' should be created")

            # Check schema
            c.execute("PRAGMA table_info(pr_tracking)")
            columns = {row[1]: row[2] for row in c.fetchall()}

            self.assertIn('pr_number', columns)
            self.assertIn('attempts', columns)
            self.assertIn('status', columns)

            self.assertEqual(columns['pr_number'], 'INTEGER')
            self.assertEqual(columns['attempts'], 'INTEGER')
            self.assertEqual(columns['status'], 'TEXT')

            # Check default value of status
            c.execute("PRAGMA table_info(pr_tracking)")
            for row in c.fetchall():
                if row[1] == 'status':
                    self.assertEqual(row[4], "'PENDING'")

            conn.close()
        finally:
            if os.path.exists(test_db):
                os.remove(test_db)

if __name__ == '__main__':
    unittest.main()
