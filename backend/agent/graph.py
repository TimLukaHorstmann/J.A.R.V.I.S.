import logging
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

logger = logging.getLogger("jarvis.agent")

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], "The conversation history"]

class JarvisAgent:
    def __init__(self, llm_service, mcp_service):
        self.llm = llm_service.get_llm()
        self.tools = []
        
        # Load tools from MCP servers
        # We'll implement mcp_service.get_tools() to return the list of tools
        self.tools = mcp_service.get_tools()
        
        # Bind tools to LLM
        self.model = self.llm.bind_tools(self.tools)
        
        # Define the graph
        workflow = StateGraph(AgentState)
        
        # Define nodes
        workflow.add_node("agent", self.call_model)
        workflow.add_node("tools", ToolNode(self.tools))
        
        # Define edges
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges(
            "agent",
            self.should_continue,
            {
                "continue": "tools",
                "end": END
            }
        )
        workflow.add_edge("tools", "agent")
        
        self.app = workflow.compile()
        
        self.system_prompt = """You are JARVIS, a highly advanced and helpful AI assistant.
        You have access to various tools to help the user.
        Always be concise, polite, and efficient.
        If you use a tool, interpret the results for the user naturally.
        """

    def should_continue(self, state: AgentState):
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "continue"
        return "end"

    async def call_model(self, state: AgentState):
        messages = state["messages"]
        # Prepend system prompt if it's the first turn or not present
        # (Simplified for now, usually we manage history better)
        if not isinstance(messages[0], HumanMessage) and not isinstance(messages[0], AIMessage):
             # Assuming system prompt is handled via history or we just prepend it here
             pass
             
        # We can construct a prompt template here
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            MessagesPlaceholder(variable_name="messages"),
        ])
        
        chain = prompt | self.model
        response = await chain.ainvoke({"messages": messages})
        
        # Custom parsing for Qwen/Local models that output XML tool calls
        if "<tool_call>" in str(response.content):
            response = self.parse_tool_calls_from_content(response)
            
        return {"messages": [response]}

    def parse_tool_calls_from_content(self, message: AIMessage):
        import re
        import json
        import uuid
        
        content = message.content
        # Regex to find <tool_call>...</tool_call>
        pattern = r'<tool_call>\s*({.*?})\s*</tool_call>'
        matches = re.findall(pattern, content, re.DOTALL)
        
        if matches:
            tool_calls = []
            for json_str in matches:
                try:
                    data = json.loads(json_str)
                    tool_calls.append({
                        "name": data["name"],
                        "args": data["arguments"],
                        "id": str(uuid.uuid4())
                    })
                except Exception as e:
                    logger.error(f"Error parsing tool call JSON: {e}")
            
            if tool_calls:
                message.tool_calls = tool_calls
        
        return message

    async def process_message(self, message: str, history: list = None):
        if history is None:
            history = []
        
        # Convert string history to Messages
        formatted_history = []
        for i, msg in enumerate(history):
            if isinstance(msg, str):
                if i % 2 == 0:
                    formatted_history.append(HumanMessage(content=msg))
                else:
                    formatted_history.append(AIMessage(content=msg))
            else:
                formatted_history.append(msg)
        
        inputs = {"messages": formatted_history + [HumanMessage(content=message)]}
        
        async for event in self.app.astream(inputs):
            for key, value in event.items():
                # We can log steps here
                pass
                
        # Return the final state's last message
        # Note: astream yields updates. We might want to use invoke for simplicity 
        # or handle streaming properly. For now, let's just get the final result.
        final_state = await self.app.ainvoke(inputs)
        return final_state["messages"][-1].content
