# Managed Agents — A股多Agent量化交易系统
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi uvicorn pydantic pyyaml

# Application
COPY . .

# Runtime
EXPOSE 8080
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUTF8=1

# Data volume
VOLUME ["/app/managed_agents_data", "/app/data"]

CMD ["python", "-m", "managed_agents.api.server"]
