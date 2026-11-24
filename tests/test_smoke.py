import unittest
import src

class TestSmoke(unittest.TestCase):
    def test_version(self):
        self.assertEqual(src.__version__, "1.0.0")

if __name__ == "__main__":
    unittest.main()
