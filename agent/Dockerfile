# Vortex agent 
FROM python:3.12-slim

WORKDIR /app

# System deps: none needed yet — psutil and redis-py are pure-Python/wheel installs.

COPY agent/requirements.txt agent/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt

# Copy the Phase 1 collector package and the agent package itself.
# Both are needed: agent/main.py does `from collector import collect_snapshot`.
COPY collector/ collector/
COPY agent/ agent/

# Run as a module so the relative import (`from .transform import ...`) works.
CMD ["python", "-m", "agent.main"]