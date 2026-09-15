FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8934

# --host 0.0.0.0 is required here (unlike the native run) -- uvicorn's default
# 127.0.0.1 binds only inside the container's own network namespace and would
# be unreachable through the port mapping.
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8934"]
