import logging
from langchain_openai import ChatOpenAI

logger = logging.getLogger("jarvis.llm")

class LLMService:
    def __init__(self, config):
        self.config = config
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
