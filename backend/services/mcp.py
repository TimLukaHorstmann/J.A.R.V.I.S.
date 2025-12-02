import logging
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from contextlib import AsyncExitStack

logger = logging.getLogger("jarvis.mcp")

class MCPService:
    def __init__(self, config):
        self.config = config
        self.tools = []
        self.client = None
        self.exit_stack = AsyncExitStack()

    async def initialize(self):
        """Connects to MCP servers and loads tools."""
        # Define server connections from config
        server_map = self.config.get("mcp", {}).get("servers", {})
        
        if not server_map:
            logger.warning("No MCP servers configured.")
            return

        try:
            self.client = MultiServerMCPClient(server_map)
            # Updated for langchain-mcp-adapters 0.1.0+
            self.tools = await self.client.get_tools()
            logger.info(f"Loaded {len(self.tools)} tools from MCP servers.")
        except Exception as e:
            logger.error(f"Failed to initialize MCP client: {e}")

    async def cleanup(self):
        # MultiServerMCPClient 0.1.0+ manages its own lifecycle or doesn't support context manager
        # We'll assume no explicit cleanup is needed for the client object itself 
        # if we just used get_tools(), or we can check for a close method.
        if self.client and hasattr(self.client, 'aclose'):
             await self.client.aclose()
        elif self.client and hasattr(self.client, 'close'):
             await self.client.close()

    def get_tools(self):
        return self.tools
