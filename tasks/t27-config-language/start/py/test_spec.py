"""Runs the examples in cases/: python3 -m unittest test_spec"""
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Spec(unittest.TestCase):
    def test_cases(self) -> None:
        for case in sorted((HERE / "cases").iterdir()):
            with self.subTest(case=case.name):
                expected = (case / "expected").read_text(encoding="utf-8")
                done = subprocess.run([sys.executable, str(HERE / "solution.py"), str(case / "main.conf")],
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(done.stdout, expected)
                self.assertEqual(done.returncode, 1 if expected.startswith("error ") else 0)


if __name__ == "__main__":
    unittest.main()
