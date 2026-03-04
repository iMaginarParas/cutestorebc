# 🛒 FastAPI Payment Gateway — Razorpay + Supabase + Gmail OAuth

Sell a ₹200 product with Google login, Razorpay checkout, and Supabase as your DB & auth layer.

---

## Stack
| Layer | Tool |
|-------|------|
| API | FastAPI + Uvicorn |
| Auth | Supabase (Google OAuth / Gmail) |
| Payments | Razorpay (live keys included) |
| Database | Supabase Postgres |

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up Supabase
1. Create a project at https://supabase.com
2. Go to **SQL Editor** → paste & run `supabase_migration.sql`
3. Go to **Authentication → Providers → Google** → enable it, add your Google OAuth credentials
4. Copy your **Project URL**, **Service Role Key**, and **JWT Secret** (Settings → API)

### 3. Configure environment
```bash
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET
```

### 4. Run the server
```bash
uvicorn app.main:app --reload
```

API docs → http://localhost:8000/docs

---

## Payment Flow

```
User                    Frontend              FastAPI              Razorpay
 |                          |                    |                    |
 |-- Click "Buy Now" -----> |                    |                    |
 |                          |-- POST /payments/create-order -------> |
 |                          |                    |<-- order_id -------|
 |                          |<-- order details --|                    |
 |                          |                    |                    |
 |<-- Razorpay Checkout popup (from JS SDK) -----|                    |
 |-- Pay ₹200 (UPI/Card/etc) ---------------------------------------->|
 |                          |<-- handler({ payment_id, signature }) --|
 |                          |-- POST /payments/verify -------------> |
 |                          |                    |-- HMAC verify -----|
 |                          |                    |-- DB: mark paid    |
 |                          |                    |-- DB: grant access |
 |                          |<-- { success: true } ---|              |
 |<-- "Access Granted 🎉" --|                    |                    |
```

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | ❌ | Health check |
| GET | `/auth/login/google` | ❌ | Redirect to Google OAuth |
| GET | `/auth/status` | ❌ | Auth info |
| POST | `/payments/create-order` | ✅ JWT | Create ₹200 Razorpay order |
| POST | `/payments/verify` | ✅ JWT | Verify payment signature |
| GET | `/payments/status` | ✅ JWT | Check if user has access |
| POST | `/webhooks/razorpay` | 🔑 Signature | Razorpay server events |

---

## Webhook Setup (Razorpay Dashboard)
1. Go to Razorpay Dashboard → **Settings → Webhooks**
2. Add URL: `https://your-domain.com/webhooks/razorpay`
3. Secret: your `RAZORPAY_KEY_SECRET`
4. Enable events: `payment.captured`, `payment.failed`, `order.paid`

> The webhook acts as a safety net — if the user closes the browser after paying but before `/verify` is called, the webhook will still grant access.

---

## Database Schema

### `purchases`
| Column | Type | Notes |
|--------|------|-------|
| id | uuid | PK |
| user_id | uuid | FK → auth.users |
| razorpay_order_id | text | unique |
| razorpay_payment_id | text | filled on success |
| amount_paise | int | 20000 = ₹200 |
| status | text | pending / paid / failed |
| paid_at | timestamptz | |

### `product_access`
| Column | Type | Notes |
|--------|------|-------|
| user_id | uuid | PK, FK → auth.users |
| razorpay_order_id | text | |
| granted_at | timestamptz | |

---

## Frontend
See `frontend_example.html` for a complete single-file frontend with:
- Google sign-in via Supabase
- Razorpay Checkout widget
- Payment verification
