"""
Real-Time Blink Liveness & Face Identity Verification Module
Uses OpenCV Haar Cascades for eye tracking (Python 3.14 compatible).
Runs blink detection and face recognition in parallel within a single webcam loop.
"""
import cv2
import time
import numpy as np
from typing import Dict


def run_liveness_and_recognition(face_engine, user_id: str, timeout: int = 5) -> Dict:
    """
    Opens the webcam and runs a real-time loop that simultaneously:
      1. Detects blinks via Haar Cascade eye tracking (liveness)
      2. Runs FaceNet identity verification on captured frames

    Args:
        face_engine: The existing FaceRecognitionEngine instance
        user_id: The enrolled user ID to verify against
        timeout: Max seconds to wait for a blink (default 5)

    Returns:
        Dict with keys: liveness_verified, face_match, similarity_score, mode
    """
    # Load built-in OpenCV Haar cascades (no external downloads needed)
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )
    eye_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_eye_tree_eyeglasses.xml'
    )

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[LIVENESS] ERROR: Could not open webcam.")
        return {
            "liveness_verified": False,
            "face_match": False,
            "similarity_score": 0.0,
            "mode": "error"
        }

    start_time = time.time()
    liveness_verified = False
    face_match = False
    best_similarity = 0.0
    best_mode = "production"

    # Blink state machine
    eyes_were_closed = False
    eyes_closed_count = 0
    CLOSED_THRESHOLD = 2  # Frames eyes must be closed before counting as blink

    # Face recognition throttle (run every 0.5s to save CPU)
    last_recog_time = 0
    RECOG_INTERVAL = 0.5

    window_name = 'KsheminPay Liveness Verification'

    while (time.time() - start_time) < timeout:
        ret, frame = cap.read()
        if not ret:
            continue

        frame = cv2.flip(frame, 1)  # Mirror for selfie view
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        elapsed = time.time() - start_time
        remaining = max(0, int(timeout - elapsed))

        # --- FACE DETECTION ---
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        if len(faces) > 0:
            # Use the largest face
            faces_sorted = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
            (fx, fy, fw, fh) = faces_sorted[0]

            # Draw face rectangle
            cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), (0, 255, 255), 2)

            # --- EYE DETECTION (upper 60% of face ROI) ---
            roi_gray = gray[fy:fy + int(fh * 0.6), fx:fx + fw]
            eyes = eye_cascade.detectMultiScale(roi_gray, 1.1, 10)

            # --- BLINK LOGIC ---
            if len(eyes) == 0:
                # No eyes detected = eyes are closed
                eyes_closed_count += 1
            else:
                if eyes_closed_count >= CLOSED_THRESHOLD:
                    # Eyes were closed and now reopened = BLINK!
                    liveness_verified = True
                    print(f"[LIVENESS] Blink detected! (closed for {eyes_closed_count} frames)")
                eyes_closed_count = 0

            # --- PARALLEL FACE RECOGNITION (throttled) ---
            now = time.time()
            if (now - last_recog_time) > RECOG_INTERVAL:
                last_recog_time = now
                try:
                    rgb_crop = cv2.cvtColor(frame[fy:fy+fh, fx:fx+fw], cv2.COLOR_BGR2RGB)
                    rgb_crop = cv2.resize(rgb_crop, (160, 160)).astype(np.float32) / 255.0
                    result = face_engine.verify_user(user_id, rgb_crop)
                    score = result.get("similarity_score", 0.0)
                    if score > best_similarity:
                        best_similarity = score
                        best_mode = result.get("mode", "production")
                    if result.get("match", False):
                        face_match = True
                except Exception as e:
                    print(f"[LIVENESS] Recognition error: {e}")

        # --- UI OVERLAY ---
        # Status bar background
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 90), (0, 0, 0), -1)

        # Liveness message
        if liveness_verified:
            msg = "Liveness verified. Processing authentication..."
            color = (0, 255, 0)
        elif remaining <= 1:
            msg = "Liveness check failed. Please try again."
            color = (0, 0, 255)
        else:
            msg = f"Please blink your eyes to verify liveness ({remaining}s)"
            color = (0, 255, 255)

        cv2.putText(frame, msg, (15, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # Identity status
        if face_match:
            id_text = f"Identity: VERIFIED ({user_id})"
            id_color = (0, 255, 0)
        elif len(faces) > 0:
            id_text = "Identity: Scanning..."
            id_color = (255, 255, 255)
        else:
            id_text = "Identity: No face detected"
            id_color = (100, 100, 100)

        cv2.putText(frame, id_text, (15, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, id_color, 1)

        cv2.imshow(window_name, frame)

        # Exit early if both conditions met
        if liveness_verified and face_match:
            cv2.waitKey(500)  # Brief pause to show "Verified" to the user
            break

        if cv2.waitKey(1) & 0xFF == 27:  # ESC key
            break

    cap.release()
    cv2.destroyAllWindows()

    if not liveness_verified:
        print("[LIVENESS] Timeout — no blink detected.")
    if not face_match:
        print(f"[LIVENESS] Face match failed (best similarity: {best_similarity:.4f})")

    return {
        "liveness_verified": liveness_verified,
        "face_match": face_match,
        "similarity_score": round(best_similarity, 4),
        "mode": best_mode
    }


if __name__ == "__main__":
    print("Standalone test — requires a FaceRecognitionEngine instance.")
