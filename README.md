# Todo MCP Server

A simple Model Context Protocol (MCP) server for managing todo lists. This is a learning project to understand how MCP servers work.

## Features

Our Todo MCP Server provides the following tools:

### 🔧 Available Tools

1. **add_todo(title, description)** - Add a new todo item
2. **list_todos(show_completed)** - List all todos (optionally include completed)
3. **complete_todo(todo_id)** - Mark a todo as completed
4. **delete_todo(todo_id)** - Delete a todo item
5. **get_todo_stats()** - Get statistics about your todos

## Setup

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the server:
   ```bash
   python todo_server.py
   ```

## Usage with AI Toolkit

1. Open AI Toolkit in VS Code
2. Go to the Agent Builder
3. Add this MCP server by pointing to the `todo_server.py` file
4. Test the tools in the playground!

## Run with VS Code MCP (RLM Corpus Server)

See `docs/setup_mcp.md` for a step-by-step guide to run the RLM corpus MCP server from VS Code. The guide includes creating a virtualenv, installing dependencies, placing a sample `.vscode/mcp.json` configuration (provided in the repo), and verifying the server inside Copilot Chat with a `load_corpus → search_corpus → exec_repl` smoke flow. Note: `OPENAI_API_KEY` is only required when experimental `llm_query` is enabled.

## RestrictedPython sandbox (optional)

The RLM REPL can run user code inside a RestrictedPython sandbox for production hardening. This is disabled by default to keep local development and tests fast and predictable.

- To enable the sandbox set the environment variable `RLM_USE_RESTRICTED_PYTHON=1` before starting the server. Ensure `RestrictedPython` is installed (it's listed in `requirements.txt`).

Example:

```bash
export RLM_USE_RESTRICTED_PYTHON=1
python rlm_corpus_server.py
```

When enabled the sandbox restricts imports and builtins. Allowed modules by default: `math`, `re`, `json`. Common helpers (`enumerate`, `range`, `len`, `sum`, `min`, `max`, `sorted`, `zip`, `map`, `filter`, `any`, `all`, `print`) remain available. Consult `plans/rlm-corpus-server/implementation.md` for details on extending the whitelist safely.

## Example Usage

Once connected, you can use commands like:

- "Add a todo to buy groceries"
- "Show me all my todos"
- "Mark todo #1 as complete"
- "Delete todo #2"
- "Show me my todo statistics"

## Data Storage

Todos are stored in `todos.json` in the same directory as the server, so they persist between runs.

## Learning Notes

This MCP server demonstrates:

- ✅ Tool definition with proper type hints
- ✅ JSON Schema generation for parameters
- ✅ Data persistence
- ✅ Error handling
- ✅ User-friendly responses
- ✅ FastMCP framework usage