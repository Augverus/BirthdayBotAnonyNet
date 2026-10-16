"""Tests for configuration helpers."""
import unittest
from pathlib import Path

import config


class ResolveDbPathTests(unittest.TestCase):
    def test_relative_path_is_resolved_against_base_dir(self):
        self.assertEqual(config.resolve_db_path(Path('/srv/bot'), 'birthdays.db'),
                         '/srv/bot/birthdays.db')

    def test_nested_relative_path_is_resolved(self):
        self.assertEqual(config.resolve_db_path(Path('/srv/bot'), 'data/x.db'),
                         '/srv/bot/data/x.db')

    def test_absolute_path_is_untouched(self):
        self.assertEqual(config.resolve_db_path(Path('/srv/bot'), '/data/x.db'), '/data/x.db')

    def test_memory_database_is_untouched(self):
        self.assertEqual(config.resolve_db_path(Path('/srv/bot'), ':memory:'), ':memory:')

    def test_configured_default_is_absolute(self):
        # The env default must never depend on the process working directory.
        self.assertTrue(Path(config.resolve_db_path(Path('/srv/bot'), 'birthdays.db')).is_absolute())


if __name__ == '__main__':
    unittest.main()
