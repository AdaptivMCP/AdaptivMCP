import os
import sys

# Ensure the project root (where main.py lives) is on the import path when running tests.
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
