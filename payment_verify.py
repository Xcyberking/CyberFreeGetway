"""
UPI payment verification via Gmail IMAP.
User ek UTR daalta hai -> hum Gmail inbox mein us UTR ka email dhundhte hain.
Match mila + amount sahi + note sahi -> plan activate.
"""
import imaplib
import email
import email.utils
import re
import logging
from datetime import datetime, timedelta

from config import Config
from parser import clean_body

log = logging.getLogger(__name__)

IMAP_TIMEOUT = 20
SEARCH_DAYS  = 7          # payment emails usually recent
AMOUNT_RE    = re.compile(r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
UTR_RE       = re.compile(r"\b(\d{12})\b")
CREDIT_HINT  = re.compile(
    r"(credited|received|deposited|received\s+from|money\s+received|"
    r"upi\s+credit|payment\s+received)", re.I
)


def _extract_body(msg) -> str:
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct not in ("text/plain", "text/html"): continue
            try:
                cs = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True).decode(cs, errors="replace")
                if ct == "text/plain": plain += payload + " "
                else: html += payload + " "
            except Exception: continue
    else:
        try:
            cs = msg.get_content_charset() or "utf-8"
            plain = msg.get_payload(decode=True).decode(cs, errors="replace")
        except Exception: pass
    return plain if plain.strip() else html


def find_upi_credit(utr: str) -> dict:
    """
    Search Gmail for an email containing this UTR that looks like a UPI credit.
    Returns:
      {"found": True,  "amount": "299", "sender": "Rahul", "snippet": "..."}
      {"found": False, "reason": "..."}
    """
    if not Config.EMAIL_ADDRESS or not Config.EMAIL_APP_PASS:
        return {"found": False, "reason": "email_not_configured"}
    if not re.fullmatch(r"\d{10,18}", utr):
        return {"found": False, "reason": "invalid_utr_format"}

    mail = None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=IMAP_TIMEOUT)
        mail.login(Config.EMAIL_ADDRESS, Config.EMAIL_APP_PASS)
        mail.select("INBOX", readonly=True)

        since = (datetime.now() - timedelta(days=SEARCH_DAYS)).strftime("%d-%b-%Y")
        status, data = mail.search(None, f'(SINCE {since} TEXT "{utr}")')
        if status != "OK" or not data or not data[0]:
            return {"found": False, "reason": "no_email_with_utr"}

        # Newest first, check each
        ids = data[0].split()
        for eid in reversed(ids[-5:]):          # last 5 max
            st, md = mail.fetch(eid, "(RFC822)")
            if st != "OK" or not md: continue
            msg = email.message_from_bytes(md[0][1])
            body = clean_body(_extract_body(msg))

            # Verify this email is really a UPI credit
            if not CREDIT_HINT.search(body):
                continue

            # Extract amount
            am = AMOUNT_RE.search(body)
            if not am:
                continue
            amount_str = am.group(1).replace(",", "")
            try:
                amount_val = float(amount_str)
            except ValueError:
                continue

            # Extract sender name (best-effort)
            sender = "Unknown"
            sm = re.search(
                r"(?:from|sender|paid\s*by|received\s*from)\s*[:\-]?\s*"
                r"([A-Z][A-Za-z0-9 ._'-]{1,40}?)"
                r"(?=\s+(?:to|on|via|at|UTR|Ref)\b|[.,\n])",
                body, re.I
            )
            if sm:
                sender = sm.group(1).strip().title()

            return {
                "found": True,
                "amount": amount_str,
                "amount_value": amount_val,
                "sender": sender,
                "snippet": body[:300],
            }

        return {"found": False, "reason": "utr_found_but_not_credit"}

    except imaplib.IMAP4.error as e:
        log.exception("IMAP auth error")
        return {"found": False, "reason": f"imap_auth_failed: {e}"}
    except Exception as e:
        log.exception("IMAP failure")
        return {"found": False, "reason": f"imap_error: {e}"}
    finally:
        if mail:
            try: mail.logout()
            except Exception: pass


def verify_payment(utr: str, expected_amount: int, expected_note: str = "") -> dict:
    """
    Full verification:
      - UTR exists in a UPI credit email
      - amount >= expected_amount
      - (optional) note matches
    Returns: {"ok": bool, "reason": str, "detail": dict}
    """
    res = find_upi_credit(utr)
    if not res.get("found"):
        return {"ok": False, "reason": res.get("reason", "not_found"), "detail": {}}

    got = res["amount_value"]
    if got + 0.01 < float(expected_amount):
        return {
            "ok": False,
            "reason": f"amount_mismatch: got ₹{got}, expected ₹{expected_amount}",
            "detail": res,
        }

    if expected_note and expected_note.lower() not in res["snippet"].lower():
        return {
            "ok": False,
            "reason": f"note_mismatch: '{expected_note}' not in email",
            "detail": res,
        }

    return {"ok": True, "reason": "verified", "detail": res}