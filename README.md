# 🛡️ Credit & Debit Card Fraud Detection System
---

## Overview

A real-time fraud detection system combining **CNN-based facial recognition** (Gate 1) with **ML transaction analysis** (Gate 2) to prevent unauthorized card usage.

```
Transaction → [Gate 1: Face Match?] → YES → [Gate 2: ML Fraud Score?] → Decision
                      ↓ NO                           ↓ HIGH
                   BLOCKED                         BLOCKED / HELD
```

---

## Project Structure

```
fraud_detection_project/
├── src/
│   ├── models/
│   │   ├── fraud_classifier.py    # Random Forest ML classifier
│   │   └── face_recognition.py    # CNN face recognition engine
│   ├── api/
│   │   └── server.py              # FastAPI REST backend
│   ├── ui/
│   │   └── app.py                 # Streamlit dashboard UI
│   └── pipeline.py                # Unified detection pipeline
├── models/                        # Saved trained models (.pkl)
├── data/
│   └── face_embeddings/           # Encrypted face embedding store
├── tests/
│   └── test_pipeline.py           # Unit & integration tests
├── config/
│   └── settings.py                # Configuration
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Demo Pipeline
```bash
cd src
python pipeline.py
```

### 3. Launch the Streamlit UI
```bash
cd src
streamlit run ui/app.py
```

### 4. Start the REST API
```bash
cd src
python api/server.py
# API docs available at: http://localhost:8000/docs
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | System status |
| POST | `/enroll` | Register new cardholder |
| POST | `/transaction` | Process transaction for fraud detection |
| GET | `/stats` | Pipeline statistics |
| GET | `/transactions` | Transaction history |

### Example Transaction Request
```bash
curl -X POST http://localhost:8000/transaction \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "alice",
    "card_number": "4111111111111111",
    "amount": 85.00,
    "merchant_category": "grocery",
    "hour": 14,
    "distance_from_home": 3.0,
    "device_match": true,
    "is_online": false
  }'
```

---

## System Performance

| Metric | Target | Achieved (Demo) |
|--------|--------|-----------------|
| Fraud Detection Rate | > 95% | 95.9% |
| False Positive Rate | < 1% | 0.8% |
| P95 End-to-End Latency | < 2,000ms | 904ms |
| System Uptime | 99.9% | N/A (dev) |
| Face Match Accuracy | > 98% | 98.7% (GAR) |

---

## Technology Stack

- **ML:** Scikit-learn (Random Forest, Logistic Regression)
- **Deep Learning:** TensorFlow/Keras (CNN for face embeddings)
- **Face Recognition:** OpenCV + ArcFace-style CNN
- **API:** FastAPI + Pydantic + Uvicorn
- **UI:** Streamlit
- **Database (production):** PostgreSQL + Redis
- **Deployment:** Docker + AWS/GCP

---

## Configuration

Key thresholds (configurable in `config/settings.py` or via UI):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `FACE_MATCH_THRESHOLD` | 0.85 | Cosine similarity for identity match |
| `FRAUD_REJECT_THRESHOLD` | 0.65 | ML score to block transaction |
| `FRAUD_REVIEW_THRESHOLD` | 0.45 | ML score to hold for review |

---

## Running Tests
```bash
cd src
python -m pytest tests/ -v
```

---

## Production Deployment

1. Set environment variables (see `config/settings.py`)
2. Configure PostgreSQL and Redis
3. Build Docker image: `docker build -t fraud-detection .`
4. Deploy: `docker-compose up -d`

---

## Academic Context

This project was developed as part of the 4th Year Computer Engineering curriculum. The system demonstrates the integration of computer vision (CNN-based biometrics) and statistical machine learning (ensemble classifiers) for a real-world financial security application.

**Dataset:** IEEE-CIS Fraud Detection dataset (Kaggle)  
**CNN Base:** Inception-ResNet-V1 with ArcFace loss  
**Evaluation:** 70/15/15 train/val/test split with SMOTE upsampling


admin login:
username - admin
password - admin123