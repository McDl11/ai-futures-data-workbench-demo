from pathlib import Path
import runpy
import sys


VIEWER_DIR = Path(__file__).resolve().parent / "apps" / "db_viewer"


if __name__ == "__main__":
    sys.path.insert(0, str(VIEWER_DIR))
    runpy.run_path(str(VIEWER_DIR / "app.py"), run_name="__main__")
