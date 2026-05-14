"""
Firebase Configuration — Singleton Initializer
Credit & Debit Card Fraud Detection System

Reads Firebase credentials from the environment and initializes the Firebase
Admin SDK exactly once. All other modules should use get_firestore_client()
to obtain a Firestore client rather than initializing Firebase themselves.

Required environment variables:
    FIREBASE_CREDENTIALS_PATH  — absolute or relative path to the
                                  Firebase service account JSON key file.

Usage:
    from firebase_config import get_firestore_client
    db = get_firestore_client()
"""

import os
import logging

logger = logging.getLogger(__name__)

_firebase_app = None


def initialize_firebase():
    """
    Initialize the Firebase Admin SDK (idempotent).
    Raises RuntimeError if FIREBASE_CREDENTIALS_PATH is not set or the file
    cannot be found.
    """
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        raise RuntimeError(
            "firebase-admin package is not installed. "
            "Run: pip install firebase-admin>=6.0.0"
        )

    cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "serviceAccountKey.json")
    abs_cred_path = os.path.abspath(cred_path)

    if not os.path.isfile(abs_cred_path):
        raise RuntimeError(
            f"Firebase credentials file not found at: {abs_cred_path}\n"
            "Set FIREBASE_CREDENTIALS_PATH to the path of your service account JSON key."
        )

    cred = credentials.Certificate(abs_cred_path)
    _firebase_app = firebase_admin.initialize_app(cred)
    logger.info("[Firebase] Initialized with credentials: %s", abs_cred_path)
    return _firebase_app


def get_firestore_client():
    """
    Return an initialized Firestore client. Initializes Firebase first if
    not already done.
    """
    initialize_firebase()
    from firebase_admin import firestore
    return firestore.client()
