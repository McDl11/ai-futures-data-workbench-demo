from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
APPS_DIR = ROOT / "apps"

if APPS_DIR.exists():
    apps_path = str(APPS_DIR)
    if apps_path not in sys.path:
        sys.path.insert(0, apps_path)
