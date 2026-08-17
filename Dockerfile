FROM python:3.13-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY alpha ./alpha
RUN pip install --no-cache-dir .
COPY migrations ./migrations
COPY web ./web
CMD ["python", "-m", "alpha.cloud"]
