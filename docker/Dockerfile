FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./

RUN uv sync --frozen --no-dev

COPY src/ ./src/
COPY dbt_health_gen_ai_chat/target/ ./dbt_health_gen_ai_chat/target/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.chat_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
