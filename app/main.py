from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, payments, webhooks

app = FastAPI(
    title="Payment Gateway API",
    description="Sell products via Razorpay + Supabase + Gmail OAuth",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(payments.router, prefix="/payments", tags=["Payments"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])


@app.get("/")
def root():
    return {"message": "Payment Gateway is live 🚀", "product_price_inr": 200}
