import Stripe from "stripe";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).end("Method Not Allowed");
  }

  try {
    const session = await stripe.checkout.sessions.create({
      ui_mode: "embedded",
      line_items: [{ price: process.env.STRIPE_PRICE_ID, quantity: 1 }],
      mode: "payment",
      return_url: `${process.env.DOMAIN}/success?session_id={CHECKOUT_SESSION_ID}`,
      automatic_tax: { enabled: true },
    });

    res.json({ clientSecret: session.client_secret });
  } catch (err) {
    console.error("Stripe session creation failed:", err.message);
    res.status(500).json({ error: err.message });
  }
}
