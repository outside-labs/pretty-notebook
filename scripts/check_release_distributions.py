"""Verify that the compatibility distribution cannot own implementation files."""

from email.parser import BytesParser
from pathlib import Path
import tomllib
from zipfile import ZipFile


def check_distributions(directory=Path("dist")):
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    version = project["version"]
    for name in ("pretty-notebook", "pnbp"):
        wheel_path, = (directory / name).glob("*.whl")
        with ZipFile(wheel_path) as wheel:
            files = wheel.namelist()
            metadata_path, = [path for path in files if path.endswith(".dist-info/METADATA")]
            metadata = BytesParser().parsebytes(wheel.read(metadata_path))
            assert metadata["Name"].replace("_", "-") == name
            assert metadata["Version"] == version
            assert metadata["Requires-Python"] == ">=3.11"
            assert metadata["License-Expression"] == "MIT"
            if name == "pnbp":
                assert metadata.get_all("Requires-Dist") == [f"pretty-notebook=={version}"]
                assert all(".dist-info/" in path for path in files), "Bridge must contain metadata only"
                assert not any(path.endswith("entry_points.txt") for path in files)
            else:
                requirements = metadata.get_all("Requires-Dist", [])
                assert not any(item.lower().startswith("markdown") and ";" not in item for item in requirements), "Python-Markdown must remain optional"
                assert "pretty_notebook/markdown/parser.py" in files
                assert "pretty_notebook/markdown/dialect.py" in files
                assert "pretty_notebook/__init__.py" in files
                assert "pnbp/__init__.py" in files
                assert any(path.startswith("pretty_notebook/resources/deploy/") for path in files)
    print(f"Verified matching {version} distributions and metadata-only pnbp compatibility package.")


if __name__ == "__main__":
    check_distributions()
