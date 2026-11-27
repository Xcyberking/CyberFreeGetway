import re
from datetime import datetime

AMOUNT_RE = re.compile(r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
UTR_RE    = re.compile(r"(?:UTR|UPI\s*Ref(?:\s*No)?|Ref(?:erence)?\s*(?:No|#)?)"
                       r"\s*[:#]?\s*([0-9]{10,})", re.I)
TXN_RE    = re.compile(r"(?:Transaction|Txn|Fampay)\s*(?:ID|No|#)?\s*[:#]?\s*"
                       r"([A-Z0-9]{6,})", re.I)
NAME_RE   = re.compile(r"(?:from|Paid\s*by|Sender)\s*[:\-]?\s*"
                       r"([A-Z][A-Za-z0-9 ._'-]{1,40}?)"
                       r"(?=\s+(?:to|on|via|at|for|UTR|Ref|has|sent|paid)\b|[.,\n])",
                       re.I)
FAIL_RE   = re.compile(r"\b(fail(?:ed|ure)?|declin(?:ed|e)|unsuccessful|"
                       r"reversed|cancel(?:l?ed)?|refund(?:ed)?)\b", re.I)


def clean_body(text: str) -> str:
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'"))
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_transaction(body: str, date_obj: datetime) -> dict:
    text = clean_body(body)

    m = AMOUNT_RE.search(text)
    amount = m.group(1).replace(",", "") if m else "0.0"

    m = UTR_RE.search(text)
    utr = m.group(1) if m else ""
    if not utr:
        m = re.search(r"\b(\d{12})\b", text)
        utr = m.group(1) if m else ""

    m = TXN_RE.search(text)
    txn = m.group(1) if m else ""

    m = NAME_RE.search(text)
    sender = m.group(1).strip().title() if m else "Unknown"

    status = "Failed" if FAIL_RE.search(text) else "Success"

    return {
        "date":    date_obj.strftime("%d %b %Y %H:%M:%S") if date_obj else "",
        "time":    date_obj.strftime("%I:%M %p") if date_obj else "",
        "money":   amount,
        "name":    sender,
        "txn_id":  txn,
        "utr":     utr,
        "payment": status,
        "raw_snippet": text[:200],
    }