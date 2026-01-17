# Todo Manager MCP Server

A comprehensive example of a Model Context Protocol (MCP) server implementation that provides todo management capabilities. This serves as an educational resource for learning how to build MCP servers.

## Overview

This todo manager demonstrates:
- **MCP Server Structure**: Proper server setup, tool definitions, and resource management
- **Tool Implementation**: CRUD operations with proper error handling and validation
- **Resource Endpoints**: Exposing data through MCP resources
- **State Persistence**: File-based storage for todos
- **Client Interaction**: Example client code showing how to connect and use MCP servers

## Features

### Tools (Actions)
- `add_todo` - Add a new todo item with title and optional description
- `list_todos` - List todos with filtering (all/pending/completed) and statistics
- `get_todo` - Get detailed information about a specific todo
- `toggle_todo` - Mark a todo as complete/incomplete
- `delete_todo` - Remove a todo item
- `clear_completed` - Remove all completed todos

### Resources (Data Access)
- `todos://all` - JSON data of all todo items
- `todos://pending` - JSON data of pending todos only  
- `todos://completed` - JSON data of completed todos only

### Data Persistence
- Todos are stored in `todos.json` file
- Automatic loading/saving on server start/operations
- Graceful handling of missing or corrupted data files

## Installation

1. Install required dependencies:
```bash
pip install mcp
```

2. Ensure you have the MCP library available in your Python environment.

## Usage

### Running the Server

Start the MCP server:
```bash
python todo_mcp_server.py
```

The server will run using stdio communication, which is the standard for MCP servers.

### Running the Demo Client

Run the automated demo:
```bash
python test_todo_client.py
```

This will demonstrate all the server capabilities with sample data.

### Running the Interactive Client

For hands-on exploration:
```bash
python test_todo_client.py interactive
```

Available commands in interactive mode:
- `add <title> [description]` - Add a new todo
- `list [all|pending|completed]` - List todos with optional filtering
- `get <id>` - Get details of a specific todo
- `toggle <id>` - Toggle completion status
- `delete <id>` - Delete a todo
- `clear` - Remove all completed todos
- `tools` - Show available MCP tools
- `resources` - Show available MCP resources
- `help` - Show help message
- `quit` - Exit the client

### Example Session

```
todo> add "Learn MCP" "Study Model Context Protocol"
✅ Todo added successfully!

ID: 1
Title: Learn MCP
Description: Study Model Context Protocol
Created: 2026-01-17T10:30:00.123456

todo> add "Build todo app"
✅ Todo added successfully!

ID: 2
Title: Build todo app
Description: 
Created: 2026-01-17T10:30:15.789012

todo> list all
📝 All Todos (2 items):

⏳ [1] Learn MCP
    📄 Study Model Context Protocol

⏳ [2] Build todo app

📊 Statistics:
   Total: 2
   Completed: 0
   Pending: 2

todo> toggle 1
✅ Todo 'Learn MCP' marked as completed!

todo> list pending
📝 Pending Todos (1 items):

⏳ [2] Build todo app
```

## Learning Points

This example demonstrates several key MCP concepts:

### 1. Server Setup
- Proper MCP server initialization with `mcp.server.Server`
- Stdio communication setup for standard MCP interaction
- Capabilities declaration and initialization options

### 2. Tool Definition
- JSON Schema for input validation
- Proper error handling and user-friendly responses  
- Consistent return format using `types.TextContent`

### 3. Resource Management
- Multiple resource endpoints with different data views
- JSON serialization for structured data access
- Dynamic resource content based on current state

### 4. Data Management
- Persistence layer with file-based storage
- Data model with proper serialization/deserialization
- State management and consistency

### 5. Client Integration
- Proper client session management
- Tool calling with parameter validation
- Resource reading and data processing

## Architecture

```
todo_mcp_server.py
├── TodoItem (Data Model)
├── TodoManager (Business Logic)
├── MCP Server Setup
├── Tool Handlers (@server.call_tool)
├── Resource Handlers (@server.read_resource)
└── Main Server Loop

test_todo_client.py
├── Demo Mode (Automated demonstration)
├── Interactive Mode (User-driven testing)
├── Client Session Management
└── Command Processing
```

## File Structure

- `todo_mcp_server.py` - Main MCP server implementation
- `test_todo_client.py` - Example client with demo and interactive modes
- `todos.json` - Persistent storage file (created automatically)
- `README.md` - This documentation file

## Educational Value

This example is designed to teach:

1. **MCP Fundamentals**: Understanding the protocol, tools vs resources, client-server communication
2. **Server Implementation**: How to structure an MCP server, handle different operations, manage state
3. **Client Integration**: How applications can connect to and utilize MCP servers
4. **Best Practices**: Error handling, input validation, user experience, documentation

## Extending the Example

Ideas for extending this todo manager:

1. **Enhanced Features**:
   - Due dates and reminders
   - Todo categories/tags
   - Priority levels
   - Subtasks

2. **Better Persistence**:
   - Database storage (SQLite, PostgreSQL)
   - Multiple user support
   - Backup and restore

3. **Advanced MCP Features**:
   - Prompts for guided interactions
   - Sampling for AI integration
   - Notifications for real-time updates

4. **Integration Examples**:
   - Web interface using the MCP server
   - CLI tool built on the MCP client
   - AI assistant integration

## Troubleshooting

**Server won't start**: 
- Ensure MCP library is installed: `pip install mcp`
- Check Python version compatibility
- Verify file permissions for data storage

**Client connection fails**:
- Make sure server is running before starting client
- Check for port conflicts or communication issues
- Verify MCP library versions match

**Data persistence issues**:
- Check write permissions in current directory
- Verify `todos.json` file isn't corrupted
- Delete `todos.json` to reset data if needed

## References

- [Model Context Protocol Documentation](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Specification](https://spec.modelcontextprotocol.io/)

This example serves as a foundation for understanding MCP servers and can be adapted for various use cases beyond todo management.