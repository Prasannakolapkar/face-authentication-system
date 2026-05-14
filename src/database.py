import sqlite3
import os
import json
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional, Any

class DatabaseManager:
    """
    Handles persistence for the Fraud Detection System using SQLite.
    Stores user enrollment data (including face embeddings) and transaction logs.
    """

    def __init__(self, db_path: str = "data/fraud_detection.db"):
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self.db_path = db_path
        self.initialize()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def initialize(self):
        """Create tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table: Store enrollment data, embeddings, and credentials
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    card_number TEXT NOT NULL,
                    face_embedding BLOB,
                    password_hash TEXT,
                    role TEXT DEFAULT 'CARDHOLDER',
                    email TEXT,
                    enrolled_at TEXT NOT NULL
                )
            ''')
            
            # Migration: add email column if missing (existing databases)
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Transactions table: Store full history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    tx_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    decision TEXT NOT NULL,
                    risk_score REAL,
                    face_similarity REAL,
                    latency_ms INTEGER,
                    timestamp TEXT NOT NULL,
                    metadata TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            conn.commit()

    # --- User Operations ---

    def upsert_user(self, user_id: str, card_number: str, embedding: Optional[np.ndarray] = None, 
                    password_hash: Optional[str] = None, role: str = "CARDHOLDER", email: Optional[str] = None):
        """Add or update a cardholder."""
        embedding_blob = embedding.tobytes() if embedding is not None else None
        now = datetime.now().isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (user_id, card_number, face_embedding, password_hash, role, email, enrolled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    card_number = excluded.card_number,
                    face_embedding = COALESCE(excluded.face_embedding, users.face_embedding),
                    password_hash = COALESCE(excluded.password_hash, users.password_hash),
                    role = COALESCE(excluded.role, users.role),
                    email = COALESCE(excluded.email, users.email)
            ''', (user_id, card_number, embedding_blob, password_hash, role, email, now))
            conn.commit()

    def get_user(self, user_id: str) -> Optional[Dict]:
        """Retrieve user data."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            
            if row:
                res = dict(row)
                if res['face_embedding']:
                    res['face_embedding'] = np.frombuffer(res['face_embedding'], dtype=np.float32)
                return res
            return None

    def list_users(self) -> List[str]:
        """Return list of all enrolled user IDs."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users')
            return [row[0] for row in cursor.fetchall()]

    def list_users_detail(self) -> List[Dict]:
        """Return detailed list of all enrolled users (without face embeddings)."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, email, card_number, role, enrolled_at FROM users')
            users = []
            for row in cursor.fetchall():
                user = dict(row)
                # Mask card number: show only last 4 digits
                card = user.get("card_number", "")
                if len(card) > 4:
                    user["card_number"] = "•" * (len(card) - 4) + card[-4:]
                users.append(user)
            return users

    # --- Transaction Operations ---

    def log_transaction(self, tx_data: Dict[str, Any]):
        """Append a transaction to the log."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transactions (
                    tx_id, user_id, amount, decision, risk_score, 
                    face_similarity, latency_ms, timestamp, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tx_data['tx_id'],
                tx_data['user_id'],
                tx_data['amount'],
                tx_data['decision'],
                tx_data.get('fraud_score'),
                tx_data.get('face_score'),
                tx_data.get('latency_ms'),
                tx_data.get('timestamp', datetime.now().isoformat()),
                json.dumps(tx_data.get('metadata', {}))
            ))
            conn.commit()

    def get_history(self, limit: int = 100) -> List[Dict]:
        """Retrieve latest transactions."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM transactions ORDER BY timestamp DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict:
        """Calculate pipeline statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM transactions')
            total = cursor.fetchone()[0]
            
            if total == 0:
                return {"total_transactions": 0, "approved": 0, "blocked": 0, "held_for_review": 0, "avg_latency_ms": 0}
            
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE decision = 'APPROVED'")
            approved = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE decision LIKE 'BLOCKED%'")
            blocked = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE decision = 'HELD_FOR_REVIEW'")
            held = cursor.fetchone()[0]
            
            cursor.execute("SELECT AVG(latency_ms) FROM transactions")
            avg_latency = cursor.fetchone()[0]
            
            return {
                "total_transactions": total,
                "approved": approved,
                "blocked": blocked,
                "held_for_review": held,
                "avg_latency_ms": int(avg_latency) if avg_latency else 0
            }

if __name__ == "__main__":
    # Test initialization
    db = DatabaseManager(":memory:")
    print("Database initialized successfully.")
    db.upsert_user("test_user", "1234")
    print(f"Users: {db.list_users()}")
