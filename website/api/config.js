export default function handler(_req, res) {
  res.json({ publishableKey: process.env.STRIPE_PUBLISHABLE_KEY });
}
