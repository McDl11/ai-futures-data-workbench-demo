from pathlib import Path
import runpy
import sys


SYSTEM_DIR = Path(__file__).resolve().parent / "services" / "report_system"


if __name__ == "__main__":
    sys.path.insert(0, str(SYSTEM_DIR))
    runpy.run_path(str(SYSTEM_DIR / "health_check.py"), run_name="__main__")
