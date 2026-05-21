from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import sendgrid
from dotenv import load_dotenv
from sendgrid.helpers.mail import Content, Email, Mail, Personalization


load_dotenv()

REQUESTS_DIR = Path(__file__).parent / "requests"
ALERT_THRESHOLD_SECONDS = 60


@dataclass
class RequestStatus:
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"


# Worker polling interval in seconds
WORKER_POLL_INTERVAL_SECONDS = 10


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_mail_settings() -> tuple[str, str, list[str]]:
    load_dotenv(override=True)
    devex_support_email = os.getenv("DEVEX_SUPPORT_EMAIL", "").strip()
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY", "").strip()
    admin_emails = [
        email.strip()
        for email in os.getenv("ACCESS_REQUEST_ADMIN_EMAILS", "").split(",")
        if email.strip()
    ]
    return devex_support_email, sendgrid_api_key, admin_emails


def is_mail_configured() -> bool:
    devex_support_email, sendgrid_api_key, admin_emails = get_mail_settings()
    return bool(devex_support_email and sendgrid_api_key and admin_emails)


def send_email(subject: str, body: str, recipients: list[str]) -> bool:
    devex_support_email, sendgrid_api_key, _ = get_mail_settings()

    if not recipients or not (devex_support_email and sendgrid_api_key):
        return False

    sanitized_body = body.replace('"', "").replace("'", "")

    try:
        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
        from_email = Email(devex_support_email)
        content = Content("text/plain", sanitized_body)
        mail = Mail(from_email=from_email, subject=subject, plain_text_content=content)
        personalization = Personalization()

        for recipient in recipients:
            personalization.add_to(Email(recipient))

        mail.add_personalization(personalization)
        response = sg.client.mail.send.post(request_body=mail.get())
        return response.status_code == 202
    except Exception:
        return False


def send_email_to_admin(email: str, app_name: str) -> bool:
    subject = "DevEx App Access Request"
    body = f"""
Dear Admin,
{email} has requested access to the {app_name} application.
Please review the request at your earliest convenience.

Thank you,
DevEx Team

!! This is an Automated email Please dont reply.
"""
    _, _, admin_emails = get_mail_settings()
    return send_email(subject, body, admin_emails)


def send_query_request_email(user_name: str, request_id: str, query_text: str) -> bool:
    subject = "QueryDesk Request Submitted"
    body = f"""
Dear Admin,
A new QueryDesk request has been submitted.

User Name: {user_name}
Request ID: {request_id}
Query:
{query_text}

Please review the request at your earliest convenience.

Thank you,
QueryDesk

!! This is an Automated email Please dont reply.
"""
    _, _, admin_emails = get_mail_settings()
    return send_email(subject, body, admin_emails)


def send_query_alert_email(user_id: str, request_id: str, user_name: str, started_at: str) -> bool:
    subject = "QueryDesk Alert: Request Pending Beyond 1 Minute"
    body = f"""
Dear Admin,
The following QueryDesk request is still pending after 1 minute.

User ID: {user_id}
User Name: {user_name}
Request ID: {request_id}
Started At: {started_at}

Please review the request immediately.

Thank you,
QueryDesk

!! This is an Automated email Please dont reply.
"""
    _, _, admin_emails = get_mail_settings()
    return send_email(subject, body, admin_emails)


def get_department_directories() -> list[Path]:
    if not REQUESTS_DIR.exists():
        return []

    return [path for path in REQUESTS_DIR.iterdir() if path.is_dir()]


def check_and_send_alerts() -> list[str]:
    now = datetime.now()
    alerted_requests: list[str] = []

    for department_dir in get_department_directories():
        for user_dir in department_dir.iterdir():
            if not user_dir.is_dir():
                continue

            tracking_path = user_dir / "tracking.json"
            entries = read_json(tracking_path, [])

            if not isinstance(entries, list):
                continue

            updated = False

            for entry in entries:
                if entry.get("status") != RequestStatus.IN_PROGRESS:
                    continue

                if entry.get("alert_mail_sent"):
                    continue

                start_timestamp = parse_timestamp(
                    entry.get("start_timestamp")
                    or entry.get("initial_timestamp")
                    or entry.get("latest_submission_timestamp")
                    or entry.get("submission_timestamp")
                )
                if start_timestamp is None:
                    continue

                if now <= start_timestamp + timedelta(seconds=ALERT_THRESHOLD_SECONDS):
                    continue

                request_id = str(entry.get("query_id", ""))
                user_name = str(entry.get("name", "Unknown"))
                if send_query_alert_email(
                    user_id=user_dir.name,
                    request_id=request_id,
                    user_name=user_name,
                    started_at=start_timestamp.isoformat(timespec="seconds"),
                ):
                    entry["alert_mail_sent"] = True
                    entry["alert_mail_sent_at"] = now.isoformat(timespec="seconds")
                    alerted_requests.append(request_id)
                    updated = True

            if updated:
                tracking_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    return alerted_requests


def process_new_request_notifications() -> list[str]:
    notified_requests: list[str] = []

    for department_dir in get_department_directories():
        for user_dir in department_dir.iterdir():
            if not user_dir.is_dir():
                continue

            tracking_path = user_dir / "tracking.json"
            entries = read_json(tracking_path, [])

            if not isinstance(entries, list):
                continue

            updated = False

            for entry in entries:
                if entry.get("request_mail_sent"):
                    continue

                request_id = str(entry.get("query_id", ""))
                user_name = str(entry.get("name", "Unknown"))

                request_payload = read_json(user_dir / f"{request_id}.json", {})
                query_items = request_payload.get("query", []) if isinstance(request_payload, dict) else []
                query_text = query_items[0] if query_items else "No query text available."

                if send_query_request_email(user_name, request_id, query_text):
                    entry["request_mail_sent"] = True
                    entry["request_mail_sent_at"] = datetime.now().isoformat(timespec="seconds")
                    notified_requests.append(request_id)
                    updated = True

            if updated:
                tracking_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    return notified_requests


def run_worker() -> None:
    import time

    print("Starting QueryDesk mail worker...")
    while True:
        new_request_ids = process_new_request_notifications()
        alert_request_ids = check_and_send_alerts()

        if new_request_ids:
            print(f"Sent new request mail for: {new_request_ids}")

        if alert_request_ids:
            print(f"Sent alert mail for: {alert_request_ids}")

        time.sleep(WORKER_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_worker()