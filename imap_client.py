import imaplib, email, email.utils, socket, logging
from datetime import datetime, timedelta
from config import Config
from parser import parse_transaction

log = logging.getLogger(__name__)
IMAP_TIMEOUT = 20
SEARCH_DAYS  = 30
MAX_EMAILS   = 5


def extract_body(msg) -> str:
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"): continue
            try:
                cs = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True).decode(cs, errors="replace")
                if ctype == "text/plain": plain += payload + " "
                else: html += payload + " "
            except Exception: continue
    else:
        try:
            cs = msg.get_content_charset() or "utf-8"
            plain = msg.get_payload(decode=True).decode(cs, errors="replace")
        except Exception: pass
    return plain if plain.strip() else html


def search_gmail(query_id: str) -> dict:
    if not Config.EMAIL_ADDRESS or not Config.EMAIL_APP_PASS:
        return {"error": "Email not configured", "found": False}

    mail = None
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=IMAP_TIMEOUT)
        mail.login(Config.EMAIL_ADDRESS, Config.EMAIL_APP_PASS)
        mail.select("INBOX", readonly=True)
        since = (datetime.now() - timedelta(days=SEARCH_DAYS)).strftime("%d-%b-%Y")
        status, data = mail.search(None, f'(SINCE {since} TEXT "{query_id}")')
        if status != "OK" or not data or not data[0]:
            return {"query": query_id, "found": False, "results": []}

        ids = data[0].split()[-MAX_EMAILS:]
        results = []
        for eid in reversed(ids):
            st, md = mail.fetch(eid, "(RFC822)")
            if st != "OK" or not md: continue
            msg = email.message_from_bytes(md[0][1])
            try: dt = email.utils.parsedate_to_datetime(msg.get("Date",""))
            except Exception: dt = datetime.now()
            results.append(parse_transaction(extract_body(msg), dt))
        return {"query": query_id, "found": bool(results), "results": results}
    except Exception as e:
        log.exception("imap fail")
        return {"error": str(e), "found": False}
    finally:
        if mail:
            try: mail.logout()
            except Exception: pass