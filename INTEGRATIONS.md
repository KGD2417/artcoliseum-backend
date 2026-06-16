# Payments (Razorpay) & Shipping (Shiprocket)

Both integrations are **optional and degrade gracefully**. With no credentials
set, checkout uses the built-in demo payment overlay and a static India PIN-zone
shipping table — exactly as before. Fill in the env vars to go live.

> Scope today: **India domestic only.** The code is structured so international
> (multi-currency Razorpay + Shiprocket X / DHL) can be added later without a
> rewrite — see the notes in `app/utils/shipping.py` and `app/utils/pricing.py`.

Install deps after pulling: `pip install -r requirements.txt`

---

## Razorpay (payments)

### 1. Get keys
Razorpay Dashboard → **Settings → API Keys → Generate**. Use the `rzp_test_*`
pair while testing. Put them in `.env`:

```
RAZORPAY_KEY_ID=rzp_test_T2DrUsQ1TS2cdu
RAZORPAY_KEY_SECRET=aOxhA51QrO76eTeYK7IwQoEW
```

### 2. Webhook (recommended — server-side source of truth)
Dashboard → **Settings → Webhooks → Add New Webhook**
- URL: `https://YOUR_BACKEND/orders/razorpay/webhook`
- Active event: `payment.captured`
- Secret: any strong string — put the **same** value in `.env`:

```
RAZORPAY_WEBHOOK_SECRET=aOxhA51QrO76eTeYK7IwQoEW
```

### Flow
1. `POST /orders` creates the order **and** a matching Razorpay order; the
   response carries `razorpay_order_id`, `razorpay_key_id`, `amount_due` (paise).
2. The frontend opens Razorpay Checkout with those, gets back
   `razorpay_payment_id` + `razorpay_signature`.
3. `POST /orders/{id}/verify` checks the signature, then fulfills (delivery +
   ownership). The webhook does the same independently, so a closed browser tab
   never loses an order.
4. `POST /orders/{id}/pay` (the old demo "pay") is **disabled** whenever live
   keys are present.

### Test card
`4111 1111 1111 1111`, any future expiry, any CVV, any OTP. (Razorpay test mode.)

---

## Shiprocket (shipping)

### 1. Create an API user
Shiprocket panel → **Settings → API → Configure → Create an API User**
(this is a *separate* login from your normal account). Then:

```
SHIPROCKET_EMAIL=kshitijdesai179@gmail.com
SHIPROCKET_PASSWORD=L3LEVOP2WuAy*^Q1#$jgwnSFoq7*p9jX
```

### 2. Pickup location
Add your warehouse under **Settings → Company → Pickup Addresses** and set the
nickname + origin PIN:

```
SHIPROCKET_PICKUP_PINCODE=400001
SHIPROCKET_PICKUP_LOCATION=Primary   # must match the nickname exactly
```

Optional parcel defaults (used when an item has no measured packaging):
`SHIP_DEFAULT_WEIGHT_KG`, `SHIP_DEFAULT_LENGTH_CM`, `SHIP_DEFAULT_BREADTH_CM`,
`SHIP_DEFAULT_HEIGHT_CM`.

### Flow
- `GET /deliveries/estimate?pincode=` → live cheapest courier rate + ETA
  (cached 10 min per PIN). Falls back to the static table if not serviceable.
- On payment, `_finalize_paid` books a Shiprocket adhoc order, assigns the
  cheapest AWB, and stores it as the delivery's tracking id. Falls back to a
  generated tracking id on any failure / for self-pickup orders.

---

## Going live checklist
- [ ] Swap `rzp_test_*` → `rzp_live_*` keys.
- [ ] Point the webhook URL at the production backend; re-copy the secret.
- [ ] Confirm the Shiprocket pickup nickname matches `SHIPROCKET_PICKUP_LOCATION`.
- [ ] Ensure `RAZORPAY_*` / `SHIPROCKET_*` are set in the Railway (prod) env, not just `.env`.
