import sqlite3
import os

DB_PATH = "service/feedback.db"

def setup_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id TEXT NOT NULL,
            message TEXT NOT NULL,
            predicted_category TEXT NOT NULL,
            true_category TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_feedback(log_id: str, message: str, predicted_category: str, true_category: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO feedback (log_id, message, predicted_category, true_category)
        VALUES (?, ?, ?, ?)
    """, (log_id, message, predicted_category, true_category))
    conn.commit()
    conn.close()
