FROM debian:bookworm-slim AS build
ARG TARGETARCH
ARG ONNXRUNTIME_VERSION=1.22.0
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl cmake g++ libopencv-dev libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in arm64) arch=aarch64 ;; amd64) arch=x64 ;; *) exit 1 ;; esac \
    && curl --fail --location --retry 3 "https://github.com/microsoft/onnxruntime/releases/download/v${ONNXRUNTIME_VERSION}/onnxruntime-linux-${arch}-${ONNXRUNTIME_VERSION}.tgz" -o /tmp/ort.tgz \
    && mkdir /opt/onnxruntime && tar -xzf /tmp/ort.tgz --strip-components=1 -C /opt/onnxruntime
RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY CMakeLists.txt ./
COPY include ./include
COPY src ./src
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DONNXRUNTIME_ROOT=/opt/onnxruntime \
    && cmake --build build --target museboard-worker --parallel 2

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libopencv-core406 libopencv-imgproc406 libopencv-imgcodecs406 libcurl4 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home museboard
COPY --from=build /opt/onnxruntime/lib/ /opt/onnxruntime/lib/
COPY --from=build /src/build/museboard-worker /usr/local/bin/museboard-worker
ENV LD_LIBRARY_PATH=/opt/onnxruntime/lib STORAGE_DIR=/data MODEL_PATH=/models/vision_model.onnx
USER museboard
ENTRYPOINT ["museboard-worker"]
