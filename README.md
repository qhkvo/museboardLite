# Museboard Lite


## Build 


```sh
# Download dependencies and compiles OpenCV from source
bash scripts/bootstrap_macos.sh
python3 scripts/download_model.py
```

If OpenCV and ONNX Runtime are already installed (including on Linux), configure directly:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=/path/to/opencv/lib/cmake/opencv4 \
  -DONNXRUNTIME_ROOT=/path/to/onnxruntime
cmake --build build --parallel 4
ctest --test-dir build --output-on-failure
python3 scripts/download_model.py
```

## Process the images

From the repository root:

```sh
./build/museboard-prototype --output output/portrait-test-2 tests/images/01-portrait-exif6.jpg tests/images/02-portrait-exif8.jpg

# To process all:
./build/museboard-prototype --output output/similarity-test tests/images/*.jpg tests/images/*.png
```

Use a **new output directory for each run**. Existing outputs are never replaced. Paths with spaces must be quoted. `--model` accepts another location of the **same pinned export**, not arbitrary CLIP variants. Run the downloader to verify the default model checksum.

```text
output/my-first-run/
  image-1/
    thumbnail.jpg
    result.json
  image-2/
    thumbnail.jpg
    result.json
  summary.json
```

Each `result.json` includes the oriented image dimensions, thumbnail path, five palette entries (`hex`, LAB coordinates, and proportional `weight`), normalized embedding, model/preprocessing identifiers, and CPU/AI timings. `summary.json` includes model-load time and matches sorted by descending cosine similarity. Each source image is excluded from its own matches. Scores are similarities, not probabilities.

Invalid inputs print an error; other inputs continue. The process exits nonzero if any image fails, with a failure count in the summary. A one-image run has an empty matches list.

## Processing choices

- Decode JPEG/PNG using OpenCV, apply EXIF orientation, convert grayscale to RGB, and discard PNG alpha (matching Pillow `convert("RGB")`). No ICC color-profile conversion is performed.
- Thumbnails fit within 512×512 without upscaling and preserve aspect ratio.
- Palettes use a sample bounded by 128×128, OpenCV LAB conversion, and deterministic five-cluster k-means. Weights describe the sampled pixels. Solid colors can produce repeated entries; tiny images get zero-weight padding when needed.
- CLIP preprocessing resizes the shortest edge to 224 with antialiased bicubic resampling, center crops 224×224, converts BGR to RGB/NCHW float32, and applies the pinned mean/std. The C++ resampler follows Pillow's kernel; byte-rounding differences are checked with tolerances against Pillow.
- Inference uses the vision-only float32 ONNX export, two CPU threads, and L2-normalized `image_embeds` (512 values). One session is reused across all images.
- This local prototype rejects decoded images over 40 megapixels and CLIP aspect ratios over 100:1. It is not an untrusted-upload service; backend upload validation and process isolation belong to later phases.

## Validate

The CTest executable checks thumbnail geometry, palette weights, tiny images, CLIP RGB/NCHW normalization, and cosine handling. The integration check uses independent Pillow/NumPy preprocessing and Python ONNX Runtime inference on the same pinned export.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements-reference.txt
.venv/bin/python scripts/make_test_images.py
./build/museboard-prototype --output output/fixture-run \
  output/fixtures/landscape.png output/fixtures/landscape-copy.png \
  output/fixtures/landscape-flipped.jpg output/fixtures/portrait.png \
  output/fixtures/noise.png output/fixtures/tiny.png \
  output/fixtures/grayscale.png output/fixtures/alpha.png output/fixtures/oriented.jpg
.venv/bin/python scripts/verify_reference.py output/fixture-run
```

Reference acceptance: cosine ≥ 0.999 and maximum absolute component error ≤ 0.005. These tolerances allow minor decoder/resampler rounding but catch channel, crop, and tensor-layout errors. This verifies C++ integration against a Python implementation of the pinned ONNX pipeline; it does not independently revalidate the export against the original PyTorch checkpoint.

For your own batch, run `scripts/verify_reference.py` against its output directory using the same environment. Timings are local measurements and exclude JSON/JPEG output writes; model-load time is reported separately.
