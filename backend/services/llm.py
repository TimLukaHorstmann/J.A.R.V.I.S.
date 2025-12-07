import logging
import os
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

logger = logging.getLogger("jarvis.llm")

class LLMService:
    def __init__(self, config):
        self.config = config
        provider = config['llm'].get('provider', 'local')

        if provider == 'gemini':
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.error("GEMINI_API_KEY not found in environment variables")
                raise ValueError("GEMINI_API_KEY not found")
            
            self.llm = ChatGoogleGenerativeAI(
                model=config['llm']['gemini']['model'],
                google_api_key=api_key,
                temperature=0.7
            )
            logger.info(f"LLM Service initialized using Gemini model: {config['llm']['gemini']['model']}")
        elif provider == 'ollama-cloud':
            api_key = os.getenv("OLLAMA_CLOUD_API_KEY")
            if not api_key:
                logger.error("OLLAMA_CLOUD_API_KEY not found in environment variables")
                raise ValueError("OLLAMA_CLOUD_API_KEY not found")
            
            self.llm = ChatOllama(
                base_url=config['llm']['ollama_cloud']['base_url'],
                model=config['llm']['ollama_cloud']['model'],
                temperature=0.7,
                client_kwargs={'headers': {'Authorization': f'Bearer {api_key}'}}
            )
            logger.info(f"LLM Service initialized using Ollama Cloud model: {config['llm']['ollama_cloud']['model']}")
        else:
            # Connect to local llama-cpp-python server
            self.llm = ChatOpenAI(
                base_url=config['llm']['base_url'],
                api_key="EMPTY",
                model=config['llm']['model_alias'],
                temperature=0.7,
                streaming=True
            )
            logger.info(f"LLM Service initialized pointing to {config['llm']['base_url']}")

    def get_llm(self):
        return self.llm
