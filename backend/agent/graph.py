import logging
import json
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from agent.prompts import SYSTEM_PROMPT

logger = logging.getLogger("jarvis.agent")

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

class JarvisAgent:
    def __init__(self, llm_service, mcp_service, local_tools=None):
        self.llm = llm_service.get_llm()
        self.tools = []
        
        # Load tools from MCP servers
        mcp_tools = mcp_service.get_tools()
        self.tools.extend(mcp_tools)
        
        # Add local tools
        if local_tools:
            self.tools.extend(local_tools)
        
        # Bind tools to LLM
        if self.tools:
            self.model = self.llm.bind_tools(self.tools)
        else:
            self.model = self.llm

        
        # Define the graph
        workflow = StateGraph(AgentState)
        
        # Define nodes
        workflow.add_node("agent", self.call_model)
        workflow.add_node("tools", self.run_tools)
        
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
        
        self.system_prompt = SYSTEM_PROMPT

    async def run_tools(self, state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        tool_calls = last_message.tool_calls
        
        results = []
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_id = tc["id"]
            
            # Find tool
            tool = next((t for t in self.tools if t.name == tool_name), None)
            
            if tool:
                try:
                    # Execute
                    # We prefer ainvoke if available
                    if hasattr(tool, "ainvoke"):
                        output = await tool.ainvoke(tool_args)
                    else:
                        output = tool.invoke(tool_args)
                except Exception as e:
                    output = f"Error: {str(e)}"
            else:
                output = f"Error: Tool {tool_name} not found."
            
            results.append(ToolMessage(content=str(output), tool_call_id=tool_id, name=tool_name))
            
        return {"messages": results}

    def should_continue(self, state: AgentState):
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "continue"
        return "end"

    async def call_model(self, state: AgentState, config: RunnableConfig):
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
        response = await chain.ainvoke({"messages": messages}, config=config)
        
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
        
        state = "NORMAL" # NORMAL, THINKING, TOOL_DEF
        buffer = ""
        streamed_response = False
        
        logger.info("Starting process_message stream...")
        
        try:
            async for event in self.app.astream_events(inputs, version="v1"):
                kind = event["event"]
                # logger.info(f"Event: {kind}") # Debug log
                
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"].content
                    if not chunk: continue
                    
                    streamed_response = True
                    buffer += chunk
                    
                    while True:
                        if state == "NORMAL":
                            if "<think>" in buffer:
                                pre, rest = buffer.split("<think>", 1)
                                if pre: yield {"type": "response", "chunk": pre}
                                state = "THINKING"
                                buffer = rest
                                continue
                            if "<tool_call>" in buffer:
                                pre, rest = buffer.split("<tool_call>", 1)
                                if pre: yield {"type": "response", "chunk": pre}
                                state = "TOOL_DEF"
                                buffer = rest
                                continue
                            
                            if "<" in buffer:
                                idx = buffer.find("<")
                                if idx > 0:
                                    yield {"type": "response", "chunk": buffer[:idx]}
                                    buffer = buffer[idx:]
                                break
                            else:
                                yield {"type": "response", "chunk": buffer}
                                buffer = ""
                                break
                                
                        elif state == "THINKING":
                            if "</think>" in buffer:
                                thought, rest = buffer.split("</think>", 1)
                                if thought.strip():
                                    yield {"type": "thought", "chunk": thought}
                                state = "NORMAL"
                                buffer = rest
                                continue
                            
                            if "</" in buffer:
                                 idx = buffer.find("</")
                                 if idx > 0:
                                     if buffer[:idx].strip():
                                         yield {"type": "thought", "chunk": buffer[:idx]}
                                     buffer = buffer[idx:]
                                 break
                            elif buffer.endswith("<"):
                                 if buffer[:-1].strip():
                                     yield {"type": "thought", "chunk": buffer[:-1]}
                                 buffer = "<"
                                 break
                            else:
                                 if buffer.strip():
                                     yield {"type": "thought", "chunk": buffer}
                                 buffer = ""
                                 break

                        elif state == "TOOL_DEF":
                            if "</tool_call>" in buffer:
                                tool_json, rest = buffer.split("</tool_call>", 1)
                                try:
                                    # Parse the JSON to get tool name and args
                                    tool_data = json.loads(tool_json)
                                    yield {
                                        "type": "tool_call",
                                        "tool": tool_data.get("name"),
                                        "args": tool_data.get("arguments")
                                    }
                                except Exception as e:
                                    logger.error(f"Failed to parse tool call from stream: {e}")
                                
                                state = "NORMAL"
                                buffer = rest
                                continue
                            break

                elif kind == "on_tool_end":
                    tool_name = event["name"]
                    output = event["data"].get("output")
                    if output:
                        yield {"type": "tool_result", "tool": tool_name, "content": str(output)}
                
                elif kind == "on_chain_end":
                    # Fallback for tool results if on_tool_end is not emitted (e.g. inside a node)
                    if event["name"] == "tools":
                        output = event["data"].get("output")
                        if output and "messages" in output:
                            for msg in output["messages"]:
                                if isinstance(msg, ToolMessage):
                                    yield {
                                        "type": "tool_result", 
                                        "tool": msg.name, 
                                        "content": str(msg.content)
                                    }

                elif kind == "on_chat_model_end":
                    msg = event["data"]["output"]
                    if msg:
                        # Handle tool calls
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                yield {"type": "tool_call", "tool": tc["name"], "args": tc["args"]}
                        
                        # Fallback: If we didn't stream anything, yield the content now
                        if not streamed_response and msg.content:
                            logger.info("Fallback: Yielding full content from on_chat_model_end")
                            buffer += msg.content

        except Exception as e:
            logger.error(f"Error in process_message stream: {e}")
        
        # Flush remaining buffer after the event loop finishes
        if buffer:
            logger.info(f"Flushing buffer: {buffer[:50]}...")
            if state == "NORMAL":
                yield {"type": "response", "chunk": buffer}
            elif state == "THINKING":
                if buffer.strip():
                    yield {"type": "thought", "chunk": buffer}
