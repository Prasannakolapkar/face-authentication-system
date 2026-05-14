"""
Fraud Detection Pipeline - Main Orchestrator
Credit & Debit Card Fraud Detection System
Integrates face recognition + ML transaction scoring into a unified pipeline.
Authors: Karan Sumbe, Isha Ghokane, Shantanu Aptikar, Shreya Pawar
"""

import sys
import os
import uuid
import time
from typing import Dict, Optional, Tuple
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import joblib
# NOTE: face_recognition (torch) MUST be imported before fraud_classifier (sklearn)
# on Windows. sklearn's native OpenBLAS/MKL extensions corrupt the Windows DLL
# loader state, causing torch's _load_dll_libraries() to fail with WinError 1114.
from models.face_recognition import FaceRecognitionEngine
from models.fraud_classifier import FraudClassifier
import os as _os
if _os.environ.get("USE_FIREBASE", "").lower() == "true":
    from firebase_database import FirestoreManager as DatabaseManager
    print("[INFO] Database backend: Firebase Firestore")
else:
    from database import DatabaseManager
    print("[INFO] Database backend: SQLite (local)")


# Import the new email alert service
from services.email_alert import send_fraud_alert




class FraudDetectionPipeline:
    """
    End-to-end fraud detection pipeline integrating dual-layer security:
    Gate 1: CNN biometric identity verification
    Gate 2: ML behavioral transaction analysis
    """

    def __init__(self, model_path: str = "../models/", data_path: str = "../data/"):
        print("Initializing Fraud Detection Pipeline...")
        self.db_manager = DatabaseManager(db_path=os.path.join(data_path, "fraud_detection.db"))
        self.face_engine = FaceRecognitionEngine(
            db_manager=self.db_manager
        )
        self.classifier = FraudClassifier(
            model_type="random_forest",
            model_path=model_path
        )
        self._ensure_model_ready()

    def _ensure_model_ready(self):
        """Train classifier on synthetic data if no saved model exists."""
        if not self.classifier.load_model():
            print("[INFO] No saved model found — training on synthetic data...")
            self.classifier.train(use_synthetic=True)
            self.classifier.save_model()
        else:
            print("[INFO] Loaded pre-trained fraud classifier")

    def enroll_cardholder(self, user_id: str, card_number: str, face_image=None) -> Dict:
        """
        Enroll a new cardholder: capture face embedding and register card.
        
        Args:
            user_id: Unique user identifier
            card_number: Associated card number (masked to last 4)
            face_image: Optional pre-captured face image array
            
        Returns:
            Dict with enrollment result
        """
        print(f"\n[ENROLLMENT] Starting face enrollment for user: {user_id}")
        success = self.face_engine.enroll_user(user_id, face_image)
        
        if success:
            # Update user info with card number in DB
            embedding = self.face_engine.embeddings.get(user_id)
            self.db_manager.upsert_user(user_id, card_number, embedding)

        masked_card = "**** **** **** " + card_number[-4:] if len(card_number) >= 4 else card_number
        return {
            "status": "enrolled" if success else "failed",
            "user_id": user_id,
            "card": masked_card,
            "timestamp": datetime.now().isoformat()
        }

    def process_transaction(self,
                            user_id: str,
                            transaction: Dict,
                            face_image=None,
                            skip_face_for_demo: bool = False,
                            skip_face: bool = False) -> Dict:
        """
        Process a transaction through the full dual-layer fraud detection pipeline.
        
        Args:
            user_id: Cardholder user ID
            transaction: Dict with transaction features (see FraudClassifier.extract_features)
            face_image: Optional pre-captured face image array
            skip_face_for_demo: If True, skips real face capture (for testing)
            
        Returns:
            Dict with transaction result including fraud_score, decision, latency
        """
        tx_id = str(uuid.uuid4())[:8].upper()
        pipeline_start = time.time()

        result = {
            "tx_id": tx_id,
            "user_id": user_id,
            "amount": transaction.get("amount", 0),
            "timestamp": datetime.now().isoformat(),
            "gate1_face": None,
            "gate2_ml": None,
            "final_decision": None,
            "total_latency_ms": None,
            "alert_triggered": False
        }

        print(f"\n{'='*60}")
        print(f"TRANSACTION ID: {tx_id}")
        print(f"User: {user_id} | Amount: ${transaction.get('amount', 0):.2f}")
        print(f"{'='*60}")

        # ── GATE 1: BIOMETRIC VERIFICATION ─────────────────────
        if skip_face:
            print("\n[GATE 1] Biometric Face Verification... SKIPPED (admin/privileged user)")
            result["gate1_face"] = {
                "passed": True,
                "similarity_score": 1.0,
                "latency_ms": 0,
                "mode": "skipped"
            }
        else:
            print("\n[GATE 1] Biometric Face Verification...")
            gate1_start = time.time()

            face_result = self.face_engine.verify_user(user_id, face_image)
            gate1_latency = int((time.time() - gate1_start) * 1000)

            result["gate1_face"] = {
                "passed": face_result.get("match", False),
                "similarity_score": face_result.get("similarity_score", 0.0),
                "latency_ms": gate1_latency,
                "mode": face_result.get("mode", "unknown")
            }

            if face_result.get("error"):
                result["gate1_face"]["error"] = face_result["error"]

            if not face_result.get("match", False):
                result["final_decision"] = "BLOCKED_BIOMETRIC_FAILURE"
                result["total_latency_ms"] = int((time.time() - pipeline_start) * 1000)
                result["alert_triggered"] = True
                result["block_reason"] = "Face verification failed \u2014 identity mismatch"
                self._log_transaction(result)
                self._print_result(result)
                
                # Fetch user details to get the registered email
                user_record = self.db_manager.get_user(user_id)
                user_email = user_record.get('email') if user_record else None
                
                # Fallback: if no email registered, use the sender email itself for monitoring
                if not user_email:
                    user_email = "ccard1582@gmail.com"
                
                # Get location from client IP
                client_ip = transaction.get('client_ip', 'Unknown')
                from services.location_service import get_user_location
                location_data = get_user_location(client_ip)
                
                # Trigger async fraud alert email
                card_preview = str(transaction.get('card_number', '0000'))[-4:]
                send_fraud_alert(
                    user_email=user_email,
                    transaction_amount=result["amount"],
                    card_last4=card_preview,
                    timestamp=result["timestamp"],
                    location_data=location_data
                )
                
                return result

        print(f"  ✓ Face match confirmed (similarity: {result['gate1_face']['similarity_score']:.3f})")

        # ── GATE 2: ML TRANSACTION ANALYSIS ────────────────────
        print("\n[GATE 2] ML Transaction Analysis...")
        gate2_start = time.time()

        ml_result = self.classifier.predict(transaction)
        gate2_latency = int((time.time() - gate2_start) * 1000)

        result["gate2_ml"] = {
            "fraud_score": ml_result["fraud_score"],
            "risk_level": ml_result["risk_level"],
            "decision": ml_result["decision"],
            "latency_ms": gate2_latency
        }

        print(f"  Fraud score: {ml_result['fraud_score']:.4f} | Risk: {ml_result['risk_level']}")

        # ── FINAL DECISION ──────────────────────────────────────
        ml_decision = ml_result["decision"]

        if ml_decision == "APPROVE":
            result["final_decision"] = "APPROVED"
            result["alert_triggered"] = False
        elif ml_decision == "HOLD_FOR_REVIEW":
            result["final_decision"] = "HELD_FOR_REVIEW"
            result["alert_triggered"] = True
            result["block_reason"] = f"Suspicious pattern detected (score: {ml_result['fraud_score']:.3f})"
        else:  # REJECT
            result["final_decision"] = "BLOCKED_ML_FRAUD"
            result["alert_triggered"] = True
            result["block_reason"] = f"High fraud probability (score: {ml_result['fraud_score']:.3f})"

        result["total_latency_ms"] = int((time.time() - pipeline_start) * 1000)
        self._log_transaction(result)
        self._print_result(result)

        return result

    def _print_result(self, result: Dict):
        """Print formatted transaction result."""
        decision = result["final_decision"]
        symbols = {
            "APPROVED": "✅",
            "HELD_FOR_REVIEW": "⚠️ ",
            "BLOCKED_BIOMETRIC_FAILURE": "🚫",
            "BLOCKED_ML_FRAUD": "🚫"
        }
        symbol = symbols.get(decision, "❓")
        print(f"\n{symbol} DECISION: {decision}")
        if result.get("block_reason"):
            print(f"   Reason: {result['block_reason']}")
        print(f"   Total latency: {result['total_latency_ms']}ms")
        if result.get("alert_triggered"):
            print("   📨 Alert notification sent to cardholder")
        print(f"{'='*60}")

    def _log_transaction(self, result: Dict):
        """Persist transaction to SQLite database."""
        tx_log_data = {
            "tx_id": result["tx_id"],
            "user_id": result["user_id"],
            "amount": result["amount"],
            "decision": result["final_decision"],
            "fraud_score": (result.get("gate2_ml") or {}).get("fraud_score"),
            "face_score": (result.get("gate1_face") or {}).get("similarity_score"),
            "latency_ms": result["total_latency_ms"],
            "timestamp": result["timestamp"]
        }
        self.db_manager.log_transaction(tx_log_data)

    def get_transaction_log(self) -> list:
        """Return latest transactions from database."""
        return self.db_manager.get_history()

    def get_stats(self) -> Dict:
        """Return pipeline performance statistics from database."""
        return self.db_manager.get_stats()


