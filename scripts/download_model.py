"""Download the pinned vision-only CLIP export and verify its SHA-256."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

def main():
    manifest = json.loads((ROOT / "models/manifest.json").read_text())
    target = ROOT / "models/vision_model.onnx"
    if target.exists() and digest(target) == manifest["sha256"]:
        print(f"Verified {target}")
        return
    url = f"https://huggingface.co/{manifest['repository']}/resolve/{manifest['revision']}/{manifest['file']}"
    partial = target.with_suffix(".part")
    print(f"Downloading {manifest['bytes'] / 1e6:.0f} MB from {url}", flush=True)
    try:
        # Use the system TLS trust store via curl (python.org macOS installs may
        # lack a configured CA bundle). Certificate verification stays enabled.
        subprocess.run(["curl", "-L", "--fail", "--retry", "3", "--connect-timeout", "30",
                        "--max-time", "900", url, "-o", str(partial)], check=True)
        if partial.stat().st_size != manifest["bytes"] or digest(partial) != manifest["sha256"]:
            raise RuntimeError("Model checksum/size mismatch; download was not installed")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    print(f"Verified {target}")

if __name__ == "__main__":
    main()
