"""
FastAPI REST Backend
Credit & Debit Card Fraud Detection System
Endpoints for transaction processing, enrollment, and reporting.
Authors: Karan Sumbe, Isha Ghokane, Shantanu Aptikar, Shreya Pawar
"""

import sys
import os
import base64
import random
import time
import uuid
import numpy as np
from typing import Optional, List
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

try:
    from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Form, Depends
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    from fastapi.security import OAuth2PasswordRequestForm
    from pydantic import BaseModel, Field
    import uvicorn
    from api.auth import create_access_token, get_current_user, pwd_context
    from api.exceptions import AppException
    FASTAPI_AVAILABLE = True
except ImportError as e:
    FASTAPI_AVAILABLE = False
    print(f"[ERROR] Import failed: {e}")
    print("[WARNING] FastAPI/uvicorn not installed. Install with: pip install fastapi uvicorn")

if FASTAPI_AVAILABLE:
    from pipeline import FraudDetectionPipeline

    # ── DATA MODELS ────────────────────────────────────────────────
    class TransactionRequest(BaseModel):
        user_id: str = Field(..., description="Cardholder user ID")
        card_number: str = Field(..., description="Card number (last 4 will be stored)")
        amount: float = Field(..., gt=0, description="Transaction amount in USD")
        merchant_category: str = Field(default="other", description="Merchant category code")
        hour: int = Field(default=12, ge=0, le=23)
        day_of_week: int = Field(default=0, ge=0, le=6)
        distance_from_home: float = Field(default=5.0, ge=0)
        distance_from_last_tx: float = Field(default=5.0, ge=0)
        time_since_last_tx: float = Field(default=480.0, description="Minutes since last tx")
        daily_tx_count: int = Field(default=2, ge=1)
        daily_spend: float = Field(default=100.0, ge=0)
        weekly_avg_spend: float = Field(default=100.0, ge=0)
        is_foreign: bool = Field(default=False)
        device_match: bool = Field(default=True)
        is_online: bool = Field(default=False)
        velocity_flag: bool = Field(default=False)
        face_image_b64: Optional[str] = Field(default=None, description="Base64-encoded face image (JPEG/PNG)")

    class EnrollmentRequest(BaseModel):
        user_id: str
        card_number: str
        email: Optional[str] = None
        face_image_b64: Optional[str] = None

    class CardValidateRequest(BaseModel):
        user_id: str
        card_number: str

    class OTPRequest(BaseModel):
        user_id: str

    class OTPVerifyRequest(BaseModel):
        user_id: str
        otp: str

    class TransactionResponse(BaseModel):
        tx_id: str
        decision: str
        fraud_score: Optional[float]
        face_similarity: Optional[float]
        risk_level: Optional[str]
        latency_ms: int
        alert_triggered: bool
        timestamp: str
        message: str

    class StatsResponse(BaseModel):
        total_transactions: int
        approved: int
        blocked: int
        held_for_review: int
        avg_latency_ms: int

    class Token(BaseModel):
        access_token: str
        token_type: str

    # ── APP SETUP ──────────────────────────────────────────────────
    app = FastAPI(
        title="Card Fraud Detection API",
        description="Real-time fraud detection using CNN face recognition + ML transaction analysis",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # --- Middleware ---
    # Robust CORS setup for Cloudflare -> Render integration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], # Cloudflare domain + wildcard for testing
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"]
    )

    # --- Mount Static Files (Only for local dev) ---
    # Corrected path to point to src/static relative to src/api
    static_path = os.path.join(os.path.dirname(__file__), "..", "static")
    if os.path.exists(static_path):
        app.mount("/static", StaticFiles(directory=static_path), name="static")
    else:
        print("[INFO] Static directory not found. Assuming production mode with separate frontend.")

    # --- Endpoints ---

    @app.get("/", response_class=HTMLResponse)
    async def root():
        """Redirect root to the static index page."""
        return FileResponse(os.path.join(static_path, "index.html"))

    @app.get("/health")
    async def health_check():
        """Deployment health check."""
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0-deploy",
            "memory_mode": "lightweight"
        }

    # Initialize pipeline (singleton)
    pipeline = FraudDetectionPipeline(
        model_path=os.path.join(os.path.dirname(__file__), "../models/"),
        data_path=os.path.join(os.path.dirname(__file__), "../../data/")
    )

    # In-memory OTP store: { user_id: { "otp": str, "expires_at": float } }
    otp_store = {}

    # ── EXCEPTION HANDLERS ──────────────────────────────────────────
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"message": exc.message},
            headers=exc.headers
        )

    @app.exception_handler(HTTPException)
    async def standard_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"message": exc.detail},
            headers=exc.headers
        )

    def decode_face_image(b64_string: str) -> Optional[np.ndarray]:
        try:
            img_bytes = base64.b64decode(b64_string)
            img_array = np.frombuffer(img_bytes, dtype=np.uint8)
            try:
                import cv2
                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                img_resized = cv2.resize(img_rgb, (160, 160)).astype(np.float32) / 255.0
                return img_resized
            except ImportError:
                return np.random.rand(160, 160, 3).astype(np.float32)
        except Exception:
            return None

    # ── ENDPOINTS ──────────────────────────────────────────────────

    @app.get("/", summary="Serve UI")
    async def root():
        return FileResponse(os.path.join(os.path.dirname(__file__), "../static/index.html"))

    @app.get("/health", summary="System health")
    async def health():
        return {
            "status": "healthy",
            "face_engine": "operational",
            "ml_classifier": "operational" if pipeline.classifier.is_trained else "loading",
            "enrolled_users": len(pipeline.face_engine.get_enrolled_users()),
            "database": "connected"
        }

    @app.post("/login", response_model=Token, summary="Obtain access token")
    async def login(form_data: OAuth2PasswordRequestForm = Depends()):
        user = pipeline.db_manager.get_user(form_data.username)
        if not user or not pwd_context.verify(form_data.password, user["password_hash"]):
            raise AppException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token = create_access_token(data={"sub": user["user_id"]})
        return {"access_token": access_token, "token_type": "bearer"}

    # ── ADMIN AUTHENTICATION ────────────────────────────────────────
    # Hardcoded admin credentials — validated on backend only, never exposed to frontend
    ADMIN_USERNAME = "admin"
    ADMIN_PASSWORD = "admin123"

    class AdminLoginRequest(BaseModel):
        username: str
        password: str

    @app.post("/admin/login", response_model=Token, summary="Admin login with hardcoded credentials")
    async def admin_login(request: AdminLoginRequest):
        """Admin-only login. Credentials are hardcoded and never stored in the database."""
        if request.username != ADMIN_USERNAME or request.password != ADMIN_PASSWORD:
            raise AppException(
                status_code=401,
                message="Invalid Admin Credentials",
            )
        # Issue a JWT token with role=admin so the frontend can identify the session type
        access_token = create_access_token(data={"sub": ADMIN_USERNAME, "role": "admin"})
        return {"access_token": access_token, "token_type": "bearer"}

    @app.get("/admin/verify", summary="Verify that a token belongs to an admin session")
    async def admin_verify(raw_token: str = Depends(oauth2_scheme)):
        """Returns 200 OK only if the Authorization Bearer token has role=admin."""
        from jose import JWTError, jwt as _jwt
        from api.auth import SECRET_KEY, ALGORITHM
        try:
            payload = _jwt.decode(raw_token, SECRET_KEY, algorithms=[ALGORITHM])
        except JWTError:
            raise AppException(status_code=401, message="Invalid or expired token")
        if payload.get("role") != "admin":
            raise AppException(status_code=403, message="Admin access required")
        return {"admin": True}

    @app.post("/enroll", summary="Enroll a new cardholder")
    async def enroll_user(request: EnrollmentRequest):
        # Admin check removed to allow public registration
        
        face_image = None
        if request.face_image_b64:
            try:
                import base64
                import cv2
                import numpy as np
                img_data = base64.b64decode(request.face_image_b64)
                nparr = np.frombuffer(img_data, np.uint8)
                face_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if face_image is not None:
                    face_image = cv2.cvtColor(face_image, cv2.COLOR_BGR2RGB)
                    face_image = cv2.resize(face_image, (160, 160))
                    face_image = face_image.astype(np.float32) / 255.0
            except Exception as e:
                print(f"[ERROR] Error decoding face image during enrollment: {e}")

        result = pipeline.enroll_cardholder(request.user_id, request.card_number, face_image=face_image)
        hashed_pw = pwd_context.hash(request.user_id + "123")
        pipeline.db_manager.upsert_user(request.user_id, request.card_number, role="CARDHOLDER", password_hash=hashed_pw)
        
        # Save the email if provided
        if request.email:
            with pipeline.db_manager._get_connection() as conn:
                conn.execute('UPDATE users SET email = ? WHERE user_id = ?', (request.email, request.user_id))
                conn.commit()
        
        return result

    # ── CARD VALIDATION ────────────────────────────────────────
    @app.post("/validate-card", summary="Validate card credentials against registered data")
    async def validate_card(request: CardValidateRequest):
        user = pipeline.db_manager.get_user(request.user_id)
        if not user:
            raise AppException(status_code=400, message="User not found. Please register first.")

        # Compare card number (strip spaces)
        input_card = request.card_number.replace(" ", "")
        stored_card = user.get("card_number", "").replace(" ", "")

        if input_card != stored_card:
            raise AppException(status_code=400, message="Wrong credentials — card number does not match registered card.")

        return {"valid": True, "message": "Card verified successfully."}

    # ── OTP GENERATION ─────────────────────────────────────────
    @app.post("/generate-otp", summary="Generate a 6-digit OTP for the user")
    async def generate_otp(request: OTPRequest):
        user = pipeline.db_manager.get_user(request.user_id)
        if not user:
            raise AppException(status_code=400, message="User not found.")

        otp_code = str(random.randint(100000, 999999))
        otp_store[request.user_id] = {
            "otp": otp_code,
            "expires_at": time.time() + 60  # 60 second expiry
        }
        print(f"[OTP] Generated OTP for {request.user_id}: {otp_code}")
        # Return OTP in response for testing purposes
        return {"otp": otp_code, "expires_in": 60, "message": "OTP generated successfully."}

    # ── OTP VERIFICATION ───────────────────────────────────────
    @app.post("/verify-otp", summary="Verify the entered OTP")
    async def verify_otp_endpoint(request: OTPVerifyRequest):
        stored = otp_store.get(request.user_id)
        if not stored:
            raise AppException(status_code=400, message="No OTP generated. Please request a new OTP.")

        if time.time() > stored["expires_at"]:
            del otp_store[request.user_id]
            raise AppException(status_code=400, message="OTP expired. Please generate a new OTP.")

        if request.otp != stored["otp"]:
            raise AppException(status_code=400, message="Wrong OTP. Please try again.")

        # OTP verified — remove from store
        del otp_store[request.user_id]
        return {"valid": True, "message": "OTP verified successfully."}

    # ── TRANSACTION ────────────────────────────────────────────
    @app.post("/transaction", response_model=TransactionResponse, summary="Process a transaction")
    async def process_transaction(request: TransactionRequest, fastapi_req: Request):

        # Validate card number matches registered card
        tx_user_info = pipeline.db_manager.get_user(request.user_id)
        if not tx_user_info:
            raise AppException(status_code=400, message="User not registered.")
        
        input_card = request.card_number.replace(" ", "")
        stored_card = tx_user_info.get("card_number", "").replace(" ", "")
        if input_card != stored_card:
            raise AppException(status_code=400, message="Card number mismatch — fraud alert sent to registered cardholder.")

        face_image = None
        if request.face_image_b64:
            if request.face_image_b64 == "LIVENESS_FAILED":
                # Frontend timed out on blink detection
                from services.email_alert import send_fraud_alert
                from services.location_service import get_user_location
                
                client_ip = fastapi_req.client.host
                location_data = get_user_location(client_ip)
                user_email = tx_user_info.get('email', "ccard1582@gmail.com")
                
                # Trigger async fraud alert email
                send_fraud_alert(
                    user_email=user_email,
                    transaction_amount=request.amount,
                    card_last4=request.card_number[-4:],
                    timestamp=datetime.now().isoformat(),
                    location_data=location_data
                )
                
                return TransactionResponse(
                    tx_id=str(uuid.uuid4())[:8].upper(),
                    decision="BLOCKED_BIOMETRIC_FAILURE",
                    latency_ms=0,
                    alert_triggered=True,
                    timestamp=datetime.now().isoformat(),
                    message="Transaction blocked: Liveness verification timeout."
                )
                
            face_image = decode_face_image(request.face_image_b64)

        tx_data = request.model_dump(exclude={"face_image_b64", "user_id", "card_number"})
        tx_data["client_ip"] = fastapi_req.client.host
        tx_data["card_number"] = request.card_number # Always include full card number for downstream alerts

        # Face verification is always required — no skip
        result = pipeline.process_transaction(
            user_id=request.user_id,
            transaction=tx_data,
            face_image=face_image
        )

        messages = {
            "APPROVED": "Transaction approved successfully.",
            "HELD_FOR_REVIEW": "Transaction flagged for review. You may be contacted.",
            "BLOCKED_BIOMETRIC_FAILURE": "Transaction blocked: identity verification failed.",
            "BLOCKED_ML_FRAUD": "Transaction blocked: suspicious activity detected."
        }

        return TransactionResponse(
            tx_id=result["tx_id"],
            decision=result["final_decision"],
            fraud_score=result.get("gate2_ml", {}).get("fraud_score") if result.get("gate2_ml") else None,
            face_similarity=result.get("gate1_face", {}).get("similarity_score") if result.get("gate1_face") else None,
            risk_level=result.get("gate2_ml", {}).get("risk_level") if result.get("gate2_ml") else None,
            latency_ms=result["total_latency_ms"],
            alert_triggered=result["alert_triggered"],
            timestamp=result["timestamp"],
            message=messages.get(result["final_decision"], "Processing complete.")
        )

    @app.get("/stats", summary="Pipeline statistics")
    async def get_stats():
        """Returns overall transaction statistics."""
        try:
            stats = pipeline.db_manager.get_stats()
            return stats
        except Exception as e:
            raise AppException(status_code=500, message=f"Database error: {str(e)}")

    @app.get("/transactions", summary="Transaction history")
    async def get_transactions(limit: int = 50):
        """Returns recent transactions."""
        try:
            history = pipeline.db_manager.get_history(limit=limit)
            return history
        except Exception as e:
            raise AppException(status_code=500, message=f"Database error: {str(e)}")

    @app.get("/users", summary="Registered users list")
    async def get_users():
        """Returns a list of all registered users."""
        try:
            users = pipeline.db_manager.list_users_detail()
            return users
        except Exception as e:
            raise AppException(status_code=500, message=f"Database error: {str(e)}")
            
    @app.get("/dashboard", summary="Legacy dashboard endpoint")
    async def get_dashboard():
        users = pipeline.db_manager.list_users_detail()
        stats = pipeline.db_manager.get_stats()
        history = pipeline.db_manager.get_history(limit=50)
        
        # Include system thresholds for Settings view
        settings = {
            "fraud_threshold": pipeline.classifier.fraud_threshold,
            "review_threshold": pipeline.classifier.review_threshold,
            "face_match_threshold": pipeline.face_engine.MATCH_THRESHOLD,
            "is_demo_mode": pipeline.face_engine.is_demo_mode
        }
        
        return {
            "total_users": len(users),
            "users": users,
            "transaction_stats": stats,
            "transactions": history,
            "settings": settings
        }

    if __name__ == "__main__":
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
