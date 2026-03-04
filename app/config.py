from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Razorpay
    razorpay_key_id: str = "rzp_live_SN8uUEKbefkTOY"
    razorpay_key_secret: str = "jQ3ni56wOfHOXbLh40X5Q8Li"

    # Supabase
    supabase_url: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    # Product
    product_price_paise: int = 20000  # 200 INR
    product_name: str = "My Awesome Product"
    product_description: str = "Access to the premium product"

    # App URLs
    app_base_url: str = "http://localhost:8000"
    frontend_success_url: str = "http://localhost:3000/success"
    frontend_cancel_url: str = "http://localhost:3000/cancel"

    class Config:
        env_file = ".env"


settings = Settings()
