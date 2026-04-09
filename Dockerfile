FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/ ./gateway/
COPY config/example.yaml ./config/example.yaml

CMD ["python3", "-m", "gateway.main", "--config", "config/config.yaml"]
