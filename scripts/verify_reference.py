"""Compares C++ embeddings with independent Pillow preprocessing and Python inference.

Usage: python scripts/verify_reference.py output/run
Verifies numerical export integration, not parity with original PyTorch weights.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps
from download_model import ROOT, digest

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "models/manifest.json").read_text())
    model = ROOT / "models/vision_model.onnx"
    assert digest(model) == manifest["sha256"], "Model checksum mismatch"
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
    summary = json.loads((args.output / "summary.json").read_text())
    assert summary["failed_images"] == 0, "Some inputs failed"
    assert summary["results"], "No processed images"
    for entry in summary["results"]:
        result = json.loads((args.output / entry["result"]).read_text())
        expected_model = f"{manifest['repository']}@{manifest['revision']}/{manifest['file']}"
        assert result["model_id"] == expected_model
        with Image.open(result["source"]) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        resized = (224, int(224 * height / width)) if width <= height else (int(224 * width / height), 224)
        image = image.resize(resized, Image.Resampling.BICUBIC)
        left, top = (resized[0] - 224) // 2, (resized[1] - 224) // 2
        image = image.crop((left, top, left + 224, top + 224))
        pixels = np.asarray(image, dtype=np.float32) / 255.0
        pixels = (pixels - np.array([0.48145466, 0.4578275, 0.40821073], np.float32)) / np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
        pixels = pixels.transpose(2, 0, 1)[None].copy()
        reference = session.run(["image_embeds"], {"pixel_values": pixels})[0].reshape(-1)
        reference /= np.linalg.norm(reference)
        actual = np.asarray(result["embedding"], dtype=np.float32)
        assert actual.shape == (512,) and np.isfinite(actual).all()
        assert abs(np.linalg.norm(actual) - 1) < 1e-5
        similarity = float(np.dot(actual, reference))
        max_error = float(np.max(np.abs(actual - reference)))
        # Different JPEG decoders and float-vs-fixed-point bicubic rounding may
        # produce tiny differences. Thresholds detect crop/channel/layout errors.
        assert similarity >= 0.999, f"Reference cosine too low: {similarity}"
        assert max_error <= 0.005, f"Reference max error too high: {max_error}"
        assert len(result["palette"]) == 5
        assert abs(sum(c["weight"] for c in result["palette"]) - 1) < 1e-5
        for match in entry["matches"]:
            assert match["source"] != entry["source"], "Self match"
        print(f"{Path(result['source']).name}: cosine={similarity:.8f}, max_abs_error={max_error:.6g}")
    print("Reference checks passed")

if __name__ == "__main__":
    main()
