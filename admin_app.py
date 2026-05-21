from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from datetime import datetime
from html import escape
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


def get_submission_timestamp(payload: dict[str, Any]) -> str:
    return (
        payload.get("latest_submission_timestamp")
        or payload.get("submission_timestamp")
        or payload.get("initial_timestamp")
        or ""
    )


def ensure_requests_directory() -> Path:
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    return REQUESTS_DIR


def get_all_requests():
    records = []
    requests_dir = ensure_requests_directory()

    if not requests_dir.exists():
        return records

    for user_dir in requests_dir.iterdir():
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
    path = ensure_requests_directory() / user_id / f"{request_id}.json"
    return read_json(path, None)


def save_request(user_id: str, request_id: str, payload: dict):
    path = ensure_requests_directory() / user_id / f"{request_id}.json"
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
    tracking_path = ensure_requests_directory() / user_id / "tracking.json"
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

    attachment_path = ensure_requests_directory() / user_id / relative_path
    if attachment_path.exists():
        return attachment_path.read_bytes()

    return b""


def build_pdf_data_url(file_bytes: bytes) -> str:
    encoded = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:application/pdf;base64,{encoded}"


def build_image_data_url(file_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def can_admin_respond(record: dict[str, Any]) -> bool:
    queries = record.get("query", [])
    responses = record.get("response", [])
    return len(queries) > len(responses)


def make_dom_id(value: str) -> str:
    safe_value = re.sub(r"[^a-zA-Z0-9_-]", "-", value)
    return safe_value.strip("-") or "image-preview"


def render_clickable_image_preview(image_url: str, file_name: str, popup_key: str):
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


def render_attachment_downloads(user_id: str, attachments: list[dict[str, Any]], prefix: str):
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


def render_chat(record, user_id):
    submitted_at = get_submission_timestamp(record)
    st.subheader(f"Request: {record['name']}")
    st.caption(
        f"User: {user_id} | Status: {record['status']} | Submitted: {submitted_at}"
    )

    queries = record.get("query", [])
    responses = record.get("response", [])
    attachment_groups = normalize_attachment_groups(
        record.get("user_attachments", []),
        len(queries),
    )

    max_len = max(len(queries), len(responses))

    for i in range(max_len):
        if i < len(queries):
            with st.chat_message("user"):
                st.markdown(queries[i])
                attachments = attachment_groups[i] if i < len(attachment_groups) else []
                render_attachment_downloads(
                    user_id,
                    attachments,
                    prefix=f"admin_user_query_{record.get('name', 'request')}_{i}",
                )

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

    st.title("QueryDesk Admin")

    all_requests = get_all_requests()

    selected, show_analytics = render_sidebar(all_requests)

    if show_analytics:
        st.session_state.show_analytics = True
        st.session_state.selected_request = None

    if selected:
        st.session_state.selected_request = selected
        st.session_state.show_analytics = False

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

    if can_admin_respond(record):
        admin_reply = st.chat_input("Respond to the user")

        if admin_reply:
            append_admin_response(user_id, request_id, admin_reply)
            st.rerun()
    else:
        st.info("You can reply after the user sends a new query.")

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
