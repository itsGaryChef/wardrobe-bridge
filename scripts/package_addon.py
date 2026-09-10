from pathlib import Path
import ast
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
package = root / "wardrobe_bridge"
dist = root / "dist"
dist.mkdir(exist_ok=True)

for path in package.rglob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

archive_path = dist / "wardrobe_bridge.zip"
with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in package.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            archive.write(path, path.relative_to(root))

with zipfile.ZipFile(archive_path) as archive:
    assert archive.testzip() is None
    assert "wardrobe_bridge/__init__.py" in archive.namelist()

print(archive_path)

