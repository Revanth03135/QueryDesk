from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


REQUESTS_DIR = Path(__file__).parent / "requests"
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
    initial_timestamp: str
    submission_timestamp: str
    completion_timestamp: str | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "query": self.query,
            "response": self.response,
            "initial_timestamp": self.initial_timestamp,
            "submission_timestamp": self.submission_timestamp,
            "completion_timestamp": self.completion_timestamp,
            "status": self.status,
        }


def ensure_user_directory(user_id: str) -> Path:
    user_dir = REQUESTS_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    tracking_file = user_dir / "tracking.json"
    if not tracking_file.exists():
        tracking_file.write_text("[]", encoding="utf-8")

    return user_dir


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

    # Sort tracking entries by timestamp (latest first)
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


def load_request(user_id: str, request_id: str) -> QueryRecord | None:
    payload = read_json_file(request_file_path(user_id, request_id), default=None)
    if not isinstance(payload, dict):
        return None

    submission_timestamp = payload.get("submission_timestamp", "")
    initial_timestamp = payload.get("initial_timestamp", submission_timestamp)

    return QueryRecord(
        request_id=request_id,
        name=payload.get("name", ""),
        query=payload.get("query", []),
        response=payload.get("response", []),
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


def create_new_request(user_id: str, name: str, initial_query: str) -> str:
    request_id = str(uuid.uuid4())
    timestamp = generate_timestamp()
    record = QueryRecord(
        request_id=request_id,
        name=name.strip(),
        query=[initial_query.strip()],
        response=[],
        initial_timestamp=timestamp,
        submission_timestamp=timestamp,
        completion_timestamp=None,
        status=RequestStatus.IN_PROGRESS,
    )
    save_request(record, user_id)
    return request_id


def append_query_to_request(user_id: str, request_id: str, new_query: str) -> None:
    record = load_request(user_id, request_id)
    if record is None:
        raise FileNotFoundError(f"Query request '{request_id}' does not exist.")

    clean_query = new_query.strip()
    if not clean_query:
        return

    record.query.append(clean_query)
    record.submission_timestamp = generate_timestamp()
    if record.status == RequestStatus.COMPLETED:
        record.status = RequestStatus.IN_PROGRESS

    record.completion_timestamp = None
    save_request(record, user_id)


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
        submitted = st.form_submit_button("Submit Query")

    if submitted:
        if not name.strip():
            st.error("Name is required.")
            return
        if not initial_query.strip():
            st.error("Query is required.")
            return

        request_id = create_new_request(user_id, name, initial_query)
        select_request(request_id)
        st.success("Query submitted successfully.")
        st.rerun()


def render_chat_history(record: QueryRecord) -> None:
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

        if index < len(record.response):
            with st.chat_message("assistant"):
                st.markdown(record.response[index])

    if not record.response:
        st.info("No admin responses yet.")


def render_requery_box(user_id: str, record: QueryRecord) -> None:
    requery = st.chat_input("Requery under the same request")
    if requery and requery.strip():
        append_query_to_request(user_id, record.request_id, requery)
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

    render_chat_history(record)
    render_requery_box(user_id, record)


if __name__ == "__main__":
    main()