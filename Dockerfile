FROM python:3.12.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GRAPHITI_TELEMETRY_ENABLED=false
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps --no-build-isolation . && useradd -u 10001 -m memory \
    && mkdir -p /app/data /app/config && chown -R memory:memory /app/data /app/config
USER memory
EXPOSE 8080
CMD ["active-memory", "serve"]
