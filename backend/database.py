import sqlite3
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional

class DatabaseService:
    def __init__(self, db_path="jarvis.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Create sessions table
        c.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create messages table
        c.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                type TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        ''')
        
        # Create memory table
        c.execute('''
            CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()

    def create_session(self, title: str = "New Conversation") -> str:
        session_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO sessions (id, title) VALUES (?, ?)", (session_id, title))
        conn.commit()
        conn.close()
        return session_id

    def get_sessions(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_session_messages(self, session_id: str) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC", (session_id,))
        rows = c.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def add_message(self, session_id: str, role: str, content: str, msg_type: str = "text"):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "INSERT INTO messages (session_id, role, content, type) VALUES (?, ?, ?, ?)",
            (session_id, role, content, msg_type)
        )
        # Update session timestamp
        c.execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()

    def update_session_title(self, session_id: str, title: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
        conn.commit()
        conn.close()

    def delete_session(self, session_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()

    def add_memory(self, key: str, value: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO memory (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (key, value)
        )
        conn.commit()
        conn.close()

    def get_memory(self, key: str) -> Optional[str]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT value FROM memory WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None
    
    def get_all_memories(self) -> Dict[str, str]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT key, value FROM memory")
        rows = c.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}

    def delete_session(self, session_id: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()
