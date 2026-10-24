# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    kicad=9.0.8+dfsg-1 kicad-footprints=9.0.7-1 kicad-symbols=9.0.7-1 python3-pil python3-reportlab \
    python3-shapely python3-numpy python3-scipy python3-sexpdata \
    poppler-utils ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
ENV HOME=/tmp/kicad-home
