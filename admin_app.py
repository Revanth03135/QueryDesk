from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any

import streamlit as st


REQUESTS_DIR = Path(__file__).parent / "requests"
DEPARTMENT = "Marketing"


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


def get_submission_timestamp(payload: dict[str, Any]) -> str:
    return (
        payload.get("latest_submission_timestamp")
        or payload.get("submission_timestamp")
        or payload.get("initial_timestamp")
        or ""
    )


def get_department_directory() -> Path:
    department_dir = REQUESTS_DIR / DEPARTMENT
    department_dir.mkdir(parents=True, exist_ok=True)
    return department_dir


def get_all_requests():
    records = []
    department_dir = get_department_directory()

    if not department_dir.exists():
        return records

    for user_dir in department_dir.iterdir():
        if not user_dir.is_dir():
            continue

        tracking_file = user_dir / "tracking.json"
        entries = read_json(tracking_file, [])

        for entry in entries:
            entry["user_id"] = user_dir.name
            records.append(entry)

    # ensure newest first
    records.sort(key=get_submission_timestamp, reverse=True)
    return records


def load_request(user_id: str, request_id: str):
    path = get_department_directory() / user_id / f"{request_id}.json"
    return read_json(path, None)


def save_request(user_id: str, request_id: str, payload: dict):
    path = get_department_directory() / user_id / f"{request_id}.json"
    write_json(path, payload)


def append_admin_response(user_id: str, request_id: str, response: str):
    record = load_request(user_id, request_id)
    if not record:
        return

    responses = record.get("response", [])
    responses.append(response)
    record["response"] = responses

    save_request(user_id, request_id, record)


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
    tracking_path = get_department_directory() / user_id / "tracking.json"
    tracking_entries = read_json(tracking_path, [])

    for entry in tracking_entries:
        if entry.get("query_id") == request_id:
            entry["status"] = RequestStatus.COMPLETED

    # keep newest first
    try:
        tracking_entries.sort(
            key=get_submission_timestamp,
            reverse=True,
        )
    except Exception:
        pass

    write_json(tracking_path, tracking_entries)


def render_sidebar(all_requests):
    st.sidebar.title("Admin Request Panel")

    show_analytics = st.sidebar.button(
        "View Analytics",
        key="view_analytics",
        use_container_width=True,
    )

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

        ts = get_submission_timestamp(r)

        if start_date and ts:
            if ts[:10] < str(start_date):
                continue

        if end_date and ts:
            if ts[:10] > str(end_date):
                continue

        filtered.append(r)

    st.sidebar.divider()
    st.sidebar.subheader("Requests")

    selected = None

    for r in filtered:
        label = f"{r['name']} | {r['status']} | {get_submission_timestamp(r)}"
        if st.sidebar.button(label, key=f"{r['user_id']}_{r['query_id']}"):
            selected = r

    return selected, show_analytics


