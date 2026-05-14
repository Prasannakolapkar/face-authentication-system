import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import time
from datetime import datetime
import threading

# Configure basic logger for the email service
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# SMTP Configuration (In production, use os.getenv)
# Using Gmail SMTP as the solution for domain-free delivery
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465  # SSL Port
SMTP_SENDER_EMAIL = "ccard1582@gmail.com"
# For Gmail, you MUST use an "App Password" (16-digit code) here
SMTP_SENDER_PASSWORD = "qmjg lsjk qhjm zhre" 


# --- SANDBOX SETTINGS ---
# SMTP does not have sandbox restrictions like Resend
USE_SANDBOX_OVERRIDE = False 
VERIFIED_TEST_EMAIL = "ccard1582@gmail.com" 

def _send_email_async(user_email: str, amount: float, card_last4: str, timestamp: str, location_data: dict = None):
    """Internal function to actually send the email using SMTP."""
    
    recipient = user_email
    if USE_SANDBOX_OVERRIDE:
        recipient = VERIFIED_TEST_EMAIL

    if not location_data:
        location_data = {}
        
    city = location_data.get('city', 'Unknown')
    region = location_data.get('region', 'Unknown')
    country = location_data.get('country', 'Unknown')
    isp = location_data.get('isp', 'Unknown')
    ip_addr = location_data.get('ip', 'Unknown')

    location_str = "Unknown Location"
    if city != "Unknown" or region != "Unknown" or country != "Unknown":
        location_parts = [p for p in [city, region, country] if p != "Unknown"]
        location_str = ", ".join(location_parts)
        
    try:
        # Create message container
        message = MIMEMultipart("alternative")
        message["Subject"] = "Security Alert: Unrecognized Payment Authentication Attempt"
        message["From"] = f"KsheminPay Alerts <{SMTP_SENDER_EMAIL}>"
        message["To"] = recipient

        html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px;">
                <h2 style="color: #dc2626; text-align: center;">Fraud Detection Security Alert</h2>
                <p>Hello,</p>
                <p>A payment attempt was detected using your registered credit/debit card, but the face authentication did not match the registered cardholder.</p>
                <div style="background-color: #fef2f2; padding: 15px; border-left: 4px solid #dc2626; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Details:</strong></p>
                    <ul style="margin-top: 5px;">
                        <li><strong>Status:</strong> Face Verification Failed</li>
                        <li><strong>Time:</strong> {timestamp}</li>
                        <li><strong>Location:</strong> {location_str} (IP: {ip_addr})</li>
                    </ul>
                </div>
                <p>If this activity was not performed by you, please immediately contact your bank or block your card.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;" />
                <p style="font-size: 12px; color: #888; text-align: center;">This is an automated security notification from the Fraud Detection System.</p>
            </div>
          </body>
        </html>
        """
        
        # Attach HTML content
        message.attach(MIMEText(html_content, "html"))

        # Create secure SSL context and send
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(SMTP_SENDER_EMAIL, SMTP_SENDER_PASSWORD)
            server.sendmail(SMTP_SENDER_EMAIL, recipient, message.as_string())

        logger.info(f"Fraud alert email successfully sent via SMTP to {recipient}")

    except Exception as e:
        logger.error(f"Failed to send fraud alert email to {recipient} via SMTP: {str(e)}")


def send_fraud_alert(user_email: str, transaction_amount: float, card_last4: str, timestamp: str, location_data: dict = None):
    """
    Public entry point to trigger a fraud alert email.
    Uses threading to prevent blocking the main authentication pipeline.
    """
    logger.info(f"Triggering fraud alert email to {user_email}")
    
    # We offload the email sending to a separate thread so it doesn't affect the inference latency (<100ms goal)
    thread = threading.Thread(
        target=_send_email_async, 
        args=(user_email, transaction_amount, card_last4, timestamp, location_data)
    )
    thread.daemon = True # Dies when main thread dies
    thread.start()

# For local testing
if __name__ == "__main__":
    send_fraud_alert("ccard1582@gmail.com", 599.00, "1234", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("Test triggered, waiting 5 seconds for background thread...")
    time.sleep(5) # Wait for thread
