from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
__path__ = [str(ROOT / "apps" / "desktop")]
