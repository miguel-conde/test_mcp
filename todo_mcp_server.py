#!/usr/bin/env python3
"""
Todo Manager MCP Server

A simple Model Context Protocol (MCP) server that provides todo management capabilities.
This serves as a educational example demonstrating:
- FastMCP server setup and structure
- Tool definition and implementation
- Resource management
- Error handling
- State persistence

Usage:
    python todo_mcp_server.py

Tools provided:
- add_todo: Add a new todo item
- list_todos: List all todo items
- toggle_todo: Mark a todo as complete/incomplete
- delete_todo: Delete a todo item
- get_todo: Get details of a specific todo
- clear_completed: Remove all completed todos

Resources provided:
- todos://all: All todo items
- todos://pending: Only pending todos
- todos://completed: Only completed todos
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

from mcp.server.fastmcp import FastMCP


# Data model for todo items
@dataclass
class TodoItem:
    """Represents a single todo item."""
    id: int
    title: str
    description: str = ""
    completed: bool = False
    created_at: str = ""
    completed_at: Optional[str] = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def toggle(self):
        """Toggle the completion status of this todo."""
        self.completed = not self.completed
        if self.completed:
            self.completed_at = datetime.now().isoformat()
        else:
            self.completed_at = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TodoItem":
        """Create TodoItem from dictionary."""
        return cls(**data)


class TodoManager:
    """Manages todo items with file-based persistence."""
    
    def __init__(self, data_file: str = "todos.json"):
        self.data_file = data_file
        self.todos: List[TodoItem] = []
        self._next_id = 1
        self.load_todos()
    
    def load_todos(self):
        """Load todos from file."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.todos = [TodoItem.from_dict(todo_data) for todo_data in data.get('todos', [])]
                    self._next_id = data.get('next_id', 1)
            except (json.JSONDecodeError, KeyError, FileNotFoundError):
                self.todos = []
                self._next_id = 1
    
    def save_todos(self):
        """Save todos to file."""
        data = {
            'todos': [todo.to_dict() for todo in self.todos],
            'next_id': self._next_id
        }
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def add_todo(self, title: str, description: str = "") -> TodoItem:
        """Add a new todo item."""
        todo = TodoItem(
            id=self._next_id,
            title=title,
            description=description
        )
        self.todos.append(todo)
        self._next_id += 1
        self.save_todos()
        return todo
    
    def get_todo(self, todo_id: int) -> Optional[TodoItem]:
        """Get a specific todo by ID."""
        for todo in self.todos:
            if todo.id == todo_id:
                return todo
        return None
    
    def get_all_todos(self) -> List[TodoItem]:
        """Get all todos."""
        return self.todos.copy()
    
    def get_pending_todos(self) -> List[TodoItem]:
        """Get only pending (incomplete) todos."""
        return [todo for todo in self.todos if not todo.completed]
    
    def get_completed_todos(self) -> List[TodoItem]:
        """Get only completed todos."""
        return [todo for todo in self.todos if todo.completed]
    
    def toggle_todo(self, todo_id: int) -> Optional[TodoItem]:
        """Toggle completion status of a todo."""
        todo = self.get_todo(todo_id)
        if todo:
            todo.toggle()
            self.save_todos()
        return todo
    
    def delete_todo(self, todo_id: int) -> bool:
        """Delete a todo item."""
        for i, todo in enumerate(self.todos):
            if todo.id == todo_id:
                del self.todos[i]
                self.save_todos()
                return True
        return False
    
    def clear_completed(self) -> int:
        """Remove all completed todos and return count of removed items."""
        initial_count = len(self.todos)
        self.todos = [todo for todo in self.todos if not todo.completed]
        removed_count = initial_count - len(self.todos)
        if removed_count > 0:
            self.save_todos()
        return removed_count
    
    def get_stats(self) -> Dict[str, int]:
        """Get todo statistics."""
        total = len(self.todos)
        completed = len(self.get_completed_todos())
        pending = len(self.get_pending_todos())
        return {
            'total': total,
            'completed': completed,
            'pending': pending
        }


# Initialize FastMCP server and todo manager
mcp = FastMCP("todo-manager")
todo_manager = TodoManager()


@mcp.tool()
def add_todo(title: str, description: str = "") -> str:
    """Add a new todo item."""
    todo = todo_manager.add_todo(title, description)
    return f"✅ Todo added successfully!\n\nID: {todo.id}\nTitle: {todo.title}\nDescription: {todo.description}\nCreated: {todo.created_at}"


