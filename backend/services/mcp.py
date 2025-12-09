import logging
import os
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
        server_map = self.config.get("mcp", {}).get("servers", {}).copy()
        
        # Add Home Assistant MCP if enabled
        ha_config = self.config.get("home_assistant", {})
        # Check env vars first, then config
        ha_url = os.getenv("HASS_URL") or ha_config.get("url")
        ha_token = os.getenv("HASS_TOKEN") or ha_config.get("token")
        
        # Determine if enabled: check tools config AND presence of credentials
        # We use the 'tools' section to allow UI toggling
        tools_config = self.config.get("tools", {})

        # Filter servers based on tools config
        keys_to_remove = []
        for server_name in server_map:
            if server_name in tools_config and not tools_config[server_name]:
                keys_to_remove.append(server_name)
        
        for key in keys_to_remove:
            del server_map[key]
            logger.info(f"MCP server '{key}' disabled via tools config.")

        ha_enabled = tools_config.get("home_assistant", False) and (ha_url and ha_token)
        
        if ha_enabled:
            # Ensure URL ends with /api/mcp for the MCP endpoint
            # If the user provided the base URL (e.g. http://localhost:8123), append /api/mcp
            if not ha_url.endswith("/api/mcp"):
                # Strip trailing slash if present
                base_url = ha_url.rstrip("/")
                mcp_url = f"{base_url}/api/mcp"
            else:
                mcp_url = ha_url
                
            logger.info(f"Adding Home Assistant MCP server at {mcp_url}")
            # Use StreamableHttpConnection configuration for Home Assistant
            server_map["home_assistant"] = {
                "transport": "streamable_http",
                "url": mcp_url,
                "headers": {
                    "Authorization": f"Bearer {ha_token}",
                    "Content-Type": "application/json"
                }
            }
        
        if not server_map:
            logger.warning("No MCP servers configured.")
            return

        import asyncio
        
        # Retry logic for connection
        for attempt in range(5):
            try:
                self.client = MultiServerMCPClient(server_map)
                # Updated for langchain-mcp-adapters 0.1.0+
                self.tools = await self.client.get_tools()
                logger.info(f"Loaded {len(self.tools)} tools from MCP servers.")
                return
            except Exception as e:
                # Log detailed error for debugging
                import traceback
                logger.warning(f"Attempt {attempt+1}/5: Failed to initialize MCP client: {e}")
                logger.debug(traceback.format_exc())
                
                # Try to identify which server failed if possible (MultiServerMCPClient might not expose this easily)
                # But we can log the servers we are trying to connect to
                if attempt == 0:
                    logger.info(f"Configured MCP servers: {list(server_map.keys())}")

                if attempt < 4:
                    await asyncio.sleep(2) # Wait 2 seconds before retrying
        
        logger.error("Could not initialize MCP client after 5 attempts.")

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
