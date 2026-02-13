FROM python:3.13-slim

# Install system libraries required for HEIC/HEIF decoding via libheif.
# libde265 provides an HEVC decoder used by many iPhone HEIC files.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libheif1 libheif-dev \
    libde265-0 \
    libjpeg62-turbo \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://download.docker.com/linux/static/stable/aarch64/docker-29.1.5.tgz" \
      | tar -xz --strip-components=1 -C /usr/local/bin docker/docker

WORKDIR /app
COPY app /app

# FastAPI server + Pillow + HEIC plugin for Pillow
RUN pip install --no-cache-dir fastapi uvicorn pillow pillow-heif

EXPOSE 8090

# Run the API server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
