import logging
import os
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from ollama import AsyncClient

logger = logging.getLogger("jarvis.llm")

class LLMService:
    def __init__(self, config):
        self.config = config
        provider = config['llm'].get('provider', 'local')
        self.provider = provider
        self.ollama_client = None
        self.ollama_model = None

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
            
            # Use native ollama-python client for full thinking/tool streaming
            self.ollama_client = AsyncClient(
                host=config['llm']['ollama_cloud']['base_url'],
                headers={'Authorization': f'Bearer {api_key}'}
            )
            self.ollama_model = config['llm']['ollama_cloud']['model']
            # Keep a small langchain model placeholder in case something imports get_llm()
            self.llm = ChatOllama(
                base_url=config['llm']['ollama_cloud']['base_url'],
                model=self.ollama_model,
                temperature=0.7,
                streaming=True,
                client_kwargs={'headers': {'Authorization': f'Bearer {api_key}'}},
                extra_body={"think": True}
            )
            logger.info(f"LLM Service initialized using Ollama Cloud model (native client enabled): {config['llm']['ollama_cloud']['model']}")
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

    def get_provider(self):
        return self.provider

    def is_ollama_native(self):
        return self.provider == 'ollama-cloud' and self.ollama_client is not None

    def get_ollama_client(self):
        return self.ollama_client

    def get_ollama_model(self):
        return self.ollama_model
