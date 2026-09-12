# Keep the existing Alpine/PostgreSQL 17 base to preserve volume compatibility.
FROM postgres:17-alpine
ARG PGVECTOR_VERSION=0.8.6
RUN apk add --no-cache --virtual .vector-build build-base curl \
    && curl -fsSL "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" | tar xz -C /tmp \
    && cd /tmp/pgvector-${PGVECTOR_VERSION} \
    && make OPTFLAGS="" with_llvm=no \
    && make install with_llvm=no \
    && rm -rf /tmp/pgvector-${PGVECTOR_VERSION} \
    && apk del .vector-build
