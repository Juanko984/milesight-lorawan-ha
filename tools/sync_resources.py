"""Copy the repo's blueprints/ and dashboards/ into the integration package (resources/), which is what HACS
installs. Run before every release:  python3 tools/sync_resources.py"""
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
RES = ROOT / "custom_components" / "milesight_lorawan" / "resources"
PAIRS = [(ROOT / "blueprints" / "automation" / "milesight_lorawan", RES / "blueprints", "*.yaml"),
         (ROOT / "dashboards", RES / "dashboards", "*.yaml")]
SKIP = {"building_overview.example.yaml"}       # example only: the integration generates this one

for src, dst, pattern in PAIRS:
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob(pattern)):
        if f.name not in SKIP:
            shutil.copyfile(f, dst / f.name)
            print("copied", f.relative_to(ROOT))
