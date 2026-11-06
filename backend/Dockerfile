# OPTIONAL ONLY — used by infra/docker-compose.optional.yml.
# NOT used in the primary (no-Docker) setup. Fahad: do not build this.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
