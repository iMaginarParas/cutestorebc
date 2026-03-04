import razorpay
import hmac
import hashlib
from app.config import settings

client = razorpay.Client(
    auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
)


def create_order(receipt: str) -> dict:
    """Create a Razorpay order for 200 INR."""
    return client.order.create({
        "amount": settings.product_price_paise,  # paise
        "currency": "INR",
        "receipt": receipt,
        "notes": {
            "product": settings.product_name,
        },
        "payment_capture": 1,  # auto-capture
    })


def verify_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify Razorpay payment signature (HMAC-SHA256)."""
    payload = f"{order_id}|{payment_id}"
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body: bytes, received_sig: str) -> bool:
    """Verify incoming webhook from Razorpay."""
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received_sig)