@mcp.tool()
def list_todos(filter_type: str = "all", include_stats: bool = False) -> str:
    """List todo items with optional filtering and statistics."""
    if filter_type == "pending":
        todos = todo_manager.get_pending_todos()
    elif filter_type == "completed":
        todos = todo_manager.get_completed_todos()
    else:
        todos = todo_manager.get_all_todos()
    
    if not todos:
        status_msg = {
            "all": "No todos found.",
            "pending": "No pending todos.",
            "completed": "No completed todos."
        }.get(filter_type, "No todos found.")
        
        result = f"📝 {status_msg}"
    else:
        result = f"📝 {filter_type.title()} Todos ({len(todos)} items):\n\n"
        
        for todo in todos:
            status = "✅" if todo.completed else "⏳"
            result += f"{status} [{todo.id}] {todo.title}\n"
            if todo.description:
                result += f"    📄 {todo.description}\n"
            if todo.completed and todo.completed_at:
                result += f"    🏁 Completed: {todo.completed_at}\n"
            result += "\n"
    
    if include_stats:
        stats = todo_manager.get_stats()
        result += f"\n📊 Statistics:\n"
        result += f"   Total: {stats['total']}\n"
        result += f"   Completed: {stats['completed']}\n"
        result += f"   Pending: {stats['pending']}"
    
    return result


@mcp.tool()
def get_todo(todo_id: int) -> str:
    """Get details of a specific todo item."""
    todo = todo_manager.get_todo(todo_id)
    
    if not todo:
        return f"❌ Todo with ID {todo_id} not found."
    
    status = "✅ Completed" if todo.completed else "⏳ Pending"
    result = f"📝 Todo Details:\n\n"
    result += f"ID: {todo.id}\n"
    result += f"Title: {todo.title}\n"
    result += f"Description: {todo.description}\n"
    result += f"Status: {status}\n"
    result += f"Created: {todo.created_at}\n"
    if todo.completed_at:
        result += f"Completed: {todo.completed_at}\n"
    
    return result


@mcp.tool()
def toggle_todo(todo_id: int) -> str:
    """Mark a todo as complete or incomplete."""
    todo = todo_manager.toggle_todo(todo_id)
    
    if not todo:
        return f"❌ Todo with ID {todo_id} not found."
    
    status = "completed" if todo.completed else "pending"
    emoji = "✅" if todo.completed else "⏳"
    
    return f"{emoji} Todo '{todo.title}' marked as {status}!"


@mcp.tool()
def delete_todo(todo_id: int) -> str:
    """Delete a todo item."""
    success = todo_manager.delete_todo(todo_id)
    
    if not success:
        return f"❌ Todo with ID {todo_id} not found."
    
    return f"🗑️ Todo with ID {todo_id} deleted successfully!"


@mcp.tool()
def clear_completed() -> str:
    """Remove all completed todo items."""
    removed_count = todo_manager.clear_completed()
    
    if removed_count == 0:
        return "🧹 No completed todos to clear."
    
    return f"🧹 Cleared {removed_count} completed todo(s)!"


@mcp.resource("todos://all")
def get_all_todos_resource() -> str:
    """Get all todos as JSON resource."""
    todos = todo_manager.get_all_todos()
    todos_data = {
        "todos": [todo.to_dict() for todo in todos],
        "count": len(todos),
        "stats": todo_manager.get_stats()
    }
    return json.dumps(todos_data, indent=2)


@mcp.resource("todos://pending")
def get_pending_todos_resource() -> str:
    """Get pending todos as JSON resource."""
    todos = todo_manager.get_pending_todos()
    todos_data = {
        "todos": [todo.to_dict() for todo in todos],
        "count": len(todos),
        "stats": todo_manager.get_stats()
    }
    return json.dumps(todos_data, indent=2)


@mcp.resource("todos://completed")
def get_completed_todos_resource() -> str:
    """Get completed todos as JSON resource."""
    todos = todo_manager.get_completed_todos()
    todos_data = {
        "todos": [todo.to_dict() for todo in todos],
        "count": len(todos),
        "stats": todo_manager.get_stats()
    }
    return json.dumps(todos_data, indent=2)


if __name__ == "__main__":
    mcp.run()