#!/usr/bin/env python3
"""
Todo MCP Server Test Client

A simple test client to demonstrate interaction with the Todo Manager MCP Server.
This shows how to connect to and use an MCP server programmatically.

Usage:
    python test_todo_client.py
    python test_todo_client.py interactive
"""

import asyncio
import json
import sys
from typing import Any, Dict, List

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def run_todo_demo():
    """Run a complete demo of the todo MCP server capabilities."""
    print("🚀 Starting Todo Manager MCP Demo")
    print("=" * 50)
    
    # Configure server parameters for stdio communication
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["todo_mcp_server.py"]
    )
    
    try:
        # Connect to the server using stdio
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                
                # Initialize the session
                await session.initialize()
                
                print("✅ Connected to Todo Manager MCP Server")
                print()
                
                # List available tools
                print("📋 Available Tools:")
                tools = await session.list_tools()
                for tool in tools.tools:
                    print(f"  • {tool.name}: {tool.description}")
                print()
                
                # List available resources
                print("📚 Available Resources:")
                resources = await session.list_resources()
                for resource in resources.resources:
                    print(f"  • {resource.uri}: {resource.name}")
                print()
                
                # Demo: Add some todos
                print("📝 Adding sample todos...")
                
                # Add todo 1
                result = await session.call_tool("add_todo", {
                    "title": "Learn about MCP servers",
                    "description": "Understand how Model Context Protocol works"
                })
                print(result.content[0].text)
                print()
                
                # Add todo 2
                result = await session.call_tool("add_todo", {
                    "title": "Build a todo manager",
                    "description": "Create an MCP server for managing todos"
                })
                print(result.content[0].text)
                print()
                
                # Add todo 3
                result = await session.call_tool("add_todo", {
                    "title": "Test the server",
                    "description": ""
                })
                print(result.content[0].text)
                print()
                
                # List all todos
                print("📋 Listing all todos:")
                result = await session.call_tool("list_todos", {
                    "filter_type": "all",
                    "include_stats": True
                })
                print(result.content[0].text)
                print()
                
                # Complete a todo
                print("✅ Marking todo 2 as completed...")
                result = await session.call_tool("toggle_todo", {"todo_id": 2})
                print(result.content[0].text)
                print()
                
                # List pending todos
                print("⏳ Listing pending todos:")
                result = await session.call_tool("list_todos", {"filter_type": "pending"})
                print(result.content[0].text)
                print()
                
                # Get specific todo details
                print("🔍 Getting details for todo 1:")
                result = await session.call_tool("get_todo", {"todo_id": 1})
                print(result.content[0].text)
                print()
                
                # Read resource data
                print("📊 Reading todos resource (all):")
                resource_data = await session.read_resource("todos://all")
                todos_json = json.loads(resource_data.contents[0].text)
                print(f"Total todos from resource: {todos_json['count']}")
                print(f"Stats: {todos_json['stats']}")
                print()
                
                # Clear completed todos
                print("🧹 Clearing completed todos...")
                result = await session.call_tool("clear_completed", {})
                print(result.content[0].text)
                print()
                
                # Final list
                print("📋 Final todo list:")
                result = await session.call_tool("list_todos", {
                    "filter_type": "all",
                    "include_stats": True
                })
                print(result.content[0].text)
                print()
                
                print("🎉 Demo completed successfully!")
                
    except Exception as e:
        print(f"❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()


async def interactive_todo_client():
    """Run an interactive client for the todo MCP server."""
    print("🚀 Interactive Todo Manager Client")
    print("Type 'help' for available commands, 'quit' to exit")
    print("=" * 50)
    
    # Configure server parameters for stdio communication
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["todo_mcp_server.py"]
    )
    
    try:
        # Connect to the server using stdio
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                
                # Initialize the session
                await session.initialize()
                print("✅ Connected to Todo Manager MCP Server\n")
                
                while True:
                    try:
                        command = input("todo> ").strip()
                        
                        if command == "quit":
                            break
                        elif command == "help":
                            print("Available commands:")
                            print("  add <title> [description] - Add a new todo")
                            print("  list [all|pending|completed] - List todos")
                            print("  get <id> - Get todo details")
                            print("  toggle <id> - Toggle todo completion")
                            print("  delete <id> - Delete a todo")
                            print("  clear - Clear completed todos")
                            print("  tools - List available MCP tools")
                            print("  resources - List available MCP resources")
                            print("  help - Show this help")
                            print("  quit - Exit the client")
                            continue
                        elif command == "tools":
                            tools = await session.list_tools()
                            for tool in tools.tools:
                                print(f"  • {tool.name}: {tool.description}")
                            continue
                        elif command == "resources":
                            resources = await session.list_resources()
                            for resource in resources.resources:
                                print(f"  • {resource.uri}: {resource.name}")
                            continue
                        elif command.startswith("add "):
                            parts = command[4:].split(" ", 1)
                            title = parts[0]
                            description = parts[1] if len(parts) > 1 else ""
                            
                            result = await session.call_tool("add_todo", {
                                "title": title,
                                "description": description
                            })
                            print(result.content[0].text)
                            
                        elif command.startswith("list"):
                            parts = command.split()
                            filter_type = parts[1] if len(parts) > 1 else "all"
                            
                            result = await session.call_tool("list_todos", {
                                "filter_type": filter_type,
                                "include_stats": True
                            })
                            print(result.content[0].text)
                            
                        elif command.startswith("get "):
                            todo_id = int(command[4:])
                            
                            result = await session.call_tool("get_todo", {
                                "todo_id": todo_id
                            })
                            print(result.content[0].text)
                            
                        elif command.startswith("toggle "):
                            todo_id = int(command[7:])
                            
                            result = await session.call_tool("toggle_todo", {
                                "todo_id": todo_id
                            })
                            print(result.content[0].text)
                            
                        elif command.startswith("delete "):
                            todo_id = int(command[7:])
                            
                            result = await session.call_tool("delete_todo", {
                                "todo_id": todo_id
                            })
                            print(result.content[0].text)
                            
                        elif command == "clear":
                            result = await session.call_tool("clear_completed", {})
                            print(result.content[0].text)
                            
                        else:
                            print("Unknown command. Type 'help' for available commands.")
                    
                    except KeyboardInterrupt:
                        break
                    except Exception as e:
                        print(f"❌ Error: {e}")
                
    except Exception as e:
        print(f"❌ Connection error: {e}")
    
    print("👋 Goodbye!")


async def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "interactive":
        await interactive_todo_client()
    else:
        await run_todo_demo()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")