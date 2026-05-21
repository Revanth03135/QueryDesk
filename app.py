from __future__ import annotations

import base64
import json
import mimetypes
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st


REQUESTS_DIR = Path(__file__).parent / "requests"
DEPARTMENT = "Marketing"
MOCK_USER_ID = "mock_user_002"


class RequestStatus:
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    VALUES = {IN_PROGRESS, COMPLETED}


@dataclass
class QueryRecord:
    request_id: str
    name: str
    query: list[str]
    response: list[str]
    user_attachments: list[list[dict[str, Any]]]
    initial_timestamp: str
    submission_timestamp: str
    completion_timestamp: str | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "query": self.query,
            "response": self.response,
            "user_attachments": self.user_attachments,
            "initial_timestamp": self.initial_timestamp,
            "submission_timestamp": self.submission_timestamp,
            "completion_timestamp": self.completion_timestamp,
            "status": self.status,
        }


def get_department_directory() -> Path:
    department_dir = REQUESTS_DIR / DEPARTMENT
    department_dir.mkdir(parents=True, exist_ok=True)
    return department_dir


def ensure_user_directory(user_id: str) -> Path:
    user_dir = get_department_directory() / user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    tracking_file = user_dir / "tracking.json"
    if not tracking_file.exists():
        tracking_file.write_text("[]", encoding="utf-8")

    return user_dir


def ensure_request_attachment_directory(user_id: str, request_id: str) -> Path:
    attachment_dir = ensure_user_directory(user_id) / request_id
    attachment_dir.mkdir(parents=True, exist_ok=True)
    return attachment_dir


def read_json_file(file_path: Path, default: Any) -> Any:
    if not file_path.exists():
        return default

    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json_file(file_path: Path, payload: Any) -> None:
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_tracking_entries(user_id: str) -> list[dict[str, Any]]:
    user_dir = ensure_user_directory(user_id)
    tracking_file = user_dir / "tracking.json"
    data = read_json_file(tracking_file, default=[])
    return data if isinstance(data, list) else []


def update_tracking_entry(
    user_id: str,
    request_id: str,
    name: str,
    latest_submission_timestamp: str,
    status: str,
) -> None:
    user_dir = ensure_user_directory(user_id)
    tracking_file = user_dir / "tracking.json"
    entries = load_tracking_entries(user_id)

    updated = False
    for entry in entries:
        if entry.get("query_id") == request_id:
            entry["name"] = name
            entry["latest_submission_timestamp"] = latest_submission_timestamp
            entry["status"] = status
            updated = True
            break

    if not updated:
        entries.append(
            {
                "query_id": request_id,
                "name": name,
                "latest_submission_timestamp": latest_submission_timestamp,
                "status": status,
            }
        )

    try:
        entries.sort(
            key=lambda x: x.get("latest_submission_timestamp", ""),
            reverse=True,
        )
    except Exception:
        pass

    write_json_file(tracking_file, entries)


def request_file_path(user_id: str, request_id: str) -> Path:
    user_dir = ensure_user_directory(user_id)
    return user_dir / f"{request_id}.json"


def normalize_attachment_groups(
    attachments: list[Any],
    query_count: int,
) -> list[list[dict[str, Any]]]:
    normalized: list[list[dict[str, Any]]] = []

    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, list):
                normalized.append([entry for entry in item if isinstance(entry, dict)])
            elif isinstance(item, dict):
                normalized.append([item])
            else:
                normalized.append([])

    while len(normalized) < query_count:
        normalized.append([])

    return normalized[:query_count]


def load_request(user_id: str, request_id: str) -> QueryRecord | None:
    payload = read_json_file(request_file_path(user_id, request_id), default=None)
    if not isinstance(payload, dict):
        return None

    query_items = payload.get("query", [])
    query_list = query_items if isinstance(query_items, list) else []
    submission_timestamp = payload.get("submission_timestamp", "")
    initial_timestamp = payload.get("initial_timestamp", submission_timestamp)

    return QueryRecord(
        request_id=request_id,
        name=payload.get("name", ""),
        query=query_list,
        response=payload.get("response", []),
        user_attachments=normalize_attachment_groups(
            payload.get("user_attachments", []),
            len(query_list),
        ),
        initial_timestamp=initial_timestamp,
        submission_timestamp=submission_timestamp,
        completion_timestamp=payload.get("completion_timestamp"),
        status=payload.get("status", RequestStatus.IN_PROGRESS),
    )


