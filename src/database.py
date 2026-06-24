import sqlite3

DB_FILE = "cloned_messages.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cloned_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_chat_id INTEGER,
            dest_chat_id INTEGER,
            source_msg_id INTEGER,
            dest_msg_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_chat_id, dest_chat_id, source_msg_id)
        )
    """)
    conn.commit()
    conn.close()

def is_already_cloned(source_chat_id, dest_chat_id, source_msg_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT dest_msg_id FROM cloned_messages
        WHERE source_chat_id = ? AND dest_chat_id = ? AND source_msg_id = ?
    """, (int(source_chat_id), int(dest_chat_id), int(source_msg_id)))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def register_clone(source_chat_id, dest_chat_id, source_msg_id, dest_msg_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO cloned_messages 
            (source_chat_id, dest_chat_id, source_msg_id, dest_msg_id)
            VALUES (?, ?, ?, ?)
        """, (int(source_chat_id), int(dest_chat_id), int(source_msg_id), int(dest_msg_id)))
        conn.commit()
    except Exception:
        pass
    conn.close()
