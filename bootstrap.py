import os
import sys

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Ensure the local 'app' package is used, not any site-packages 'app'
if 'app' in sys.modules:
    mod = sys.modules['app']
    file = getattr(mod, '__file__', '') or ''
    if not file.startswith(ROOT_DIR):
        del sys.modules['app']