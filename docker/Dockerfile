FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./

RUN uv sync --frozen --no-dev

COPY src/ ./src/

# Copy the full dbt project including profiles.yml, which reads MySQL
# connection params from env vars (MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD,
# MYSQL_DATABASE, MYSQL_PORT). The entrypoint runs `dbt compile` at startup
# using --profiles-dir to point dbt at this file, then starts uvicorn.
COPY dbt_health_gen_ai_chat/ ./dbt_health_gen_ai_chat/

COPY docker/entrypoint.sh ./entrypoint.sh
COPY docker/wait_for_mysql.py ./docker/wait_for_mysql.py
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
