from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "b_import_sync.py"


def _load():
    spec = importlib.util.spec_from_file_location("b_import_sync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sync_signature_detects_content():
    module = _load()
    paths = [ROOT / "data" / "samples" / "m_sim_tea_products.md", ROOT / "data" / "samples" / "m_sim_tea_sop.md"]
    signature = module._signature(paths)
    assert len(signature) == 2
    assert all(len(value) == 64 for value in signature.values())
    assert signature == module._signature(paths)
