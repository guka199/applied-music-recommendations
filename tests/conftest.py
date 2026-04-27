import sys
import os

# Ensure the project root and src/ are both on sys.path so that
# both "from src.X import ..." (test style) and "from X import ..." (src style) work.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
for path in (ROOT, SRC):
    if path not in sys.path:
        sys.path.insert(0, path)
