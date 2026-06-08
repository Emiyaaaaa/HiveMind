"""Minimal MCP server used by integration tests."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo-test")


@mcp.tool()
def ping(message: str = "ping") -> str:
    """Echo a message back."""
    return message


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


if __name__ == "__main__":
    mcp.run()