def save_request(record: QueryRecord, user_id: str) -> None:
    file_path = request_file_path(user_id, record.request_id)
    write_json_file(file_path, record.to_dict())
    update_tracking_entry(
        user_id=user_id,
        request_id=record.request_id,
        name=record.name,
        latest_submission_timestamp=record.submission_timestamp,
        status=record.status,
    )


def generate_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_attachment_metadata(
    user_id: str,
    request_id: str,
    uploaded_files: list[Any] | None,
) -> list[dict[str, Any]]:
    if not uploaded_files:
        return []

    attachment_dir = ensure_request_attachment_directory(user_id, request_id)
    attachments: list[dict[str, Any]] = []

    for uploaded_file in uploaded_files:
        if uploaded_file is None:
            continue

        original_name = Path(uploaded_file.name).name or "attachment"
        stored_name = f"{uuid.uuid4().hex}_{original_name}"
        file_path = attachment_dir / stored_name
        file_bytes = uploaded_file.getvalue()
        file_path.write_bytes(file_bytes)

        mime_type = uploaded_file.type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"

        attachments.append(
            {
                "file_name": original_name,
                "stored_name": stored_name,
                "relative_path": str(Path(request_id) / stored_name).replace("\\", "/"),
                "mime_type": mime_type,
                "size_bytes": len(file_bytes),
                "uploaded_at": generate_timestamp(),
            }
        )

    return attachments


def create_new_request(
    user_id: str,
    name: str,
    initial_query: str,
    uploaded_files: list[Any] | None = None,
) -> str:
    request_id = str(uuid.uuid4())
    timestamp = generate_timestamp()
    record = QueryRecord(
        request_id=request_id,
        name=name.strip(),
        query=[initial_query.strip()],
        response=[],
        user_attachments=[build_attachment_metadata(user_id, request_id, uploaded_files)],
        initial_timestamp=timestamp,
        submission_timestamp=timestamp,
        completion_timestamp=None,
        status=RequestStatus.IN_PROGRESS,
    )
    save_request(record, user_id)
    return request_id


def append_query_to_request(
    user_id: str,
    request_id: str,
    new_query: str,
    uploaded_files: list[Any] | None = None,
) -> None:
    record = load_request(user_id, request_id)
    if record is None:
        raise FileNotFoundError(f"Query request '{request_id}' does not exist.")

    clean_query = new_query.strip()
    if not clean_query:
        return

    record.query.append(clean_query)
    record.user_attachments.append(
        build_attachment_metadata(user_id, request_id, uploaded_files)
    )
    record.submission_timestamp = generate_timestamp()
    if record.status == RequestStatus.COMPLETED:
        record.status = RequestStatus.IN_PROGRESS

    record.completion_timestamp = None
    save_request(record, user_id)


def format_file_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)

    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024

    return f"{int(size_bytes)} B"


def get_attachment_bytes(user_id: str, attachment: dict[str, Any]) -> bytes:
    relative_path = attachment.get("relative_path", "")
    if not relative_path:
        return b""

    attachment_path = ensure_user_directory(user_id) / relative_path
    if attachment_path.exists():
        return attachment_path.read_bytes()

    return b""


def build_pdf_data_url(file_bytes: bytes) -> str:
    encoded = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:application/pdf;base64,{encoded}"


