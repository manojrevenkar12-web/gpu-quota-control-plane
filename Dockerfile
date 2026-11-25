FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir . && useradd -r gqc && mkdir /data && chown gqc /data
ENV GQC_ROOT=/app GQC_DB=/data/gqc.sqlite3
USER gqc
EXPOSE 8080
CMD ["uvicorn", "gqc.service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