def render_chat(record, user_id):
    submitted_at = get_submission_timestamp(record)
    st.subheader(f"Request: {record['name']}")
    st.caption(
        f"User: {user_id} | Status: {record['status']} | Submitted: {submitted_at}"
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


def parse_iso_datetime(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None

    try:
        return datetime.fromisoformat(timestamp)
    except ValueError:
        return None


def format_duration(total_seconds: float | None) -> str:
    if total_seconds is None:
        return "N/A"

    total_minutes = int(total_seconds // 60)
    hours, minutes = divmod(total_minutes, 60)

    if hours:
        return f"{hours}h {minutes}m"

    return f"{minutes}m"


def get_period_key(timestamp: str, grouping: str) -> str:
    parsed = parse_iso_datetime(timestamp)
    if parsed is None:
        return "unknown"

    if grouping == "Weekly":
        iso_year, iso_week, _ = parsed.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"

    if grouping == "Monthly":
        return parsed.strftime("%Y-%m")

    return parsed.strftime("%Y-%m-%d")


def matches_selected_period(timestamp: str, grouping: str, selected_date) -> bool:
    parsed = parse_iso_datetime(timestamp)
    if parsed is None:
        return False

    if grouping == "Weekly":
        selected_year, selected_week, _ = selected_date.isocalendar()
        parsed_year, parsed_week, _ = parsed.date().isocalendar()
        return (selected_year, selected_week) == (parsed_year, parsed_week)

    if grouping == "Monthly":
        return (
            parsed.year == selected_date.year
            and parsed.month == selected_date.month
        )

    return parsed.date() == selected_date


def get_selected_period_label(grouping: str, selected_date) -> str:
    if grouping == "Weekly":
        year, week, _ = selected_date.isocalendar()
        return f"{year}-W{week:02d}"

    if grouping == "Monthly":
        return selected_date.strftime("%Y-%m")

    return selected_date.strftime("%Y-%m-%d")


def build_analytics(all_requests, grouping: str, selected_date):
    filtered_requests = [
        request
        for request in all_requests
        if matches_selected_period(get_submission_timestamp(request), grouping, selected_date)
    ]

    total_requests = len(filtered_requests)
    in_progress_count = sum(
        1 for request in filtered_requests if request.get("status") == RequestStatus.IN_PROGRESS
    )
    completed_count = sum(
        1 for request in filtered_requests if request.get("status") == RequestStatus.COMPLETED
    )

    selected_period_label = get_selected_period_label(grouping, selected_date)
    status_chart_data = [
        {
            "period": selected_period_label,
            "status": RequestStatus.IN_PROGRESS,
            "count": in_progress_count,
        },
        {
            "period": selected_period_label,
            "status": RequestStatus.COMPLETED,
            "count": completed_count,
        },
    ]

    timeline_source = all_requests if grouping == "Date-wise" else filtered_requests
    timeline_counts: dict[str, int] = {}
    response_durations: list[float] = []

    for request in filtered_requests:
        request_record = load_request(request.get("user_id", ""), request.get("query_id", ""))
        if not request_record:
            continue

        submitted_at = parse_iso_datetime(
            request_record.get("initial_timestamp") or request_record.get("submission_timestamp")
        )
        completed_at = parse_iso_datetime(request_record.get("completion_timestamp"))

        if submitted_at and completed_at and completed_at >= submitted_at:
            response_durations.append((completed_at - submitted_at).total_seconds())

    timeline_grouping = "Date-wise" if grouping == "Date-wise" else grouping
    for request in timeline_source:
        timestamp = get_submission_timestamp(request)
        period_key = get_period_key(timestamp, timeline_grouping)
        timeline_counts[period_key] = timeline_counts.get(period_key, 0) + 1

    timeline_chart_data = [
        {"period": period, "count": count}
        for period, count in sorted(timeline_counts.items(), key=lambda item: item[0])
    ]

    average_response_seconds = (
        sum(response_durations) / len(response_durations) if response_durations else None
    )

    return {
        "total_requests": total_requests,
        "in_progress_count": in_progress_count,
        "completed_count": completed_count,
        "average_response_time": format_duration(average_response_seconds),
        "status_chart_data": status_chart_data,
        "timeline_chart_data": timeline_chart_data,
        "selected_period_label": selected_period_label,
    }


def render_analytics(all_requests):
    title_col, filter_col, date_col = st.columns([4, 1.3, 1.7], vertical_alignment="center")

    with title_col:
        st.subheader("Analytics")

    with filter_col:
        grouping = st.selectbox(
            "Filter",
            ["Date-wise", "Weekly", "Monthly"],
            key="analytics_grouping",
        )

    with date_col:
        selected_date = st.date_input(
            "Calendar",
            value=datetime.now().date(),
            key="analytics_selected_date",
        )

    st.caption("Operational KPIs for the selected period")

    analytics = build_analytics(all_requests, grouping, selected_date)

    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
    metric_col1.metric("Total Requests", analytics["total_requests"])
    metric_col2.metric("In Progress", analytics["in_progress_count"])
    metric_col3.metric("Completed", analytics["completed_count"])
    metric_col4.metric("Avg Response Time", analytics["average_response_time"])

    st.markdown(f"#### Requests by Status — {analytics['selected_period_label']}")
    st.vega_lite_chart(
        {
            "data": {"values": analytics["status_chart_data"]},
            "mark": {"type": "bar", "cornerRadiusTopLeft": 4, "cornerRadiusTopRight": 4},
            "encoding": {
                "x": {"field": "period", "type": "nominal", "title": grouping},
                "y": {"field": "count", "type": "quantitative", "title": "Count"},
                "xOffset": {"field": "status"},
                "color": {"field": "status", "type": "nominal", "title": "Status"},
            },
        },
        use_container_width=True,
    )

    st.markdown("#### Request Volume Timeline")
    st.vega_lite_chart(
        {
            "data": {"values": analytics["timeline_chart_data"]},
            "mark": {"type": "line", "point": True},
            "encoding": {
                "x": {"field": "period", "type": "ordinal", "title": grouping},
                "y": {"field": "count", "type": "quantitative", "title": "Requests"},
                "color": {"value": "#F58518"},
            },
        },
        use_container_width=True,
    )


def main():
    st.set_page_config(page_title="Admin - QueryDesk", layout="wide")

    if "selected_request" not in st.session_state:
        st.session_state.selected_request = None

    if "show_analytics" not in st.session_state:
        st.session_state.show_analytics = False

    all_requests = get_all_requests()

    selected, show_analytics = render_sidebar(all_requests)

    if show_analytics:
        st.session_state.show_analytics = True
        st.session_state.selected_request = None

    if selected:
        st.session_state.selected_request = selected
        st.session_state.show_analytics = False

    st.title("QueryDesk Admin")

    if st.session_state.show_analytics:
        render_analytics(all_requests)
        return

    if not st.session_state.selected_request:
        st.info("Select a request from the left panel or open analytics.")
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
