# Museboard Lite

### First-time startup

1. Install Docker Desktop if needed, then open it and wait until the engine is running.
2. Open a terminal in the repository root (the folder containing `compose.yaml`).
   In VS Code, use **Terminal → New Terminal** with this project open.
3. Build and start the frontend, backend, and PostgreSQL together:

```sh
docker compose up --build -d
```

`--build` builds the application containers; `-d` keeps them running in the background.
The first run downloads dependencies and may take several minutes. Later runs reuse
cached images and dependencies.

Check that the services have started:

```sh
docker compose ps
```

Expect `web`, `api`, and `db` to be running, with `api` and `db` marked healthy.

| Service | Address | Purpose |
| --- | --- | --- |
| Web UI | [localhost:5173](http://localhost:5173) | Create boards, upload images, and browse collections |
| API documentation | [localhost:8000/docs](http://localhost:8000/docs) | Explore and try the backend endpoints |
| API health | [localhost:8000/health](http://localhost:8000/health) | Confirm the API can reach PostgreSQL |

Create a board in the UI, then drag in JPEG/PNG images or use **Add images**.
The app uploads up to three files concurrently, displays per-file progress/errors,
and lets you open each original image. Uploads are limited to 20 MiB per file.

**No C++ bootstrap, Node.js installation, or Python virtual environment is needed to
run the Phase 2 app through Docker.** Those tools are only needed when developing or
testing outside the containers, or using the separate Phase 1 prototype.

### Everyday commands

Run these from the repository root with Docker Desktop running:

| Task | Command |
| --- | --- |
| Start the app with no code changes | `docker compose up -d` |
| Rebuild after frontend or backend changes | `docker compose up --build -d` |
| Rebuild only the frontend | `docker compose up -d --build --no-deps web` |
| Rebuild only the backend | `docker compose up -d --build --no-deps api` |
| Check running services | `docker compose ps` |
| Follow backend logs | `docker compose logs -f api` |
| Follow frontend/proxy logs | `docker compose logs -f web` |
| View recent database logs | `docker compose logs --tail=100 db` |
| View recent logs for all services | `docker compose logs --tail=100` |
| Restart existing containers | `docker compose restart` |
| Stop and remove containers, keeping saved data | `docker compose down` |

The single-service rebuild commands assume the other services are already running.
`restart` does **not** rebuild changed source code; use `up --build -d` for that.
The Docker frontend serves a production build, so refresh the browser after rebuilding.
Press **Ctrl+C** to stop following logs; the containers keep running.

### Saved data

Boards and image records live in the `postgres_data` Docker volume. Original image
files live in the `image_data` Docker volume. Both survive `docker compose down`
and ordinary rebuilds, so you can stop the app and continue later.

**Do not run `docker compose down -v` unless you intend to erase all boards and
uploaded images.** The `-v` option removes these volumes. Git commits and pushes do
not back up Docker volumes.

This is a local single-user build bound to localhost, not a public authenticated
deployment. Automatic C++ processing is planned for Phase 3.

### Troubleshooting

| Symptom | What to check |
| --- | --- |
| “Cannot connect to the Docker daemon” | Open Docker Desktop and wait for it to finish starting, then rerun the command. |
| “No configuration file provided” | Run the command from the folder containing `compose.yaml`. |
| Browser cannot connect | Run `docker compose ps`. If services stopped, use `docker compose up -d` and inspect the logs. |
| UI loads but boards/uploads fail | Check `docker compose logs --tail=100 api` and the API health address above. |
| Code changes do not appear | Run `docker compose up --build -d`, then refresh the browser. |
| “Port is already allocated” | Check for another app or local development server using ports 5173, 8000, or 5433; stop the conflicting service before starting this stack. |
| Upload rejected | Use a valid, still JPEG/PNG under 20 MiB; WebP and animated images are not supported. The UI gives the specific reason. |

### To run automated API tests:
Install Python 3.10+ locally and keep the database running:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.lock -r backend/requirements-test.txt
TEST_DATABASE_URL=postgresql://museboard:museboard@127.0.0.1:5433/museboard backend/.venv/bin/python -m pytest backend/tests -q
```

The tests create and remove their own temporary database schemas, not your boards.
Without `TEST_DATABASE_URL`, database tests are skipped. The environment setup is
one-time; rerun the final command for later checks.

For a frontend type check and build outside Docker, install Node.js 22.12+:

```sh
npm ci --prefix frontend
npm run build --prefix frontend
```

## P1: To build the C++ prototype


```sh
# Download dependencies and compiles OpenCV from source
bash scripts/bootstrap_macos.sh
python3 scripts/download_model.py
```

The bootstrap compiles OpenCV on the first run. You do not need to repeat it each
time you process images. After editing C++ source, use:

```sh
cmake --build build --parallel 4
ctest --test-dir build --output-on-failure
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

### Process images with the C++ prototype

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

### Processing choices

- Decode JPEG/PNG using OpenCV, apply EXIF orientation, convert grayscale to RGB, and discard PNG alpha (matching Pillow `convert("RGB")`). No ICC color-profile conversion is performed.
- Thumbnails fit within 512×512 without upscaling and preserve aspect ratio.
- Palettes use a sample bounded by 128×128, OpenCV LAB conversion, and deterministic five-cluster k-means. Weights describe the sampled pixels. Solid colors can produce repeated entries; tiny images get zero-weight padding when needed.
- CLIP preprocessing resizes the shortest edge to 224 with antialiased bicubic resampling, center crops 224×224, converts BGR to RGB/NCHW float32, and applies the pinned mean/std. The C++ resampler follows Pillow's kernel; byte-rounding differences are checked with tolerances against Pillow.
- Inference uses the vision-only float32 ONNX export, two CPU threads, and L2-normalized `image_embeds` (512 values). One session is reused across all images.
- This local prototype rejects decoded images over 40 megapixels and CLIP aspect ratios over 100:1. It is not an untrusted-upload service; backend upload validation and process isolation belong to later phases.

### Validate the C++ prototype

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