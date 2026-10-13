# Backend image: FastAPI API + Celery worker share this image.
FROM python:3.11-slim

# ffmpeg (LGPL build from Debian) for audio/video extraction.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Install heavy ML deps only in the worker (see docker-compose build args).
ARG INSTALL_ML=false
RUN if [ "$INSTALL_ML" = "true" ]; then pip install --no-cache-dir -r requirements-ml.txt; fi

# MIDI2ScoreTransformer (required for MusicXML) in its own venv under /opt/m2s.
COPY m2s_worker ./m2s_worker
ARG INSTALL_M2S=true
RUN if [ "$INSTALL_M2S" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends git curl \
      && rm -rf /var/lib/apt/lists/* \
      && M2S_HOME=/opt/m2s M2S_DEVICE=cpu bash m2s_worker/setup_m2s.sh; \
    fi
ENV M2S_PYTHON=/opt/m2s/venv/bin/python \
    M2S_ROOT=/opt/m2s/MIDI2ScoreTransformer \
    M2S_CKPT=/opt/m2s/MIDI2ScoreTF.ckpt

COPY app ./app

ENV STORAGE_DIR=/data
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
