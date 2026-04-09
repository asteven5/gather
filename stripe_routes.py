"""Stripe Checkout routes — embedded payment flow."""

import stripe
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from config import HOST, PORT, STRIPE_PRICE_ID, STRIPE_SECRET_KEY, logger

stripe.api_key = STRIPE_SECRET_KEY

router = APIRouter(prefix="/stripe", tags=["stripe"])

DOMAIN = f"http://{HOST}:{PORT}"


@router.get("/config")
async def stripe_config():
    """Return the publishable key so the frontend can init Stripe.js."""
    from config import STRIPE_PUBLISHABLE_KEY

    return {"publishableKey": STRIPE_PUBLISHABLE_KEY}


@router.post("/create-checkout-session")
async def create_checkout_session():
    """Create an embedded Stripe Checkout session and return the client secret."""
    try:
        session = stripe.checkout.Session.create(
            ui_mode="embedded",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="payment",
            return_url=f"{DOMAIN}/stripe/return?session_id={{CHECKOUT_SESSION_ID}}",
            automatic_tax={"enabled": True},
        )
        return JSONResponse({"clientSecret": session.client_secret})
    except stripe.StripeError as exc:
        logger.exception("Stripe checkout session creation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/session-status")
async def session_status(session_id: str):
    """Check the status of a completed checkout session."""
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        return {
            "status": session.status,
            "customer_email": session.customer_details.email,
        }
    except stripe.StripeError as exc:
        logger.exception("Stripe session retrieval failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
