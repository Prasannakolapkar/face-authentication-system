"""
Firebase Firestore Database Manager
Credit & Debit Card Fraud Detection System

Drop-in replacement for DatabaseManager (src/database.py).
Implements the EXACT same public API so pipeline.py and server.py
require zero changes — only the __init__ in pipeline.py swaps
the class based on the USE_FIREBASE environment variable.

Firestore Collections:
    users/        — enrollment data, face embeddings (base64), credentials
    transactions/ — full transaction history with scores and decisions

Face embeddings (numpy float32 arrays) are serialized to base64 strings
for Firestore storage and deserialized back transparently on read.
"""

import os
import base64
import json
import logging
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional, Any

from firebase_config import get_firestore_client

logger = logging.getLogger(__name__)

# ── Collection names ───────────────────────────────────────────────────────────
USERS_COLLECTION        = "users"
TRANSACTIONS_COLLECTION = "transactions"


def _embed_to_b64(embedding: np.ndarray) -> str:
    """Serialize a numpy float32 array to a base64 string for Firestore storage."""
    return base64.b64encode(embedding.astype(np.float32).tobytes()).decode("utf-8")


def _b64_to_embed(b64_str: str) -> np.ndarray:
    """Deserialize a base64 string back to a numpy float32 array."""
    return np.frombuffer(base64.b64decode(b64_str), dtype=np.float32)


class FirestoreManager:
    """
    Handles persistence for the Fraud Detection System using Firebase Firestore.

    Public API is identical to DatabaseManager so it can be used as a
    transparent drop-in replacement.
    """

    def __init__(self, **kwargs):
        # Accept (and ignore) any kwargs that DatabaseManager accepts
        # (e.g. db_path) so callers need no changes.
        self.db = get_firestore_client()
        logger.info("[Firestore] FirestoreManager initialized.")

    # ── User Operations ────────────────────────────────────────────────────────

    def upsert_user(
        self,
        user_id: str,
        card_number: str,
        embedding: Optional[np.ndarray] = None,
        password_hash: Optional[str] = None,
        role: str = "CARDHOLDER",
        email: Optional[str] = None,
    ):
        """Add or update a cardholder document in Firestore."""
        doc_ref = self.db.collection(USERS_COLLECTION).document(user_id)
        existing = doc_ref.get()

        now = datetime.now().isoformat()

        if existing.exists:
            # Merge — only overwrite fields that are explicitly provided
            update_data: Dict[str, Any] = {
                "card_number": card_number,
            }
            if embedding is not None:
                update_data["face_embedding_b64"] = _embed_to_b64(embedding)
            if password_hash is not None:
                update_data["password_hash"] = password_hash
            if role:
                update_data["role"] = role
            if email is not None:
                update_data["email"] = email
            doc_ref.update(update_data)
        else:
            # Create full document
            doc_data: Dict[str, Any] = {
                "user_id": user_id,
                "card_number": card_number,
                "face_embedding_b64": _embed_to_b64(embedding) if embedding is not None else None,
                "password_hash": password_hash,
                "role": role,
                "email": email,
                "enrolled_at": now,
            }
            doc_ref.set(doc_data)

        logger.debug("[Firestore] upsert_user: %s", user_id)

    def get_user(self, user_id: str) -> Optional[Dict]:
        """Retrieve user data from Firestore. Returns None if not found."""
        doc_ref = self.db.collection(USERS_COLLECTION).document(user_id)
        doc = doc_ref.get()

        if not doc.exists:
            return None

        data = doc.to_dict()

        # Deserialize face embedding from base64 back to numpy array
        b64 = data.get("face_embedding_b64")
        if b64:
            try:
                data["face_embedding"] = _b64_to_embed(b64)
            except Exception:
                data["face_embedding"] = None
        else:
            data["face_embedding"] = None

        # Remove the raw b64 field so callers see the same shape as SQLite
        data.pop("face_embedding_b64", None)

        return data

    def list_users(self) -> List[str]:
        """Return list of all enrolled user IDs."""
        docs = self.db.collection(USERS_COLLECTION).stream()
        return [doc.id for doc in docs]

    def list_users_detail(self) -> List[Dict]:
        """Return detailed list of all enrolled users (without face embeddings)."""
        docs = self.db.collection(USERS_COLLECTION).stream()
        users = []
        for doc in docs:
            data = doc.to_dict()
            # Drop sensitive / large fields
            data.pop("face_embedding_b64", None)
            data.pop("password_hash", None)

            # Mask card number: show only last 4 digits (same as SQLite manager)
            card = data.get("card_number", "")
            if len(card) > 4:
                data["card_number"] = "•" * (len(card) - 4) + card[-4:]

            users.append({
                "user_id":    data.get("user_id", doc.id),
                "email":      data.get("email"),
                "card_number": data.get("card_number"),
                "role":       data.get("role"),
                "enrolled_at": data.get("enrolled_at"),
            })
        return users

    # ── Transaction Operations ─────────────────────────────────────────────────

    def log_transaction(self, tx_data: Dict[str, Any]):
        """Append a transaction document to Firestore."""
        tx_id = tx_data["tx_id"]
        doc_ref = self.db.collection(TRANSACTIONS_COLLECTION).document(tx_id)
        doc_ref.set({
            "tx_id":           tx_id,
            "user_id":         tx_data["user_id"],
            "amount":          float(tx_data["amount"]),
            "decision":        tx_data["decision"],
            "risk_score":      tx_data.get("fraud_score"),
            "face_similarity": tx_data.get("face_score"),
            "latency_ms":      tx_data.get("latency_ms"),
            "timestamp":       tx_data.get("timestamp", datetime.now().isoformat()),
            "metadata":        json.dumps(tx_data.get("metadata", {})),
        })
        logger.debug("[Firestore] log_transaction: %s", tx_id)

    def get_history(self, limit: int = 100) -> List[Dict]:
        """Retrieve latest transactions ordered by timestamp descending."""
        query = (
            self.db.collection(TRANSACTIONS_COLLECTION)
            .order_by("timestamp", direction="DESCENDING")
            .limit(limit)
        )
        docs = query.stream()
        return [doc.to_dict() for doc in docs]

    def get_stats(self) -> Dict:
        """Calculate pipeline statistics from Firestore transaction records."""
        docs = list(self.db.collection(TRANSACTIONS_COLLECTION).stream())
        total = len(docs)

        if total == 0:
            return {
                "total_transactions": 0,
                "approved": 0,
                "blocked": 0,
                "held_for_review": 0,
                "avg_latency_ms": 0,
            }

        approved = 0
        blocked  = 0
        held     = 0
        latencies: List[int] = []

        for doc in docs:
            data = doc.to_dict()
            decision = data.get("decision", "")
            if decision == "APPROVED":
                approved += 1
            elif decision.startswith("BLOCKED"):
                blocked += 1
            elif decision == "HELD_FOR_REVIEW":
                held += 1

            lat = data.get("latency_ms")
            if lat is not None:
                latencies.append(int(lat))

        avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0

        return {
            "total_transactions": total,
            "approved":           approved,
            "blocked":            blocked,
            "held_for_review":    held,
            "avg_latency_ms":     avg_latency,
        }