def build_image_data_url(file_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def can_user_requery(record: QueryRecord) -> bool:
    return len(record.query) == 0 or len(record.response) >= len(record.query)


def make_dom_id(value: str) -> str:
    safe_value = re.sub(r"[^a-zA-Z0-9_-]", "-", value)
    return safe_value.strip("-") or "image-preview"


def render_clickable_image_preview(image_url: str, file_name: str, popup_key: str) -> None:
    modal_id = make_dom_id(f"{popup_key}_modal")
    safe_name = escape(file_name, quote=True)

    st.markdown(
        f"""
        <div style="margin: 0.25rem 0 0.5rem 0;">
            <style>
                .image-thumb-{modal_id} {{
                    width: 180px;
                    max-width: 100%;
                    height: auto;
                    border-radius: 10px;
                    border: 1px solid #d9d9d9;
                    object-fit: cover;
                    display: block;
                    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
                    cursor: zoom-in;
                    transition: transform 0.2s ease, box-shadow 0.2s ease;
                }}
                .image-thumb-{modal_id}:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.16);
                }}
                .image-modal-{modal_id} {{
                    position: fixed;
                    top: 4.75rem;
                    right: 1.25rem;
                    bottom: 1.25rem;
                    left: 22rem;
                    background: rgba(0, 0, 0, 0.78);
                    display: none;
                    align-items: center;
                    justify-content: center;
                    padding: 1.5rem;
                    box-sizing: border-box;
                    border-radius: 18px;
                    overflow: auto;
                    z-index: 998;
                }}
                .image-modal-{modal_id}:target {{
                    display: flex;
                }}
                .image-modal-content-{modal_id} {{
                    position: relative;
                    max-width: min(100%, 1100px);
                    max-height: 100%;
                    width: fit-content;
                    margin: auto;
                }}
                .image-modal-content-{modal_id} img {{
                    max-width: 100%;
                    max-height: calc(100vh - 10rem);
                    width: auto;
                    height: auto;
                    border-radius: 16px;
                    border: 1px solid rgba(255, 255, 255, 0.18);
                    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.32);
                    display: block;
                    background: #fff;
                }}
                .image-modal-close-{modal_id} {{
                    position: absolute;
                    top: -0.75rem;
                    right: -0.75rem;
                    width: 2.25rem;
                    height: 2.25rem;
                    border-radius: 999px;
                    background: #fff;
                    color: #111827;
                    text-decoration: none;
                    font-size: 1.4rem;
                    font-weight: 700;
                    line-height: 2.15rem;
                    text-align: center;
                    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.22);
                }}
                .image-modal-caption-{modal_id} {{
                    margin-top: 0.75rem;
                    color: #f9fafb;
                    text-align: center;
                    font-size: 0.95rem;
                }}
                .image-preview-hint-{modal_id} {{
                    margin-top: 0.35rem;
                    color: #6b7280;
                    font-size: 0.85rem;
                }}
                @media (max-width: 991px) {{
                    .image-modal-{modal_id} {{
                        top: 4.5rem;
                        right: 0.75rem;
                        bottom: 0.75rem;
                        left: 0.75rem;
                        padding: 1rem;
                    }}
                    .image-modal-content-{modal_id} img {{
                        max-height: calc(100vh - 8rem);
                    }}
                }}
            </style>
            <a href="#{modal_id}" style="text-decoration: none;">
                <img
                    src="{image_url}"
                    alt="{safe_name}"
                    title="Click to open a larger preview"
                    class="image-thumb-{modal_id}"
                />
            </a>
            <div class="image-preview-hint-{modal_id}">Click the image to open a larger preview.</div>
            <div id="{modal_id}" class="image-modal-{modal_id}">
                <a
                    href="#"
                    style="position: absolute; inset: 0;"
                    aria-label="Close image preview"
                ></a>
                <div class="image-modal-content-{modal_id}">
                    <a href="#" class="image-modal-close-{modal_id}" aria-label="Close preview">&times;</a>
                    <img src="{image_url}" alt="{safe_name}" />
                    <div class="image-modal-caption-{modal_id}">{safe_name}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_attachments(
    user_id: str,
    attachments: list[dict[str, Any]],
    prefix: str,
) -> None:
    if not attachments:
        return

    st.markdown("**Attachments**")
    for index, attachment in enumerate(attachments):
        file_name = attachment.get("file_name", "attachment")
        size_label = format_file_size(attachment.get("size_bytes"))
        mime_type = (attachment.get("mime_type") or "application/octet-stream").lower()
        file_bytes = get_attachment_bytes(user_id, attachment)

        if not file_bytes:
            st.caption(f"{file_name} ({size_label}) - file not found")
            continue

        if mime_type.startswith("image/"):
            image_url = build_image_data_url(file_bytes, mime_type)
            render_clickable_image_preview(
                image_url,
                file_name,
                f"{prefix}_image_{index}",
            )

        if mime_type == "application/pdf":
            pdf_url = build_pdf_data_url(file_bytes)
            st.markdown(
                f'<a href="{pdf_url}" target="_blank" rel="noopener noreferrer">Open PDF: {file_name}</a>',
                unsafe_allow_html=True,
            )

        st.download_button(
            label=f"Download {file_name} ({size_label})",
            data=file_bytes,
            file_name=file_name,
            mime=mime_type,
            key=f"{prefix}_attachment_{index}_{attachment.get('stored_name', file_name)}",
            use_container_width=True,
        )


def initialise_state() -> None:
    if "user_id" not in st.session_state:
        st.session_state.user_id = MOCK_USER_ID

    if "selected_request_id" not in st.session_state:
        st.session_state.selected_request_id = None

    if "creating_new_query" not in st.session_state:
        st.session_state.creating_new_query = True


def select_request(request_id: str) -> None:
    st.session_state.selected_request_id = request_id
    st.session_state.creating_new_query = False


def start_new_query() -> None:
    st.session_state.selected_request_id = None
    st.session_state.creating_new_query = True


def render_sidebar(tracking_entries: list[dict[str, Any]]) -> None:
    st.sidebar.title("User Queries")
    st.sidebar.caption(f"User ID: {st.session_state.user_id}")

    if tracking_entries:
        for entry in reversed(tracking_entries):
            request_id = entry.get("query_id", "unknown")
            label = f"{entry.get('name', 'Unnamed')} · {entry.get('status', RequestStatus.IN_PROGRESS)}"
            if st.sidebar.button(label, key=f"sidebar_{request_id}", use_container_width=True):
                select_request(request_id)
    else:
        st.sidebar.info("No queries submitted yet.")

    st.sidebar.divider()
    st.sidebar.button(
        "Create New Query",
        key="create_new_query",
        on_click=start_new_query,
        use_container_width=True,
    )


def render_new_query_form(user_id: str) -> None:
    st.subheader("Create a new query")

    with st.form("new_query_form", clear_on_submit=True):
        name = st.text_input("Name")
        initial_query = st.text_area("Query", height=140)
        attachments = st.file_uploader(
            "Attach files",
            accept_multiple_files=True,
            key="new_query_attachments",
        )
        submitted = st.form_submit_button("Submit Query")

    if submitted:
        if not name.strip():
            st.error("Name is required.")
            return
        if not initial_query.strip():
            st.error("Query is required.")
            return

        request_id = create_new_request(user_id, name, initial_query, attachments)
        select_request(request_id)
        st.success("Query submitted successfully.")
        st.rerun()


def render_chat_history(record: QueryRecord, user_id: str) -> None:
    st.subheader(f"Query Thread: {record.name}")
    st.caption(
        f"Request ID: {record.request_id} | Submitted: {record.submission_timestamp} | "
        f"Status: {record.status}"
    )

    max_len = max(len(record.query), len(record.response))
    for index in range(max_len):
        if index < len(record.query):
            with st.chat_message("user"):
                st.markdown(record.query[index])
                attachments = record.user_attachments[index] if index < len(record.user_attachments) else []
                render_attachments(user_id, attachments, prefix=f"user_query_{record.request_id}_{index}")

        if index < len(record.response):
            with st.chat_message("assistant"):
                st.markdown(record.response[index])

    if not record.response:
        st.info("No admin responses yet.")


def render_requery_box(user_id: str, record: QueryRecord) -> None:
    st.markdown("---")
    st.subheader("Requery")

    if not can_user_requery(record):
        st.info("You can send the next message after the admin replies to your latest query.")
        return

    with st.form(f"requery_form_{record.request_id}", clear_on_submit=True):
        requery = st.text_area("Requery under the same request", height=120)
        attachments = st.file_uploader(
            "Attach files",
            accept_multiple_files=True,
            key=f"requery_attachments_{record.request_id}",
        )
        submitted = st.form_submit_button("Send Requery")

    if submitted:
        if not requery.strip() and not attachments:
            st.error("Enter a requery message or attach at least one file.")
            return

        append_query_to_request(user_id, record.request_id, requery or "[Attachment uploaded]", attachments)
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="QueryDesk", layout="wide")
    initialise_state()

    user_id = st.session_state.user_id
    tracking_entries = load_tracking_entries(user_id)
    render_sidebar(tracking_entries)

    st.title("QueryDesk")

    if st.session_state.creating_new_query or not st.session_state.selected_request_id:
        render_new_query_form(user_id)
        return

    record = load_request(user_id, st.session_state.selected_request_id)
    if record is None:
        st.warning("Selected request could not be found.")
        start_new_query()
        st.rerun()
        return

    render_chat_history(record, user_id)
    render_requery_box(user_id, record)


if __name__ == "__main__":
    main()
