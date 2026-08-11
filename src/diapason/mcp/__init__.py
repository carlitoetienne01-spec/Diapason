"""MCP (Model Context Protocol) layer for Diapason."""

from diapason.mcp.client import MCPClient
from diapason.mcp.protocol import MCPError, MCPNotification, MCPRequest, MCPResponse
from diapason.mcp.server import MCPServer
from diapason.mcp.transport import (
    InProcessTransport,
    MCPTransport,
    SSETransport,
    StdioTransport,
    StreamableHTTPTransport,
)

__all__ = [
    "MCPClient",
    "MCPError",
    "MCPNotification",
    "MCPRequest",
    "MCPResponse",
    "MCPServer",
    "MCPTransport",
    "InProcessTransport",
    "SSETransport",
    "StdioTransport",
    "StreamableHTTPTransport",
]
