FROM python:3.12-slim

WORKDIR /app

# Install worker dependencies
COPY worker/requirements.txt ./worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt

# Copy agent schemas (worker imports from agent.schemas)
COPY agent/ ./agent/

# Copy worker source
COPY worker/ ./worker/

CMD ["python", "-m", "worker.consumer"]