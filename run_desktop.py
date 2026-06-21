from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
APPS_DIR = ROOT / "apps"
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))

from desktop.app import main


if __name__ == "__main__":
    raise SystemExit(main())
