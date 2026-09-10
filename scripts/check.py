from pathlib import Path
import ast
import json
import zipfile

root = Path(__file__).resolve().parents[1]
package = root / "wardrobe_bridge"
for path in package.rglob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

manifest = json.loads((package / "motions" / "manifest.json").read_text(encoding="utf-8"))
assert manifest.get("schema") == 1 and isinstance(manifest.get("clips"), list)

archive = root / "dist" / "wardrobe_bridge.zip"
if archive.exists():
    with zipfile.ZipFile(archive) as handle:
        assert handle.testzip() is None

print("CHECKS_PASSED")

