import logging
import json
import uuid
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from ollama import AsyncClient
from agent.prompts import SYSTEM_PROMPT
from datetime import datetime

logger = logging.getLogger("jarvis.agent")

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

class JarvisAgent:
    def __init__(self, llm_service, mcp_service, local_tools=None):
        self.llm = llm_service.get_llm()
        self.llm_service = llm_service
        self.provider = llm_service.get_provider() if hasattr(llm_service, "get_provider") else "local"
        self.tools = []
        
        # Load tools from MCP servers
        mcp_tools = mcp_service.get_tools()
        self.tools.extend(mcp_tools)
        
        # Add local tools
        if local_tools:
            self.tools.extend(local_tools)
        
        # Bind tools to LLM (only for langchain providers)
        if self.provider != 'ollama-cloud':
            if self.tools:
                self.model = self.llm.bind_tools(self.tools)
            else:
                self.model = self.llm
        else:
            self.model = None
            # Pre-build Ollama tool schema for native client
            self.ollama_tools_schema = self._build_ollama_tools_schema(self.tools)

        
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
        
        current_date = datetime.now().strftime("%B %d, %Y")
        current_time = datetime.now().strftime("%H:%M")

        self.system_prompt = SYSTEM_PROMPT + f"""
Today is {current_date}. The current time is {current_time}.
"""

    def _build_ollama_tools_schema(self, tools: list):
        schema = []
        for tool in tools:
            params = {"type": "object", "properties": {}}
            try:
                if hasattr(tool, "args_schema") and tool.args_schema:
                    if hasattr(tool.args_schema, "model_json_schema"):
                        params = tool.args_schema.model_json_schema()
                    elif hasattr(tool.args_schema, "schema"):
                        params = tool.args_schema.schema()
                    elif isinstance(tool.args_schema, dict):
                        params = tool.args_schema
            except Exception as e:
                logger.error(f"Failed to build schema for tool {getattr(tool, 'name', 'unknown')}: {e}")
            schema.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": getattr(tool, "description", ""),
                    "parameters": params
                }
            })
        return schema

    async def _invoke_tool_from_ollama_call(self, tc):
        if isinstance(tc, dict):
            fn = tc.get("function", {})
        else:
            fn = getattr(tc, "function", {})

        if isinstance(fn, dict):
            tool_name = fn.get("name")
            tool_args = fn.get("arguments") or {}
        else:
            tool_name = getattr(fn, "name", None)
            tool_args = getattr(fn, "arguments", {}) or {}

        tool_id = None
        if isinstance(tc, dict):
            tool_id = tc.get("id") or tc.get("tool_call_id")
        else:
            tool_id = getattr(tc, "id", None) or getattr(tc, "tool_call_id", None)
        
        if not tool_id:
            tool_id = str(uuid.uuid4())

        tool = next((t for t in self.tools if t.name == tool_name), None)
        if tool:
            try:
                if hasattr(tool, "ainvoke"):
                    output = await tool.ainvoke(tool_args)
                else:
                    output = tool.invoke(tool_args)
            except Exception as e:
                output = f"Error: {str(e)}"
        else:
            output = f"Error: Tool {tool_name} not found."

        return {
            "tool": tool_name,
            "content": str(output),
            "tool_call_id": tool_id
        }

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

        # Native Ollama streaming path (direct SDK) for cloud provider
        if hasattr(self.llm_service, "is_ollama_native") and self.llm_service.is_ollama_native():
            async for event in self.process_message_ollama(message, history):
                yield event
            return
        
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

        def drain_buffer():
            nonlocal buffer, state
            outputs = []
            while True:
                if state == "NORMAL":
                    if "<think>" in buffer:
                        pre, rest = buffer.split("<think>", 1)
                        if pre:
                            outputs.append({"type": "response", "chunk": pre})
                        state = "THINKING"
                        buffer = rest
                        continue
                    if "[THOUGHT]" in buffer:
                        pre, rest = buffer.split("[THOUGHT]", 1)
                        if pre:
                            outputs.append({"type": "response", "chunk": pre})
                        state = "THINKING"
                        buffer = rest
                        continue
                    if "<tool_call>" in buffer:
                        pre, rest = buffer.split("<tool_call>", 1)
                        if pre:
                            outputs.append({"type": "response", "chunk": pre})
                        state = "TOOL_DEF"
                        buffer = rest
                        continue

                    if "<" in buffer or "[" in buffer:
                        idx_lt = buffer.find("<")
                        idx_sq = buffer.find("[")

                        if idx_lt != -1 and (idx_sq == -1 or idx_lt < idx_sq):
                            idx = idx_lt
                        else:
                            idx = idx_sq

                        if idx > 0:
                            outputs.append({"type": "response", "chunk": buffer[:idx]})
                            buffer = buffer[idx:]
                        break
                    else:
                        if buffer:
                            outputs.append({"type": "response", "chunk": buffer})
                        buffer = ""
                        break

                elif state == "THINKING":
                    if "<tool_call>" in buffer:
                        pre, rest = buffer.split("<tool_call>", 1)
                        if pre.strip():
                            outputs.append({"type": "thought", "chunk": pre})
                        state = "TOOL_DEF"
                        buffer = rest
                        continue

                    if "</think>" in buffer:
                        thought, rest = buffer.split("</think>", 1)
                        if thought.strip():
                            outputs.append({"type": "thought", "chunk": thought})
                        state = "NORMAL"
                        buffer = rest
                        continue

                    if "[/THOUGHT]" in buffer:
                        thought, rest = buffer.split("[/THOUGHT]", 1)
                        if thought.strip():
                            outputs.append({"type": "thought", "chunk": thought})
                        state = "NORMAL"
                        buffer = rest
                        continue

                    if "</" in buffer or "[/" in buffer:
                        idx_lt = buffer.find("</")
                        idx_sq = buffer.find("[/")

                        if idx_lt != -1 and (idx_sq == -1 or idx_lt < idx_sq):
                            idx = idx_lt
                        else:
                            idx = idx_sq

                        if idx > 0:
                            if buffer[:idx].strip():
                                outputs.append({"type": "thought", "chunk": buffer[:idx]})
                            buffer = buffer[idx:]
                        break
                    elif buffer.endswith("<") or buffer.endswith("["):
                        if buffer[:-1].strip():
                            outputs.append({"type": "thought", "chunk": buffer[:-1]})
                        buffer = buffer[-1]
                        break
                    else:
                        if buffer.strip():
                            outputs.append({"type": "thought", "chunk": buffer})
                        buffer = ""
                        break

                elif state == "TOOL_DEF":
                    if "</tool_call>" in buffer:
                        tool_json, rest = buffer.split("</tool_call>", 1)
                        try:
                            tool_data = json.loads(tool_json)
                            outputs.append({
                                "type": "tool_call",
                                "tool": tool_data.get("name"),
                                "args": tool_data.get("arguments")
                            })
                        except Exception as e:
                            logger.error(f"Failed to parse tool call from stream: {e}")

                        state = "NORMAL"
                        buffer = rest
                        continue
                    break

                else:
                    break

            return outputs
        
        logger.info("Starting process_message stream...")
        
        try:
            async for event in self.app.astream_events(inputs, version="v1"):
                kind = event["event"]
                # logger.info(f"Event: {kind}") # Debug log
                
                if kind == "on_chat_model_stream":
                    chunk_msg = event["data"]["chunk"]
                    chunk = chunk_msg.content
                    
                    # Check for tool call chunks (native tool calling)
                    if hasattr(chunk_msg, 'tool_call_chunks') and chunk_msg.tool_call_chunks:
                         streamed_response = True
                    
                    if not chunk: continue
                    
                    streamed_response = True
                    buffer += chunk
                    
                    for output in drain_buffer():
                        yield output

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
                        # Extract provider-specific reasoning traces if present
                        reasoning = None
                        if isinstance(msg, dict):
                            reasoning = msg.get("reasoning") or msg.get("thinking") or msg.get("analysis")
                        else:
                            reasoning = getattr(msg, "reasoning", None) or getattr(msg, "thinking", None)
                            if not reasoning and hasattr(msg, "response_metadata"):
                                reasoning = msg.response_metadata.get("reasoning") or msg.response_metadata.get("thinking")
                            if not reasoning and hasattr(msg, "additional_kwargs"):
                                reasoning = msg.additional_kwargs.get("reasoning") or msg.additional_kwargs.get("thinking") or msg.additional_kwargs.get("analysis")

                        if reasoning:
                            buffer += f"<think>{reasoning}</think>"
                            for output in drain_buffer():
                                yield output

                        # Handle tool calls
                        if isinstance(msg, dict):
                            tool_calls = msg.get("tool_calls", [])
                            content = msg.get("content", "")
                        else:
                            tool_calls = getattr(msg, "tool_calls", [])
                            content = getattr(msg, "content", "")

                        if tool_calls:
                            for tc in tool_calls:
                                yield {"type": "tool_call", "tool": tc["name"], "args": tc["args"]}
                        
                        # Always parse any remaining content (covers non-streaming providers)
                        if content:
                            if not streamed_response:
                                logger.info("Parsing full content from on_chat_model_end")
                            buffer += content
                            for output in drain_buffer():
                                yield output

        except Exception as e:
            logger.error(f"Error in process_message stream: {e}")
        
        # Flush remaining buffer after the event loop finishes
        if buffer:
            logger.info(f"Flushing buffer: {buffer[:50]}...")
            for output in drain_buffer():
                yield output

    async def process_message_ollama(self, message: str, history: list = None):
        """Direct streaming with ollama-python for cloud provider to capture thinking/tool calls natively."""
        if history is None:
            history = []

        client = self.llm_service.get_ollama_client()
        model = self.llm_service.get_ollama_model()
        if not client or not model:
            logger.error("Ollama client or model missing; falling back to no-op")
            return

        # Build conversation with system prompt and prior turns
        messages = [{"role": "system", "content": self.system_prompt}]

        for i, msg in enumerate(history):
            if isinstance(msg, str):
                role = "user" if i % 2 == 0 else "assistant"
                messages.append({"role": role, "content": msg})
            elif isinstance(msg, HumanMessage):
                messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                messages.append({"role": "assistant", "content": msg.content})

        messages.append({"role": "user", "content": message})

        tools = getattr(self, "ollama_tools_schema", [])

        # Iterate until no more tool calls
        while True:
            stream = await client.chat(
                model=model,
                messages=messages,
                tools=tools if tools else None,
                stream=True,
                think="medium",  # request reasoning stream from gpt-oss
            )

            pending_tool_calls = None
            collected_content = ""

            async for chunk in stream:
                msg = chunk.get("message", {}) if isinstance(chunk, dict) else getattr(chunk, "message", {}) or {}

                thinking = None
                if isinstance(msg, dict):
                    thinking = msg.get("thinking")
                else:
                    thinking = getattr(msg, "thinking", None)

                if thinking:
                    yield {"type": "thought", "chunk": thinking}

                content = None
                if isinstance(msg, dict):
                    content = msg.get("content")
                else:
                    content = getattr(msg, "content", None)

                if content:
                    collected_content += content
                    yield {"type": "response", "chunk": content}

                tool_calls = None
                if isinstance(msg, dict):
                    tool_calls = msg.get("tool_calls")
                else:
                    tool_calls = getattr(msg, "tool_calls", None)
                
                tool_calls = tool_calls or []

                if tool_calls:
                    pending_tool_calls = tool_calls
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                        else:
                            fn = getattr(tc, "function", {})
                        
                        if isinstance(fn, dict):
                            name = fn.get("name")
                            args = fn.get("arguments")
                        else:
                            name = getattr(fn, "name", None)
                            args = getattr(fn, "arguments", None)

                        yield {
                            "type": "tool_call",
                            "tool": name,
                            "args": args
                        }

            # If no tools were requested, we're done
            if not pending_tool_calls:
                break

            # Execute tool calls and feed results back to the model for another round
            tool_results = []
            for tc in pending_tool_calls:
                res = await self._invoke_tool_from_ollama_call(tc)
                tool_results.append(res)
                yield {"type": "tool_result", "tool": res["tool"], "content": res["content"]}

            # Append assistant tool call message and tool outputs per Ollama spec
            # Ensure tool_calls are serializable (dicts)
            serializable_tool_calls = []
            if pending_tool_calls:
                for tc in pending_tool_calls:
                    if isinstance(tc, dict):
                        serializable_tool_calls.append(tc)
                    else:
                        # Try to convert to dict if it has .dict() or .model_dump()
                        if hasattr(tc, "model_dump"):
                            serializable_tool_calls.append(tc.model_dump())
                        elif hasattr(tc, "dict"):
                            serializable_tool_calls.append(tc.dict())
                        else:
                            # Manual conversion as fallback
                            fn = getattr(tc, "function", {})
                            fn_dict = {}
                            if isinstance(fn, dict):
                                fn_dict = fn
                            else:
                                fn_dict = {
                                    "name": getattr(fn, "name", None),
                                    "arguments": getattr(fn, "arguments", None)
                                }
                            
                            serializable_tool_calls.append({
                                "function": fn_dict,
                                "type": getattr(tc, "type", "function"),
                                "id": getattr(tc, "id", None) or getattr(tc, "tool_call_id", None)
                            })

            messages.append({
                "role": "assistant",
                "content": collected_content,
                "tool_calls": serializable_tool_calls
            })

            for res in tool_results:
                messages.append({
                    "role": "tool",
                    "content": res["content"],
                    "tool_call_id": res["tool_call_id"]
                })

        # Done