# ── DEMO RUNNER ──────────────────────────────────────────────────────────────

def run_demo():
    """Run a full demo of the fraud detection pipeline."""
    print("\n" + "="*70)
    print("  CREDIT & DEBIT CARD FRAUD DETECTION SYSTEM - DEMO")
    print("  Authors: Karan Sumbe, Isha Ghokane, Shantanu Aptikar, Shreya Pawar")
    print("="*70)

    pipeline = FraudDetectionPipeline(model_path="./models/", data_path="./data/")

    # Enroll test users
    print("\n[SETUP] Enrolling cardholders...")
    import numpy as np
    alice_face = np.random.rand(160, 160, 3).astype(np.float32)
    bob_face = np.random.rand(160, 160, 3).astype(np.float32)

    pipeline.face_engine.enroll_user("alice", alice_face)
    pipeline.face_engine.enroll_user("bob", bob_face)

    # ── Test Case 1: Normal transaction ──────────────────────────
    print("\n\n--- TEST 1: Normal legitimate transaction ---")
    pipeline.process_transaction(
        user_id="alice",
        transaction={
            "amount": 52.00, "hour": 15, "day_of_week": 1,
            "merchant_category": "grocery", "distance_from_home": 2.5,
            "distance_from_last_tx": 4.0, "time_since_last_tx": 300,
            "daily_tx_count": 2, "daily_spend": 75.0, "weekly_avg_spend": 110.0,
            "is_foreign": False, "device_match": True, "is_online": False, "velocity_flag": False
        },
        face_image=alice_face
    )

    # ── Test Case 2: Suspicious high-risk transaction ─────────────
    print("\n--- TEST 2: High-risk suspicious transaction ---")
    pipeline.process_transaction(
        user_id="bob",
        transaction={
            "amount": 3200.00, "hour": 3, "day_of_week": 6,
            "merchant_category": "gambling", "distance_from_home": 4500.0,
            "distance_from_last_tx": 2200.0, "time_since_last_tx": 3,
            "daily_tx_count": 15, "daily_spend": 7800.0, "weekly_avg_spend": 80.0,
            "is_foreign": True, "device_match": False, "is_online": True, "velocity_flag": True
        },
        face_image=bob_face
    )

    # ── Test Case 3: Face mismatch ────────────────────────────────
    print("\n--- TEST 3: Face identity mismatch (stolen card attempt) ---")
    intruder_face = np.random.rand(160, 160, 3).astype(np.float32)
    pipeline.process_transaction(
        user_id="alice",
        transaction={
            "amount": 199.00, "hour": 11, "day_of_week": 3,
            "merchant_category": "electronics", "distance_from_home": 15.0,
            "distance_from_last_tx": 10.0, "time_since_last_tx": 120,
            "daily_tx_count": 3, "daily_spend": 250.0, "weekly_avg_spend": 100.0,
            "is_foreign": False, "device_match": False, "is_online": True, "velocity_flag": False
        },
        face_image=intruder_face  # Different face!
    )

    # ── Summary ───────────────────────────────────────────────────
    print("\n\n=== PIPELINE STATISTICS ===")
    stats = pipeline.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n=== TRANSACTION LOG ===")
    for tx in pipeline.get_transaction_log():
        print(f"  [{tx['tx_id']}] {tx['decision']:30s} | ${tx['amount']:8.2f} | {tx['latency_ms']}ms")


if __name__ == "__main__":
    run_demo()
