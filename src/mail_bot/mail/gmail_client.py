import asyncio
import base64
import json
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


@dataclass(frozen=True)
class MailAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class MailMessage:
    id: str
    thread_id: str
    sender: str
    subject: str
    received_at: str
    body: str
    attachments: tuple[MailAttachment, ...]
    gmail_url: str


class GmailClient:
    def __init__(self, client_secrets_file: str, redirect_uri: str, max_attachment_bytes: int):
        self.client_secrets_file = client_secrets_file
        self.redirect_uri = redirect_uri
        self.max_attachment_bytes = max_attachment_bytes

    def authorization_url(self, state: str) -> tuple[str, str]:
        flow = Flow.from_client_secrets_file(self.client_secrets_file, scopes=SCOPES, state=state)
        flow.redirect_uri = self.redirect_uri
        url, _ = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
        return url, flow.code_verifier

    def exchange_code(self, code: str, state: str, code_verifier: str) -> tuple[str, str, str]:
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=SCOPES,
            state=state,
            code_verifier=code_verifier,
        )
        flow.redirect_uri = self.redirect_uri
        flow.fetch_token(code=code)
        credentials = flow.credentials
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        return profile["emailAddress"], profile["historyId"], credentials.to_json()

    def _service(self, refresh_token: str):
        secrets = json.loads(Path(self.client_secrets_file).read_text(encoding="utf-8"))
        client = secrets.get("installed") or secrets.get("web")
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=client["token_uri"],
            client_id=client["client_id"],
            client_secret=client["client_secret"],
            scopes=SCOPES,
        )
        if not credentials.valid:
            credentials.refresh(Request())
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    async def list_messages(self, refresh_token: str, after_history_id: str | None) -> tuple[list[MailMessage], str]:
        return await asyncio.to_thread(self._list_messages, refresh_token, after_history_id)

    def _list_messages(self, refresh_token: str, after_history_id: str | None) -> tuple[list[MailMessage], str]:
        service = self._service(refresh_token)
        profile = service.users().getProfile(userId="me").execute()
        query = "in:inbox -label:spam"
        if after_history_id:
            response = service.users().history().list(
                userId="me", startHistoryId=after_history_id, historyTypes=["messageAdded"]
            ).execute()
            message_ids = {
                item["message"]["id"]
                for history in response.get("history", [])
                for item in history.get("messagesAdded", [])
            }
        else:
            response = service.users().messages().list(userId="me", q=query, maxResults=25).execute()
            message_ids = {item["id"] for item in response.get("messages", [])}
        messages = [self._get_message(service, message_id) for message_id in message_ids]
        return [message for message in messages if message], profile["historyId"]

    def _get_message(self, service, message_id: str) -> MailMessage | None:
        raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {header["name"].lower(): header["value"] for header in raw.get("payload", {}).get("headers", [])}
        body, attachments = self._parts(service, message_id, raw.get("payload", {}))
        received = headers.get("date", "")
        try:
            received = parsedate_to_datetime(received).isoformat()
        except (TypeError, ValueError):
            pass
        return MailMessage(
            id=message_id,
            thread_id=raw.get("threadId", ""),
            sender=headers.get("from", "unknown sender"),
            subject=headers.get("subject", "(no subject)"),
            received_at=received,
            body=body[:12000],
            attachments=tuple(attachments),
            gmail_url=f"https://mail.google.com/mail/u/0/#inbox/{message_id}",
        )

    def _parts(self, service, message_id: str, payload: dict) -> tuple[str, list[MailAttachment]]:
        body = ""
        attachments: list[MailAttachment] = []
        stack = [payload]
        while stack:
            part = stack.pop()
            filename = part.get("filename") or ""
            data = part.get("body", {}).get("data")
            if filename and data:
                decoded = base64.urlsafe_b64decode(data)
                if len(decoded) <= self.max_attachment_bytes:
                    attachments.append(MailAttachment(filename, part.get("mimeType", "application/octet-stream"), decoded))
            if part.get("mimeType") == "text/plain" and data and not body:
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            stack.extend(part.get("parts", []))
        if not body:
            body = "(no plain-text body; open the Gmail link to read this message)"
        return body, attachments

    async def modify(self, refresh_token: str, message_id: str, action: str) -> None:
        await asyncio.to_thread(self._modify, refresh_token, message_id, action)

    def _modify(self, refresh_token: str, message_id: str, action: str) -> None:
        service = self._service(refresh_token)
        body = {"addLabelIds": [], "removeLabelIds": []}
        if action == "read":
            body["removeLabelIds"].append("UNREAD")
        elif action == "star":
            body["addLabelIds"].append("STARRED")
        elif action == "trash":
            service.users().messages().trash(userId="me", id=message_id).execute()
            return
        else:
            raise ValueError(f"Unsupported Gmail action: {action}")
        service.users().messages().modify(userId="me", id=message_id, body=body).execute()
