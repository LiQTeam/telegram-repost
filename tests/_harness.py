"""Test harness: load bot.* submodules without running the heavy bot/__init__.py."""
import sys, types, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Create a lightweight 'bot' package so relative imports resolve, but WITHOUT
# executing bot/__init__.py (which eagerly imports torch/cv2/Pillow/etc.).
if "bot" not in sys.modules:
    pkg = types.ModuleType("bot")
    pkg.__path__ = [os.path.join(ROOT, "bot")]
    sys.modules["bot"] = pkg
