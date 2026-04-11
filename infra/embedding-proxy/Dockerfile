FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] httpx sentence-transformers numpy
COPY server.py .
EXPOSE 8004
CMD ["python", "server.py"]
