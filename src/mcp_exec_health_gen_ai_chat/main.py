#!/usr/bin/env python3
import os
import json
from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

mcp = FastMCP("mysql_execution_engine")

# URI with mysql dialect and pymysql driver
MYSQL_URI = os.getenv("MYSQL_ALCHEMY_URI")

# SQLAlchemy Engine initialization with idle connection validation
engine = create_engine(MYSQL_URI, pool_pre_ping=True)

@mcp.tool()
def execute_read_query(sql_query: str) -> str:
    """
    Executes read-only SQL statements (DQL) on the MySQL database engine.
    Accepts any valid SELECT query generated from the semantic layer.
    """
    # Strict restriction on write or structural modification commands
    check_query = sql_query.upper()
    forbidden_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "GRANT", "REPLACE", "TRUNCATE"]
    
    if any(keyword in check_query for keyword in forbidden_keywords):
        return "Security error: Query contains forbidden keywords. Only SELECT processing is allowed."

    try:
        with engine.connect() as connection:
            result = connection.execute(text(sql_query))
            
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            
            return json.dumps(rows, default=str, ensure_ascii=False)
            
    except SQLAlchemyError as e:
        return f"Execution error in MySQL database: {str(e)}"

if __name__ == "__main__":
    mcp.run()