# Museboard Lite

Museboard is a local, single-user app for organizing images into mood boards and
finding similar images by visual content or color. Create a board, upload images,
and open an image to explore its palette or discover related images across boards.
Search uses your uploaded collection; it does not search the internet.

![description](demo/main.png)
![description](demo/selectImage.png)

## How it works

- **React + TypeScript** provides boards, uploads, processing status, and image discovery.
- **FastAPI** stores image metadata and coordinates a PostgreSQL-backed job queue.
- **Two C++17 CPU workers** use OpenCV to generate thumbnails and five-color palettes.
- **One C++17 AI worker** uses ONNX Runtime and a pretrained CLIP image encoder to
  generate embeddings. PostgreSQL with **pgvector** ranks semantic matches; color
  search compares weighted palettes in LAB color space.

Each upload creates independent CPU and AI jobs. Workers claim jobs through internal
API endpoints; expired jobs can retry, and stale results are rejected. Thumbnails
and palettes remain usable if AI processing fails. Docker Compose runs all services
on one machine, with persistent volumes for the database and images.

## Run locally

Install **Docker Desktop** (or Docker Engine with Compose) and **Python 3.10+**.
Keep Docker running and run these commands from the repository root—the directory
containing `compose.yaml`:

```sh
# Create a private worker credential in .env.
python3 scripts/configure_workers.py

# Download and verify the pinned CLIP model.
python3 scripts/download_model.py

# Build and start the app, database, and workers.
docker compose up -d --build --wait
docker compose ps
```

The initial model download and image builds may take several minutes. Keep `.env`
private; it must not be committed.

| Service | URL |
| --- | --- |
| App | http://localhost:5173 |
| API documentation | http://localhost:8000/docs |
| API health | http://localhost:8000/health |

Create a board and upload still JPEG or PNG images up to **20 MiB each**. Thumbnails,
palettes, and processing badges update automatically. Open an image and select
**Find similar** or **Similar colors** once its corresponding processing finishes.
Results span all boards and exclude the source image.

For an optional sample collection, see [discovery setup](docs/phase4.md#optional-permitted-seed-collection).

## Build and manage the app

Run commands from the repository root.

```sh
# Start existing containers.
docker compose up -d --wait

# Rebuild after changing source or dependencies.
docker compose up -d --build --wait

# Inspect service status and recent logs.
docker compose ps
docker compose logs --tail=100 api cpu-worker ai-worker

# Stop the app while retaining saved data.
docker compose down
```

To rebuild a single service while its dependencies are running, use
`docker compose up -d --build --no-deps web` (replace `web` with `api`,
`cpu-worker`, or `ai-worker` as needed). A container restart alone does not rebuild code.

Boards and images survive ordinary rebuilds and `docker compose down`.
**`docker compose down -v` deletes the saved data volumes.**

## Build and test from source

Docker builds the application without a host C++ compiler or Node.js. To run the
native build and full automated suite below, also install **Node.js 22.12+**,
**CMake 3.20+**, and a C++17 compiler. On macOS, install Xcode Command Line Tools;
the bootstrap script downloads and builds OpenCV and installs ONNX Runtime locally.

### One-time setup

```sh
python3 scripts/configure_workers.py
python3 scripts/download_model.py
docker compose up -d --build --wait db

python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.lock -r backend/requirements-test.txt
npm ci --prefix frontend

# macOS: configure and build native workers, then run CTest.
bash scripts/bootstrap_macos.sh
```

For other native environments, install OpenCV, ONNX Runtime, and libcurl development
files, then configure and build with their actual installation paths:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DOpenCV_DIR=/path/to/opencv/lib/cmake/opencv4 \
  -DONNXRUNTIME_ROOT=/path/to/onnxruntime
cmake --build build --parallel 4
```

### Run checks

```sh
# Compile C++ and test image-processing primitives.
cmake --build build --parallel 4
ctest --test-dir build --output-on-failure

# Test APIs, discovery, job recovery, and the real C++ worker pipeline.
TEST_DATABASE_URL=postgresql://museboard:museboard@127.0.0.1:5433/museboard \
RUN_WORKER_E2E=1 \
backend/.venv/bin/python -m pytest backend/tests -q

# Type-check and build the frontend for production.
npm run build --prefix frontend
```

Database tests use isolated temporary schemas and do not modify your boards.
Without `TEST_DATABASE_URL`, database tests skip. Without `RUN_WORKER_E2E=1`, the
real-worker test skips; it requires the built native worker and downloaded model.
The database must have pgvector installed—the Compose database image includes it.

The [latest validation report](docs/phase4-validation.md) records backend and
real-worker test results plus a successful frontend build. Discovery browser/visual
QA and subjective CLIP relevance still need manual validation.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Docker commands fail | Start Docker and run commands from the repository root. |
| Missing worker credential | Run `python3 scripts/configure_workers.py`. If `.env` already contains an empty `WORKER_TOKEN`, set a nonempty private value and recreate services. |
| Images stay pending | Check `docker compose ps` and worker logs. Verify the model download completed and API/worker credentials match. |
| Changes do not appear | Rebuild the affected service and refresh the browser. |
| Port already in use | Stop other processes using ports 5173, 8000, or 5433. |
| Tests skip | Set the database URL and enable the real-worker test as shown above. |
