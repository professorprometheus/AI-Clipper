FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY alpha ./alpha
RUN pip install --no-cache-dir .
COPY migrations ./migrations
COPY web ./web
ENV ALPHA_DATABASE_PATH=/data/alpha.db ALPHA_STORAGE_PATH=/data/storage ALPHA_EMAIL_SINK_PATH=/data/emails
CMD ["python", "-m", "alpha.cloud"]
