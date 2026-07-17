FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e . \
    && adduser --system --no-create-home appuser

COPY server.py ./

EXPOSE 8004
ENV MCP_TRANSPORT=http

USER appuser

CMD ["python", "server.py"]
