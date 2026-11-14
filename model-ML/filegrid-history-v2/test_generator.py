import hashlib
from pathlib import Path
import tempfile
import unittest
from generate import generate
from verify import verify


class HistoryTests(unittest.TestCase):
    def test_repeatable_and_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            a,b=Path(directory)/'a',Path(directory)/'b'
            for folder in (a,b):
                generate(folder,seed=42,start='2024-11-14',end='2024-12-14')
            for path in a.glob('*.csv'):
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),
                                 hashlib.sha256((b/path.name).read_bytes()).digest())
            self.assertEqual(verify(a)['status'],'PASS')

    def test_existing_database_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            generate(folder,start='2024-11-14',end='2024-11-16')
            original=(folder/'stats_contor.csv').read_bytes()
            with self.assertRaises(FileExistsError):
                generate(folder,seed=123,start='2024-11-14',end='2024-11-16')
            self.assertEqual((folder/'stats_contor.csv').read_bytes(),original)

    def test_invalid_period(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                generate(directory,start='2024-11-14',end='2024-11-14')


if __name__=='__main__':
    unittest.main()
