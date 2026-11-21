import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
sys.path.insert(0, os.path.join(HERE, "..", "signaling"))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
