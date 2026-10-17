# CURRENT MCP server

Your AI coding agent sees the same digital twin as the coach, so the code it writes matches the board on the bench.

`app/mcp_server.py` is a stdio MCP server that talks to the running CURRENT HTTP API (`CURRENT_URL`, default `http://localhost:18080`).
It uses the official `mcp` SDK when installed (`pip install mcp`), otherwise a built-in minimal JSON-RPC implementation (`CURRENT_MCP_MINIMAL=1` forces it).

## Tools
- `current_get_state(code)` project, step, board, parts seen, twin, findings, mistakes, sketch
- `current_get_twin(code)` observed twin only
- `current_get_sketch(code)` current .ino
- `current_update_sketch(code, instruction)` regenerate, e.g. "fade the LED"
- `current_list_projects()` saved projects (VAST S3)
- `current_resume_project(code, key)` load one into a live session

## Claude Code
    claude mcp add current -e CURRENT_URL=http://localhost:18080 -- python app/mcp_server.py

## Cursor (`.cursor/mcp.json`)
    {"mcpServers": {"current": {"command": "python", "args": ["app/mcp_server.py"],
                                "env": {"CURRENT_URL": "http://localhost:18080"}}}}

## Demo story
1. Wire an LED on the bench; the coach and the twin agree on the pins.
2. In Claude Code: "Read my CURRENT session ABC123 and make the LED fade." The agent calls `current_get_state`, sees the LED is on D5 with a resistor, calls `current_update_sketch`, and the sketch panel in the browser updates live.
3. Download the .ino or paste it into the IDE. Pins in the code match the wires on the bench.
