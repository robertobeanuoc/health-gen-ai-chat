# MCP Server Implementation & Protocol Guide

This README documents the standard JSON-RPC 2.0 commands, schemas, and message structures required to interface with a Model Context Protocol (MCP) server. 

The Model Context Protocol enables host applications (such as LLMs or development environments) to safely and structurally interact with local or remote ecosystems via three primary primitives: **Resources**, **Prompts**, and **Tools**.

---

## 1. Protocol Lifecycle & Core Commands

MCP communication adheres strictly to the JSON-RPC 2.0 specification. All requests must include `jsonrpc: "2.0"`, an `id` (integer or string), a `method` string, and optional `params`.

### 1.1 Initialization
Before executing operations, the client and server must perform a handshake to negotiate capabilities and protocol versions.

#### Client Initialization Request (`initialize`)
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {
      "roots": {
        "listChanged": true
      },
      "sampling": {}
    },
    "clientInfo": {
      "name": "ExampleClient",
      "version": "1.0.0"
    }
  }
}
```

#### Server Initialization Response
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {
      "tools": {
        "listChanged": false
      },
      "resources": {
        "subscribe": true,
        "listChanged": false
      },
      "prompts": {
        "listChanged": false
      }
    },
    "serverInfo": {
      "name": "Custom-MCP-Server",
      "version": "1.0.0"
    }
  }
}
```

#### Client Initialized Notification (`notifications/initialized`)
Sent by the client after receiving the initialization response to signal readiness.
```json
{
  "jsonrpc": "2.0",
  "method": "notifications/initialized"
}
```

---

## 2. Capability Primitives & Schema Examples

### 2.1 Tools (Executable Functions)
Tools allow the LLM to perform actions or computations within the server's environment.

#### List Available Tools (`tools/list`)
**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "fetch_database_schema",
        "description": "Retrieves column metadata and constraints for a specific database table.",
        "inputSchema": {
          "type": "object",
          "properties": {
            "table_name": {
              "type": "string",
              "description": "The fully qualified name of the target table."
            }
          },
          "required": ["table_name"]
        }
      }
    ]
  }
}
```

#### Call a Tool (`tools/call`)
**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "fetch_database_schema",
    "arguments": {
      "table_name": "analytics.fct_orders"
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Table: analytics.fct_orders\nColumns:\n- order_id (INT, PRIMARY KEY)\n- customer_id (INT)\n- total_amount (NUMERIC)"
      }
    ],
    "isError": false
  }
}
```

---

### 2.2 Resources (Data Providers)
Resources expose read-only data, configuration files, or system states to the LLM.

#### List Resources (`resources/list`)
**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "resources/list"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "resources": [
      {
        "uri": "db://metadata/manifest",
        "name": "dbt Core Manifest",
        "description": "Contains compiled structural definitions of the data warehouse models.",
        "mimeType": "application/json"
      }
    ]
  }
}
```

#### Read a Resource (`resources/read`)
**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "resources/read",
  "params": {
    "uri": "db://metadata/manifest"
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "result": {
    "contents": [
      {
        "uri": "db://metadata/manifest",
        "mimeType": "application/json",
        "text": "{\"metadata\": {\"project_name\": \"enterprise_analytics\"}, \"nodes\": {}}"
      }
    ]
  }
}
```

---

### 2.3 Prompts (Template Repositories)
Prompts provide pre-structured system instructions or interactive conversation layouts.

#### List Prompts (`prompts/list`)
**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "prompts/list"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "result": {
    "prompts": [
      {
        "name": "analyze-incident",
        "description": "Template to perform root cause analysis on a technical error log.",
        "arguments": [
          {
            "name": "log_data",
            "description": "Raw string output of the log trace.",
            "required": true
          }
        ]
      }
    ]
  }
}
```

#### Get a Prompt (`prompts/get`)
**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "prompts/get",
  "params": {
    "name": "analyze-incident",
    "arguments": {
      "log_data": "NullPointerException at line 42"
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "result": {
    "description": "Template to perform root cause analysis on a technical error log.",
    "messages": [
      {
        "role": "user",
        "content": {
          "type": "text",
          "text": "Please analyze the following error trace and deduce the failure point: NullPointerException at line 42"
        }
      }
    ]
  }
}
```

---

## 3. Standard Error Codes

When an operation fails, the server must respond with an `error` object inside the JSON-RPC payload instead of a `result`.

| Code | Meaning | Description |
| :--- | :--- | :--- |
| `-32700` | Parse error | Invalid JSON was received by the server. |
| `-32600` | Invalid Request | The JSON sent is not a valid Request object. |
| `-32601` | Method not found | The method does not exist or is not implemented. |
| `-32602` | Invalid params | Invalid method parameters. |
| `-32603` | Internal error | Internal JSON-RPC error. |

### Example Error Response
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": {
    "code": -32602,
    "message": "Invalid parameters: table_name must be a non-empty string."
  }
}
```

---
## References
- [Model Context Protocol Official Specification](https://modelcontextprotocol.io/)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)