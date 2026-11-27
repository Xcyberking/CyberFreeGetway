import imaplib, email, re, logging
from datetime import datetime, timedelta
from config import Config
from parser import clean_body

log = logging.getLogger(__name__)
IMAP_TIMEOUT = 20
SEARCH_DAYS  = 7
AMOUNT_RE    = re.compile(r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
CREDIT_HINT  = re.compile(
    r"(credited|received|deposited|received\s+from|money\s+received|"
    r"upi\s+credit|payment\s+received)", re.I)


def _extract_body(msg) -> str:
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct not in ("text/plain", "text/html"):
                continue
            try:
                cs = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True).decode(cs, errors="replace")
                if ct == "text/plain": plain += payload + " "
                else: html += payload + " "
            except Exception:
                continue
    else:
        try:
            cs = msg.get_content_charset() or "utf-8"
            plain = msg.get_payload(decode=True).decode(cs, errors="replace")
        except Exception:
            pass
    return plain if plain.strip() else html


def find_upi_credit(utr: str) -> dict:
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

        for eid in reversed(data[0].split()[-5:]):
            st, md = mail.fetch(eid, "(RFC822)")
            if st != "OK" or not md:
                continue
            msg = email.message_from_bytes(md[0][1])
            body = clean_body(_extract_body(msg))
            if not CREDIT_HINT.search(body):
                continue
            am = AMOUNT_RE.search(body)
            if not am:
                continue
            amount_str = am.group(1).replace(",", "")
            try:
                amount_val = float(amount_str)
            except ValueError:
                continue
            sm = re.search(
                r"(?:from|sender|paid\s*by|received\s*from)\s*[:\-]?\s*"
                r"([A-Z][A-Za-z0-9 ._'-]{1,40}?)"
                r"(?=\s+(?:to|on|via|at|UTR|Ref)\b|[.,\n])",
                body, re.I)
            sender = sm.group(1).strip().title() if sm else "Unknown"
            return {
                "found": True,
                "amount": amount_str,
                "amount_value": amount_val,
                "sender": sender,
                "snippet": body[:300],
            }
        return {"found": False, "reason": "utr_found_but_not_credit"}

    except imaplib.IMAP4.error as e:
        log.exception("IMAP auth")
        return {"found": False, "reason": f"imap_auth_failed: {e}"}
    except Exception as e:
        log.exception("IMAP fail")
        return {"found": False, "reason": f"imap_error: {e}"}
    finally:
        if mail:
            try: mail.logout()
            except Exception: pass


def verify_payment(utr: str, expected_amount: int, expected_note: str = "") -> dict:
    res = find_upi_credit(utr)
    if not res.get("found"):
        return {"ok": False, "reason": res.get("reason", "not_found"), "detail": {}}
    got = res["amount_value"]
    if got + 0.01 < float(expected_amount):
        return {"ok": False,
                "reason": f"amount_mismatch: got ₹{got}, expected ₹{expected_amount}",
                "detail": res}
    if expected_note and expected_note.lower() not in res["snippet"].lower():
        # soft check — amount+UTR already matched
        log.info("note mismatch but amount matched, allowing (note=%s)", expected_note)
    return {"ok": True, "reason": "verified", "detail": res}