# CyberGateway — Vercel demo starter

This repository contains a Next.js demo interface for a private multi-website gateway concept.

## Included
- Responsive blue/white dashboard
- Demo website list and demo key generation (browser-only; not real credentials)
- Demo order creation and QR rendering
- Demo transaction status display
- API integration outline for a future server-side implementation

## Important: demo mode only
This repository does **not** accept, collect, route, settle, or verify real payments. The QR encodes a demo checkout URL, not a UPI payment instruction. Demo keys are generated in the browser and are not authentication credentials. Do not use this as a live payment gateway or connect it to a real bank/UPI account.

A real payment integration must be implemented through an authorized payment provider, with the account holder's permission and required compliance. A customer-submitted reference or screenshot is not proof of payment.

## Deploy on Vercel
1. Import this repository in Vercel.
2. Keep the framework preset as Next.js.
3. Build command: `npm run build`.
4. Deploy. No environment variables are needed for this demo.

## Local development
```bash
npm install
npm run dev
```
Open http://localhost:3000.
