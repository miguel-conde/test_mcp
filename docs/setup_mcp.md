# Setup: Run the RLM Corpus MCP Server in VS Code

This guide explains how to run the RLM corpus MCP server in VS Code using the AI Toolkit / Copilot integration.

Prerequisites
- Python 3.10+ installed
- Clone of this repository

1) Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2) Install dependencies

```bash
pip install -r requirements.txt
```

3) Sample MCP config
- Copy the example config to your user config location and update absolute paths:

```bash
mkdir -p ~/.config/Code/User
cp .vscode/mcp.json.example ~/.config/Code/User/mcp.json
# Edit ~/.config/Code/User/mcp.json and replace /absolute/path/to with your workspace path
```

On Windows, copy to `%APPDATA%/Code/User/mcp.json` instead.

4) Environment variables
- `OPENAI_API_KEY` is required only if you enable the experimental `llm_query` (Step 10). Add it to your environment or the `env` block in the `mcp.json` example.

5) Start and verify
- Restart VS Code after adding the config.
- Open Copilot Chat and type `@rlm-corpus-server` — the server should be discoverable.
- Quick smoke flow (in Copilot Chat): attach a small text file, ask Copilot to `load_corpus` the file, then `search_corpus` for a keyword, and finally ask to analyze matches (which will call `open_session` + `exec_repl`).

Notes
- Use absolute paths in `mcp.json` to avoid issues with relative resolution.
- The example `mcp.json` included in this repo is a template — edit it before use.
