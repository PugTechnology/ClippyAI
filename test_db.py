import unittest
import os
import tempfile
from unittest.mock import MagicMock, patch
import sys

# Mock modules before importing app
sys.modules['google'] = MagicMock()
sys.modules['google.genai'] = MagicMock()
sys.modules['fastapi'] = MagicMock()
sys.modules['httpx'] = MagicMock()

import app

class TestAppDB(unittest.TestCase):
    def test_get_db_connection(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            conn = app.get_db_connection(path)
            self.assertIsNotNone(conn)
            conn.close()
        finally:
            os.remove(path)

    def test_init_db(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            app.init_db(path)
            conn = app.get_db_connection(path)
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pr_tracking'")
            self.assertIsNotNone(c.fetchone())
            conn.close()
        finally:
            os.remove(path)

if __name__ == '__main__':
    unittest.main()
