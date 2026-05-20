from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any

import streamlit as st


REQUESTS_DIR = Path(__file__).parent / "requests"


class RequestStatus:
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"


def read_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_all_requests():
    records = []

    if not REQUESTS_DIR.exists():
        return records

    for user_dir in REQUESTS_DIR.iterdir():
        if not user_dir.is_dir():
            continue

        tracking_file = user_dir / "tracking.json"
        entries = read_json(tracking_file, [])

        for entry in entries:
            entry["user_id"] = user_dir.name
            records.append(entry)

    # ensure newest first
    records.sort(key=lambda x: x.get("submission_timestamp", ""), reverse=True)
    return records


def load_request(user_id: str, request_id: str):
    path = REQUESTS_DIR / user_id / f"{request_id}.json"
    return read_json(path, None)


def save_request(user_id: str, request_id: str, payload: dict):
    path = REQUESTS_DIR / user_id / f"{request_id}.json"
    write_json(path, payload)


def append_admin_response(user_id: str, request_id: str, response: str):
    record = load_request(user_id, request_id)
    if not record:
        return

    responses = record.get("response", [])
    responses.append(response)
    record["response"] = responses

    # admin handled the update → clear user update alert
    if "updated" in record:
        record["updated"] = False

    save_request(user_id, request_id, record)

    # update tracking.json as well
    tracking_path = REQUESTS_DIR / user_id / "tracking.json"
    tracking_entries = read_json(tracking_path, [])

    for entry in tracking_entries:
        if entry.get("query_id") == request_id:
            entry["updated"] = False

    write_json(tracking_path, tracking_entries)


def mark_completed(user_id: str, request_id: str):
    record = load_request(user_id, request_id)
    if not record:
        return

    completion_ts = datetime.now().isoformat(timespec="seconds")

    # update request json
    record["status"] = RequestStatus.COMPLETED
    record["completion_timestamp"] = completion_ts
    save_request(user_id, request_id, record)

    # update tracking.json
    tracking_path = REQUESTS_DIR / user_id / "tracking.json"
    tracking_entries = read_json(tracking_path, [])

    for entry in tracking_entries:
        if entry.get("query_id") == request_id:
            entry["status"] = RequestStatus.COMPLETED

    # keep newest first
    try:
        tracking_entries.sort(
            key=lambda x: x.get("submission_timestamp", ""),
            reverse=True,
        )
    except Exception:
        pass

    write_json(tracking_path, tracking_entries)


def render_sidebar(all_requests):
    st.sidebar.title("Admin Request Panel")

    status_filter = st.sidebar.selectbox(
        "Filter by Status",
        ["all", RequestStatus.IN_PROGRESS, RequestStatus.COMPLETED],
    )

    start_date = st.sidebar.date_input("Start Date", value=None)
    end_date = st.sidebar.date_input("End Date", value=None)

    filtered = []

    for r in all_requests:
        if status_filter != "all" and r.get("status") != status_filter:
            continue

        ts = r.get("submission_timestamp")

        if start_date:
            if ts[:10] < str(start_date):
                continue

        if end_date:
            if ts[:10] > str(end_date):
                continue

        filtered.append(r)

    st.sidebar.divider()
    st.sidebar.subheader("Requests")

    selected = None

    for r in filtered:
        label = f"{r['name']} | {r['status']} | {r['submission_timestamp']}"

        # highlight requests updated by user
        if r.get("updated"):
            label = "⚠ " + label

        if st.sidebar.button(label, key=f"{r['user_id']}_{r['query_id']}"):
            selected = r

    return selected


def render_chat(record, user_id):
    st.subheader(f"Request: {record['name']}")
    st.caption(
        f"User: {user_id} | Status: {record['status']} | Submitted: {record['submission_timestamp']}"
    )

    queries = record.get("query", [])
    responses = record.get("response", [])

    max_len = max(len(queries), len(responses))

    for i in range(max_len):
        if i < len(queries):
            with st.chat_message("user"):
                st.markdown(queries[i])

        if i < len(responses):
            with st.chat_message("assistant"):
                st.markdown(responses[i])


def main():
    st.set_page_config(page_title="Admin - QueryDesk", layout="wide")

    if "selected_request" not in st.session_state:
        st.session_state.selected_request = None

    all_requests = get_all_requests()

    # Initialize session memory for alerts
    if "shown_update_alerts" not in st.session_state:
        st.session_state.shown_update_alerts = set()

    # Popup alert only once per update
    for r in all_requests:
        req_id = r.get("query_id")
        if r.get("updated") and req_id not in st.session_state.shown_update_alerts:
            st.toast(f"User updated request: {r.get('name')} ({req_id})", icon="⚠")
            st.session_state.shown_update_alerts.add(req_id)

        # If admin already handled it (updated cleared), remove from memory
        if not r.get("updated") and req_id in st.session_state.shown_update_alerts:
            st.session_state.shown_update_alerts.remove(req_id)

    selected = render_sidebar(all_requests)

    if selected:
        st.session_state.selected_request = selected

    st.title("QueryDesk Admin")

    if not st.session_state.selected_request:
        st.info("Select a request from the left panel.")
        return

    meta = st.session_state.selected_request
    user_id = meta["user_id"]
    request_id = meta["query_id"]

    record = load_request(user_id, request_id)

    if not record:
        st.warning("Request file not found.")
        return

    render_chat(record, user_id)

    admin_reply = st.chat_input("Respond to the user")

    if admin_reply:
        append_admin_response(user_id, request_id, admin_reply)
        st.rerun()

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Mark as Completed"):
            mark_completed(user_id, request_id)
            st.success("Request marked as completed")
            st.rerun()

    with col2:
        st.write("Status:", record.get("status"))


if __name__ == "__main__":
    main()