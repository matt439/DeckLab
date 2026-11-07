"""Run the disposable headless UI review from any working directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decklab.ui_review.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
