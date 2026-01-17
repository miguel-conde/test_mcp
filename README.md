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