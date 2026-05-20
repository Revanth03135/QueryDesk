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
    submission_timestamp: str
    completion_timestamp: str | None
    status: str
    updated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "query": self.query,
            "response": self.response,
            "submission_timestamp": self.submission_timestamp,
            "completion_timestamp": self.completion_timestamp,
            "status": self.status,
            "updated": self.updated,
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


def write_tracking_entries(user_id: str, entries: list[dict[str, Any]]):
    tracking_file = ensure_user_directory(user_id) / "tracking.json"

    entries.sort(key=lambda x: x.get("submission_timestamp", ""), reverse=True)
    write_json_file(tracking_file, entries)


def update_tracking_entry(user_id: str, request_id: str, payload: dict):
    entries = load_tracking_entries(user_id)

    updated = False
    for entry in entries:
        if entry["query_id"] == request_id:
            entry.update(payload)
            updated = True
            break

    if not updated:
        payload["query_id"] = request_id
        entries.append(payload)

    write_tracking_entries(user_id, entries)


def delete_tracking_entry(user_id: str, request_id: str):
    entries = load_tracking_entries(user_id)
    entries = [e for e in entries if e.get("query_id") != request_id]
    write_tracking_entries(user_id, entries)


def request_file_path(user_id: str, request_id: str) -> Path:
    return ensure_user_directory(user_id) / f"{request_id}.json"


def load_request(user_id: str, request_id: str) -> QueryRecord | None:
    payload = read_json_file(request_file_path(user_id, request_id), None)
    if not isinstance(payload, dict):
        return None

    return QueryRecord(
        request_id=request_id,
        name=payload.get("name", ""),
        query=payload.get("query", []),
        response=payload.get("response", []),
        submission_timestamp=payload.get("submission_timestamp", ""),
        completion_timestamp=payload.get("completion_timestamp"),
        status=payload.get("status", RequestStatus.IN_PROGRESS),
        updated=payload.get("updated", False),
    )


def save_request(record: QueryRecord, user_id: str):
    write_json_file(request_file_path(user_id, record.request_id), record.to_dict())

    update_tracking_entry(
        user_id,
        record.request_id,
        {
            "name": record.name,
            "submission_timestamp": record.submission_timestamp,
            "status": record.status,
            "updated": record.updated,
        },
    )


def generate_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_new_request(user_id: str, name: str, query: str) -> str:
    request_id = str(uuid.uuid4())
    timestamp = generate_timestamp()

    record = QueryRecord(
        request_id=request_id,
        name=name,
        query=[query],
        response=[],
        submission_timestamp=timestamp,
        completion_timestamp=None,
        status=RequestStatus.IN_PROGRESS,
        updated=False,
    )

    save_request(record, user_id)
    return request_id


def append_query(user_id: str, request_id: str, text: str):
    record = load_request(user_id, request_id)
    if not record:
        return

    record.query.append(text)
    record.updated = True
    save_request(record, user_id)


def update_query(user_id: str, request_id: str, index: int, new_text: str):
    record = load_request(user_id, request_id)
    if not record:
        return

    if index < 0 or index >= len(record.query):
        return

    record.query[index] = new_text
    record.updated = True
    save_request(record, user_id)


def delete_query(user_id: str, request_id: str, index: int):
    record = load_request(user_id, request_id)
    if not record:
        return

    if index < 0 or index >= len(record.query):
        return

    record.query.pop(index)

    # keep responses aligned if needed
    if index < len(record.response):
        record.response.pop(index)

    record.updated = True
    save_request(record, user_id)


def delete_request(user_id: str, request_id: str):
    file_path = request_file_path(user_id, request_id)
    if file_path.exists():
        file_path.unlink()

    delete_tracking_entry(user_id, request_id)


def initialise_state():
    if "user_id" not in st.session_state:
        st.session_state.user_id = MOCK_USER_ID

    if "selected_request_id" not in st.session_state:
        st.session_state.selected_request_id = None

    if "creating_new_query" not in st.session_state:
        st.session_state.creating_new_query = True


def render_sidebar(entries):
    st.sidebar.title("User Queries")

    for e in entries:
        label = f"{e.get('name')} · {e.get('status')}"
        if e.get("updated"):
            label += " ⚠ updated"

        if st.sidebar.button(label, key=e["query_id"]):
            st.session_state.selected_request_id = e["query_id"]
            st.session_state.creating_new_query = False

    st.sidebar.divider()

    if st.sidebar.button("New Query"):
        st.session_state.creating_new_query = True
        st.session_state.selected_request_id = None


def render_new_query(user_id):
    st.subheader("Create new request")

    name = st.text_input("Name")
    query = st.text_area("Query")

    if st.button("Submit"):
        if name and query:
            rid = create_new_request(user_id, name, query)
            st.session_state.selected_request_id = rid
            st.session_state.creating_new_query = False
            st.rerun()


def render_chat(record: QueryRecord, user_id: str):
    max_len = max(len(record.query), len(record.response))

    for i in range(max_len):
        if i < len(record.query):
            with st.chat_message("user"):
                st.write(record.query[i])

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("Edit", key=f"edit_{i}"):
                        st.session_state[f"edit_mode_{i}"] = True

                with col2:
                    if st.button("Delete", key=f"delete_{i}"):
                        delete_query(user_id, record.request_id, i)
                        st.rerun()

                if st.session_state.get(f"edit_mode_{i}", False):
                    new_text = st.text_input("Update query", key=f"edit_input_{i}")
                    if st.button("Save", key=f"save_{i}"):
                        update_query(user_id, record.request_id, i, new_text)
                        st.session_state[f"edit_mode_{i}"] = False
                        st.rerun()

        if i < len(record.response):
            with st.chat_message("assistant"):
                st.write(record.response[i])


def main():
    st.set_page_config(page_title="QueryDesk", layout="wide")

    initialise_state()
    user_id = st.session_state.user_id

    tracking = load_tracking_entries(user_id)
    render_sidebar(tracking)

    st.title("QueryDesk")

    if st.session_state.creating_new_query:
        render_new_query(user_id)
        return

    rid = st.session_state.selected_request_id
    record = load_request(user_id, rid)

    if not record:
        return

    render_chat(record, user_id)

    msg = st.chat_input("Send message")
    if msg:
        append_query(user_id, rid, msg)
        st.rerun()

    st.divider()

    if st.button("Delete entire request"):
        delete_request(user_id, rid)
        st.session_state.creating_new_query = True
        st.session_state.selected_request_id = None
        st.rerun()


if __name__ == "__main__":
    main()