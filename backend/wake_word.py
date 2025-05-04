# JARVIS/backend/wake_word.py

def contains_wake_word(text: str) -> bool:
    return "hey jarvis" in text.lower()