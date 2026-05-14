"""
migrate_to_firebase.py
──────────────────────
One-time migration script: copies all existing SQLite data
(users + transactions) into Firebase Firestore.

Usage:
    # From the project root directory
    python migrate_to_firebase.py

Requirements:
    • .env file (or env vars) with FIREBASE_CREDENTIALS_PATH set
    • pip install firebase-admin python-dotenv

Safety:
    • Read-only for SQLite — existing data is never modified or deleted
    • Firestore documents are SET (upserted) — safe to re-run
    • Prints a clear summary when complete
"""

import sys
import os

# Load .env file if present (sets FIREBASE_CREDENTIALS_PATH etc.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Resolve src path ────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR      = os.path.join(PROJECT_ROOT, "src")
sys.path.insert(0, SRC_DIR)

# ── Imports ─────────────────────────────────────────────────────────────────
import sqlite3
import json
import base64
import numpy as np
from datetime import datetime
from firebase_config import get_firestore_client

# ── Constants ────────────────────────────────────────────────────────────────
SQLITE_PATH             = os.path.join(PROJECT_ROOT, "src", "data", "fraud_detection.db")
USERS_COLLECTION        = "users"
TRANSACTIONS_COLLECTION = "transactions"


def embed_to_b64(blob: bytes) -> str:
    """Convert raw numpy bytes blob to base64 string."""
    return base64.b64encode(blob).decode("utf-8")


def migrate_users(cursor, firestore_db):
    """Migrate all rows from SQLite users table to Firestore users collection."""
    cursor.execute("SELECT user_id, card_number, face_embedding, password_hash, role, email, enrolled_at FROM users")
    rows = cursor.fetchall()
    count = 0

    for row in rows:
        user_id, card_number, face_embedding_blob, password_hash, role, email, enrolled_at = row

        doc_data = {
            "user_id":          user_id,
            "card_number":      card_number,
            "face_embedding_b64": embed_to_b64(face_embedding_blob) if face_embedding_blob else None,
            "password_hash":    password_hash,
            "role":             role or "CARDHOLDER",
            "email":            email,
            "enrolled_at":      enrolled_at or datetime.now().isoformat(),
        }

        firestore_db.collection(USERS_COLLECTION).document(user_id).set(doc_data)
        print(f"  ✓ User migrated: {user_id}")
        count += 1

    return count


def migrate_transactions(cursor, firestore_db):
    """Migrate all rows from SQLite transactions table to Firestore transactions collection."""
    cursor.execute(
        "SELECT tx_id, user_id, amount, decision, risk_score, "
        "face_similarity, latency_ms, timestamp, metadata FROM transactions"
    )
    rows = cursor.fetchall()
    count = 0

    for row in rows:
        tx_id, user_id, amount, decision, risk_score, face_similarity, latency_ms, timestamp, metadata = row

        doc_data = {
            "tx_id":           tx_id,
            "user_id":         user_id,
            "amount":          float(amount) if amount is not None else 0.0,
            "decision":        decision,
            "risk_score":      float(risk_score) if risk_score is not None else None,
            "face_similarity": float(face_similarity) if face_similarity is not None else None,
            "latency_ms":      int(latency_ms) if latency_ms is not None else None,
            "timestamp":       timestamp or datetime.now().isoformat(),
            "metadata":        metadata or "{}",
        }

        firestore_db.collection(TRANSACTIONS_COLLECTION).document(tx_id).set(doc_data)
        print(f"  ✓ Transaction migrated: {tx_id} [{decision}]")
        count += 1

    return count


def main():
    print("=" * 60)
    print("  Firebase Migration: SQLite → Firestore")
    print("=" * 60)

    # ── Check SQLite file exists ──────────────────────────────────
    if not os.path.isfile(SQLITE_PATH):
        print(f"\n[WARNING] SQLite file not found at: {SQLITE_PATH}")
        print("Nothing to migrate. Exiting.")
        return

    print(f"\n[1/3] Connecting to SQLite: {SQLITE_PATH}")
    conn   = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()

    print("[2/3] Connecting to Firebase Firestore...")
    try:
        firestore_db = get_firestore_client()
        print("      Firebase connected successfully.")
    except Exception as e:
        print(f"\n[ERROR] Could not connect to Firebase: {e}")
        print("Make sure FIREBASE_CREDENTIALS_PATH is set and the file exists.")
        conn.close()
        sys.exit(1)

    print("\n[3/3] Starting migration...\n")

    # ── Migrate Users ─────────────────────────────────────────────
    print("── Users ──────────────────────────────────────────────")
    try:
        user_count = migrate_users(cursor, firestore_db)
    except sqlite3.OperationalError as e:
        print(f"  [SKIP] Users table not found or empty: {e}")
        user_count = 0

    # ── Migrate Transactions ──────────────────────────────────────
    print("\n── Transactions ───────────────────────────────────────")
    try:
        tx_count = migrate_transactions(cursor, firestore_db)
    except sqlite3.OperationalError as e:
        print(f"  [SKIP] Transactions table not found or empty: {e}")
        tx_count = 0

    conn.close()

    print("\n" + "=" * 60)
    print(f"  Migration Complete")
    print(f"  Users migrated      : {user_count}")
    print(f"  Transactions migrated: {tx_count}")
    print("=" * 60)
    print("\nYou can now set USE_FIREBASE=true in your .env and restart the server.")


if __name__ == "__main__":
    main()
