"""Send the daily digest over SMTP. Gmail app password works; so does anything else."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import settings


def configured():
    cfg = settings.EMAIL
    return bool(cfg.get("address") and cfg.get("password"))


def send(subject, text_body, html_body=None, to=None):
    cfg = settings.EMAIL
    if not configured():
        raise RuntimeError(
            "Email is not configured. Set RECRUIT_EMAIL_ADDRESS and "
            "RECRUIT_EMAIL_PASSWORD (a Gmail app password), or fill in EMAIL in recruit_config.py."
        )
    recipient = to or cfg.get("to") or cfg["address"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{cfg.get('display_name', 'Recruiting')} <{cfg['address']}>"
    msg["To"] = recipient
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"], timeout=60) as server:
        server.starttls()
        server.login(cfg["address"], cfg["password"])
        server.send_message(msg)
    return recipient
