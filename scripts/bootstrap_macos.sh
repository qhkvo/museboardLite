# Builds minimal OpenCV dependencies and installs ONNX Runtime locally

#!/usr/bin/env bash
# Minimal native dependencies under .deps; no system install or Homebrew required.
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD/.deps"
arch="$(uname -m)"
case "$arch" in arm64|x86_64) ;; *) echo "Unsupported architecture: $arch" >&2; exit 1;; esac
mkdir -p "$root"
if [ ! -d "$root/opencv-4.12.0" ]; then
  curl -L --fail --retry 3 https://github.com/opencv/opencv/archive/refs/tags/4.12.0.tar.gz -o "$root/opencv.tar.gz"
  tar -xzf "$root/opencv.tar.gz" -C "$root"
fi
if [ ! -d "$root/onnxruntime-osx-$arch-1.22.0" ]; then
  curl -L --fail --retry 3 "https://github.com/microsoft/onnxruntime/releases/download/v1.22.0/onnxruntime-osx-$arch-1.22.0.tgz" -o "$root/onnxruntime.tgz"
  tar -xzf "$root/onnxruntime.tgz" -C "$root"
fi
cmake -S "$root/opencv-4.12.0" -B "$root/opencv-build" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES="$arch" \
  -DCMAKE_INSTALL_PREFIX="$root/opencv" \
  -DBUILD_LIST=core,imgproc,imgcodecs -DBUILD_SHARED_LIBS=ON \
  -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF \
  -DBUILD_opencv_apps=OFF -DBUILD_JAVA=OFF -DBUILD_opencv_python3=OFF \
  -DWITH_OPENEXR=OFF -DWITH_TIFF=OFF -DWITH_WEBP=OFF -DWITH_JASPER=OFF \
  -DWITH_JPEGXL=OFF -DWITH_AVIF=OFF -DWITH_OPENJPEG=OFF -DWITH_IPP=OFF \
  -DWITH_FFMPEG=OFF -DWITH_GSTREAMER=OFF -DWITH_VTK=OFF -DWITH_QT=OFF \
  -DWITH_OPENCL=OFF -DWITH_ITT=OFF -DBUILD_PNG=ON -DBUILD_JPEG=ON -DBUILD_ZLIB=ON
cmake --build "$root/opencv-build" --parallel 4
cmake --install "$root/opencv-build"
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES="$arch" \
  -DOpenCV_DIR="$root/opencv/lib/cmake/opencv4" \
  -DONNXRUNTIME_ROOT="$root/onnxruntime-osx-$arch-1.22.0"
cmake --build build --parallel 4
ctest --test-dir build --output-on-failure
