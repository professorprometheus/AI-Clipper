FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY alpha ./alpha
RUN pip install --no-cache-dir .
COPY migrations ./migrations
COPY web ./web
CMD ["python", "-m", "alpha.cloud"]
