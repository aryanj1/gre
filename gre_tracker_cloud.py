"""Cloud GRE tracker: 14-day sprint with private view and password-protected editing.

Deploy with Streamlit Community Cloud, and configure Supabase + owner password
using Streamlit app Secrets (do not commit secrets to GitHub).
"""

from __future__ import annotations

import csv
import hmac
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st


# ────────────────────────── Sprint configuration ──────────────────────────
START = date(2026, 10, 16)
END = date(2026, 10, 29)
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]

# (database column, display label, daily minimum, daily aggressive target)
TARGETS = [
    ("quant", "Quant questions", 50, 75),
    ("verbal", "Verbal questions (TC + SE)", 35, 50),
    ("rc", "Reading comprehension", 20, 30),
    ("new_words", "New vocabulary words", 50, 100),
    ("revised_words", "Previously learned words revised", 100, 200),
]
QUESTION_FIELDS = ("quant", "verbal", "rc")
ACCURACY_FIELDS = {
    "quant": "quant_correct",
    "verbal": "verbal_correct",
    "rc": "rc_correct",
}

st.set_page_config(
    page_title="GRE Sprint · Oct 16–29",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      :root { color-scheme: dark; }
      .stApp { background: #090c13; color: #eaf0fb; }
      [data-testid="stSidebar"] { background: #101522; border-right: 1px solid #222b3c; }
      [data-testid="stHeader"] { background: transparent; }
      .block-container { max-width: 1250px; padding-top: 2rem; padding-bottom: 3.4rem; }
      h1, h2, h3 { letter-spacing: -0.025em; }
      .hero {
          padding: 29px 33px; border: 1px solid #2c3253; border-radius: 21px;
          background: radial-gradient(circle at 93% 2%, #273259 0%, transparent 45%),
                      linear-gradient(120deg,#151b30,#0f1320);
          margin-bottom: 25px;
      }
      .eyebrow { color: #b1a8ff; font-size: .79rem; font-weight: 760;
                 text-transform: uppercase; letter-spacing: .15em; }
      .hero-title { font-size: clamp(2.0rem, 3.9vw, 3rem); font-weight: 790;
                    line-height: 1.1; margin: 9px 0 10px; }
      .hero-sub { color: #abb8d0; font-size: 1rem; }
      .hint { color: #9ba7bb; font-size: .9rem; margin: 8px 0 15px; }
      .section-kicker { color: #c3cafe; font-size: .82rem; font-weight: 700;
                        letter-spacing: .08em; text-transform: uppercase; }
      [data-testid="stMetric"] { background: #121928; padding: 15px 17px;
                 border: 1px solid #283247; border-radius: 13px; }
      [data-testid="stMetricLabel"] { color: #a9b6ce; }
      [data-testid="stMetricValue"] { color: #f5f7ff; }
      div[data-testid="stForm"] { border: 1px solid #303a50;
                          background: #111723; border-radius: 15px; padding: 20px; }
      div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] {
          background: #8275ef; color: #0c1020; border: 0; font-weight: 760;
      }
      [data-testid="stTabs"] button { font-weight: 650; }
      .category-label { font-size: .98rem; font-weight: 670; padding-top: 9px; }
      .targets-sub { font-size: .8rem; color: #a4b0c7; margin-top: 3px; }
      .small-muted { font-size: .83rem; color: #9caac2; }
      .day-stat { border: 1px solid #283247; background: #111827; border-radius: 13px;
                  padding: 13px 16px; margin-bottom: 12px; }
      .day-stat strong { color: #eef1ff; }
      .day-stat small { color: #a3aec4; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ────────────────────── Secure, persistent Supabase store ─────────────────────
# Supabase's new sb_secret_* API keys must travel only in the apikey header.
# They never go to the browser; Streamlit executes all requests server-side.
def read_secret(name: str) -> str:
    try:
        return str(st.secrets.get(name, "")).strip()
    except (FileNotFoundError, KeyError):
        return ""


SUPABASE_URL = read_secret("SUPABASE_URL").rstrip("/")
SUPABASE_SECRET_KEY = read_secret("SUPABASE_SECRET_KEY")
OWNER_PASSWORD = read_secret("OWNER_PASSWORD")

if not all([SUPABASE_URL, SUPABASE_SECRET_KEY, OWNER_PASSWORD]):
    st.error("App setup incomplete. Add SUPABASE_URL, SUPABASE_SECRET_KEY and OWNER_PASSWORD in Streamlit Cloud → App settings → Secrets.")
    st.stop()
if not SUPABASE_URL.startswith("https://") or not SUPABASE_URL.endswith(".supabase.co"):
    st.error("SUPABASE_URL must be your project's https://....supabase.co URL.")
    st.stop()
if not SUPABASE_SECRET_KEY.startswith("sb_secret_"):
    st.error("Use a new Supabase server-side secret key (sb_secret_...), not a publishable/anon key.")
    st.stop()

API_ENDPOINT = f"{SUPABASE_URL}/rest/v1/day_log"


def require_editor() -> None:
    """Authorization enforced on every server-side write, not just hidden UI."""
    if not st.session_state.get("owner_unlocked", False):
        raise PermissionError("Editing requires owner authentication")


def db_request(method: str, *, params=None, payload=None, prefer=None):
    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    # No Authorization header: sb_secret_* is not a JWT.
    response = requests.request(
        method, API_ENDPOINT, headers=headers, params=params, json=payload, timeout=15
    )
    response.raise_for_status()
    if response.content:
        return response.json()
    return None


def read_logs() -> dict[str, dict]:
    rows = db_request("GET", params={"select": "*", "order": "day.asc"}) or []
    return {str(row["day"]): row for row in rows}


def empty_log(day: date) -> dict:
    log = {"day": day.isoformat(), "note": "", "updated_at": None}
    for field, _, _, _ in TARGETS:
        log[field] = 0
    for field in ACCURACY_FIELDS.values():
        log[field] = None
    return log


def save_log(day: date, numbers: dict, correct: dict, note: str) -> None:
    require_editor()
    if day not in DAYS:
        raise ValueError("Date outside GRE sprint")
    payload = {"day": day.isoformat(), "note": str(note)[:5000]}
    for field, *_ in TARGETS:
        count = int(numbers[field])
        if count < 0 or count > 100000:
            raise ValueError(f"Invalid count for {field}")
        payload[field] = count
    for field, correct_field in ACCURACY_FIELDS.items():
        count = correct[field]
        if count is not None and (not isinstance(count, int) or count < 0 or count > payload[field]):
            raise ValueError(f"Invalid accuracy for {field}")
        payload[correct_field] = count
    db_request(
        "POST", params={"on_conflict": "day"}, payload=payload,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def delete_log(day: date) -> None:
    require_editor()
    if day not in DAYS:
        raise ValueError("Date outside GRE sprint")
    db_request("DELETE", params={"day": f"eq.{day.isoformat()}"}, prefer="return=minimal")


def import_backup_csv(uploaded, *, overwrite: bool, old_logs: dict) -> tuple[int, int]:
    """Restore saved rows exported from the original SQLite or cloud app."""
    require_editor()
    stream = io.StringIO(uploaded.getvalue().decode("utf-8-sig"))
    entries = list(csv.DictReader(stream))
    required = {"date"} | {field for field, *_ in TARGETS}
    if not entries or not required.issubset(entries[0]):
        raise ValueError("Choose a CSV backup exported from the GRE tracker.")
    imported = skipped = 0
    for row in entries:
        try:
            day = date.fromisoformat(row["date"])
        except (ValueError, KeyError) as exc:
            raise ValueError("CSV contains an invalid date") from exc
        if day not in DAYS:
            continue
        # The export includes zero rows for every unsaved day: do not import those.
        if not row.get("updated_at", "").strip():
            skipped += 1
            continue
        if not overwrite and day.isoformat() in old_logs:
            skipped += 1
            continue
        numbers = {field: int(row[field]) for field, *_ in TARGETS}
        correct = {}
        for field, correct_field in ACCURACY_FIELDS.items():
            raw = (row.get(correct_field) or "").strip()
            correct[field] = int(raw) if raw else None
        save_log(day, numbers, correct, row.get("note", ""))
        imported += 1
    return imported, skipped


def data_for(day: date, logs: dict) -> dict:
    return logs.get(day.isoformat(), empty_log(day))


def minimum_met(log: dict) -> int:
    return sum(int(log[field] >= minimum) for field, _, minimum, _ in TARGETS)


def stretch_met(log: dict) -> int:
    return sum(int(log[field] >= stretch) for field, _, _, stretch in TARGETS)


def day_label(day: date) -> str:
    return f"{day:%a, %b} {day.day}"


def accuracy_summary(logs: dict, field: str) -> tuple[int, int]:
    correct_field = ACCURACY_FIELDS[field]
    eligible = [log for log in logs.values() if log[correct_field] is not None]
    return sum(log[correct_field] for log in eligible), sum(log[field] for log in eligible)


def csv_export(logs: dict) -> bytes:
    output = io.StringIO()
    headings = ["date"] + [field for field, *_ in TARGETS] + [
        "quant_correct", "verbal_correct", "rc_correct", "minimum_goals_met",
        "aggressive_goals_met", "note", "updated_at"
    ]
    writer = csv.DictWriter(output, fieldnames=headings)
    writer.writeheader()
    for day in DAYS:
        record = data_for(day, logs)
        row = {"date": day.isoformat()}
        for field, *_ in TARGETS:
            row[field] = record[field]
        for field in ACCURACY_FIELDS.values():
            row[field] = "" if record[field] is None else record[field]
        row["minimum_goals_met"] = minimum_met(record)
        row["aggressive_goals_met"] = stretch_met(record)
        row["note"] = record["note"]
        row["updated_at"] = record["updated_at"] or ""
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


# ───────────────────────────── App state ─────────────────────────────────
try:
    logs = read_logs()
except requests.RequestException:
    st.error("Could not load Supabase data. Check your project URL, API key and SQL table setup.")
    st.stop()
today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
active_default = min(max(today, START), END)
elapsed = sum(day <= today for day in DAYS)
fully_completed = sum(minimum_met(logs[day.isoformat()]) == 5 for day in DAYS if day.isoformat() in logs)
questions_done = sum(sum(record[field] for field in QUESTION_FIELDS) for record in logs.values())
new_words_done = sum(record["new_words"] for record in logs.values())

st.markdown(
    """
    <div class="hero">
      <div class="eyebrow">Your 14-day GRE study sprint</div>
      <div class="hero-title">GRE Progress Tracker <span style="color:#b7acff">↗</span></div>
      <div class="hero-sub">16–29 October 2026 &nbsp;·&nbsp; Log your work. Hit your minimum. Push for the stretch.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### 🔐 Access mode")
    if st.session_state.get("owner_unlocked", False):
        st.success("✍️ Owner · editing enabled")
        if st.button("🔒 Lock editing", use_container_width=True):
            st.session_state["owner_unlocked"] = False
            st.rerun()
    else:
        st.info("👀 Viewer · read-only")
        with st.expander("Unlock owner editing"):
            with st.form("owner_auth"):
                candidate = st.text_input("Owner password", type="password")
                pressed = st.form_submit_button("Unlock editing", use_container_width=True)
            if pressed:
                if hmac.compare_digest(candidate, OWNER_PASSWORD):
                    st.session_state["owner_unlocked"] = True
                    st.rerun()
                else:
                    st.error("Incorrect password")
    can_edit = bool(st.session_state.get("owner_unlocked", False))

    if st.button("🔄 Refresh progress", use_container_width=True):
        st.rerun()
    st.divider()
    st.markdown("### 🎯 Sprint overview")
    st.caption("October 16–29, 2026 · 14 days")
    st.metric("Days at all 5 minimums", f"{fully_completed} / 14")
    st.metric("Questions practiced", f"{questions_done:,}")
    st.metric("New words learned", f"{new_words_done:,}")
    st.progress(fully_completed / len(DAYS), text="Fully completed days")
    st.divider()
    st.markdown("**Daily targets**")
    for _, label, minimum, aggressive in TARGETS:
        st.caption(f"{label}: **{minimum}** min · **{aggressive}** stretch")
    st.divider()
    st.caption("☁️ Progress is stored in Supabase and shared across devices.")
    st.download_button(
        "⬇ Export all data as CSV",
        data=csv_export(logs),
        file_name="gre_sprint_16-29_oct_2026.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if can_edit:
        with st.expander("📥 Import previous CSV backup"):
            st.caption("Use a CSV exported from the original local GRE tracker. Unsaved rows are ignored.")
            upload = st.file_uploader("CSV backup", type=["csv"])
            overwrite = st.checkbox("Overwrite days already saved in cloud", value=False)
            if st.button("Import CSV", disabled=upload is None, use_container_width=True):
                try:
                    n, skipped = import_backup_csv(upload, overwrite=overwrite, old_logs=logs)
                    st.success(f"Imported {n} day(s); skipped {skipped}.")
                    st.rerun()
                except (ValueError, UnicodeError, requests.RequestException) as exc:
                    st.error(f"Import failed: {exc if not isinstance(exc, requests.RequestException) else 'database connection error'}")

summary1, summary2, summary3, summary4 = st.columns(4)
summary1.metric("Days elapsed", f"{elapsed} / 14")
summary2.metric("Minimum days achieved", f"{fully_completed} / 14")
summary3.metric("Total GRE questions", f"{questions_done:,}")
summary4.metric("New vocabulary words", f"{new_words_done:,}")

st.write("")
tab_daily, tab_overview, tab_analytics = st.tabs(
    ["✍️  Daily log", "📅  14-day overview", "📊  Analytics"]
)

# ─────────────────────────── Daily log ──────────────────────────────────
with tab_daily:
    st.markdown("### Update a study day" if can_edit else "### Study day details")
    selected_day = st.selectbox(
        "Choose a date (past dates can be edited anytime)",
        options=DAYS,
        index=DAYS.index(active_default),
        format_func=day_label,
    )
    record = data_for(selected_day, logs)
    is_saved = selected_day.isoformat() in logs

    if st.session_state.pop("saved_notice", None) == selected_day.isoformat():
        st.success(f"Saved your work for {day_label(selected_day)}.")

    if selected_day > today:
        st.info("This date is upcoming." if not can_edit else "This date is in the future. You can pre-fill it, or return when the day arrives.")
    elif not is_saved:
        st.caption("No saved entry yet." if not can_edit else "No saved entry yet — enter today's counts and click **Save daily progress**.")
    else:
        st.caption("This day has been saved." if not can_edit else "This day has been saved. You can change any count and save again.")

    form_area, daily_progress = st.columns([1.6, 1], gap="large")
    with form_area:
        if can_edit:
            with st.form(f"entry_{selected_day.isoformat()}"):
                st.markdown("**Completed today**")
                label_col, input_col, target_col = st.columns([2.1, 1.1, 1.35])
                label_col.caption("CATEGORY")
                input_col.caption("DONE")
                target_col.caption("MIN / STRETCH")

                numbers = {}
                for field, label, minimum, aggressive in TARGETS:
                    label_col, input_col, target_col = st.columns([2.1, 1.1, 1.35], vertical_alignment="center")
                    with label_col:
                        st.markdown(f'<div class="category-label">{label}</div>', unsafe_allow_html=True)
                    with input_col:
                        numbers[field] = st.number_input(
                            f"{label} completed",
                            min_value=0,
                            value=int(record[field]),
                            step=1,
                            label_visibility="collapsed",
                            key=f"{selected_day.isoformat()}_{field}",
                        )
                    with target_col:
                        st.markdown(
                            f'<div class="targets-sub">{minimum} &nbsp;/&nbsp; {aggressive}</div>',
                            unsafe_allow_html=True,
                        )

                with st.expander("Optional: track correct answers / accuracy"):
                    st.caption("Leave a field blank if you didn't record accuracy. Only recorded fields count toward accuracy charts.")
                    correct_inputs = {}
                    for field, label in (
                        ("quant", "Quant correct"),
                        ("verbal", "TC + SE correct"),
                        ("rc", "RC correct"),
                    ):
                        old = record[ACCURACY_FIELDS[field]]
                        correct_inputs[field] = st.text_input(
                            label,
                            value="" if old is None else str(old),
                            placeholder="Optional",
                            key=f"{selected_day.isoformat()}_{field}_correct",
                        )

                note = st.text_area(
                    "Study notes (optional)",
                    value=record["note"],
                    placeholder="e.g. 12 hard quant questions, revisit probability & inference RC",
                    height=92,
                    key=f"{selected_day.isoformat()}_note",
                )
                save_clicked = st.form_submit_button(
                    "💾 Save daily progress", type="primary", use_container_width=True
                )

            if save_clicked:
                parsed_correct = {}
                validation_errors = []
                for field, raw_text in correct_inputs.items():
                    raw = raw_text.strip()
                    if raw == "":
                        parsed_correct[field] = None
                    elif not raw.isdigit():
                        validation_errors.append(f"{field.title()} correct answers must be a nonnegative whole number.")
                    elif int(raw) > numbers[field]:
                        validation_errors.append(
                            f"{field.title()} correct ({int(raw)}) cannot exceed attempted ({numbers[field]})."
                        )
                    else:
                        parsed_correct[field] = int(raw)

                if validation_errors:
                    for error in validation_errors:
                        st.error(error)
                else:
                    try:
                        save_log(selected_day, numbers, parsed_correct, note)
                    except (requests.RequestException, ValueError):
                        st.error("Saving failed. Check your connection and try again.")
                        st.stop()
                    st.session_state["saved_notice"] = selected_day.isoformat()
                    st.rerun()
        else:
            st.info("Viewer mode: daily entries can only be edited by the owner.")
            st.markdown("**Completed on this day**")
            for field, label, minimum, aggressive in TARGETS:
                st.metric(label, f"{int(record[field]):,}", help=f"Minimum: {minimum} · Stretch: {aggressive}")
            if is_saved:
                with st.expander("Recorded accuracy and notes"):
                    for field, accuracy_field in ACCURACY_FIELDS.items():
                        correct = record[accuracy_field]
                        if correct is not None:
                            st.write(f"{field.upper()}: {correct} correct out of {record[field]}")
                    st.write(record["note"] or "No notes for this date.")

    with daily_progress:
        st.markdown("**Saved progress for this date**")
        if minimum_met(record) == 5:
            st.success("✅ All five minimum targets reached!")
        elif is_saved:
            st.info(f"{minimum_met(record)} / 5 minimum targets met")
        else:
            st.caption("Save an entry to see your progress here.")

        for field, label, minimum, aggressive in TARGETS:
            count = int(record[field])
            if count >= aggressive:
                status = "🚀 Stretch met"
            elif count >= minimum:
                status = "✅ Minimum met"
            else:
                status = f"{max(0, minimum - count)} to minimum"
            st.markdown(f"**{label}**")
            st.progress(min(count / aggressive, 1.0), text=f"{count} / {aggressive} stretch · {status}")

        st.markdown("---")
        q_total = sum(record[field] for field in QUESTION_FIELDS)
        st.markdown(
            f'<div class="day-stat"><strong>{q_total:,}</strong><br>'
            '<small>Questions solved (Quant + TC/SE + RC)</small></div>',
            unsafe_allow_html=True,
        )
        if is_saved and can_edit:
            with st.expander("Delete this day's entry"):
                st.warning("This permanently deletes the counts and notes for this date.")
                confirm_delete = st.checkbox("I want to delete this entry", key=f"delete_confirm_{selected_day}")
                if st.button(
                    "Delete entry", disabled=not confirm_delete,
                    key=f"delete_button_{selected_day}",
                ):
                    try:
                        delete_log(selected_day)
                    except requests.RequestException:
                        st.error("Could not delete this entry. Try again.")
                        st.stop()
                    # Remove date-specific widget state so deleted values don't linger.
                    for suffix in list(ACCURACY_FIELDS) + [field for field, *_ in TARGETS] + ["note"]:
                        st.session_state.pop(f"{selected_day.isoformat()}_{suffix}", None)
                        st.session_state.pop(f"{selected_day.isoformat()}_{suffix}_correct", None)
                    st.rerun()

# ─────────────────────────── Overview ───────────────────────────────────
with tab_overview:
    st.markdown("### All 14 days at a glance")
    st.caption("A day counts as complete only if **all five minimum targets** are met.")

    table_rows = []
    for day in DAYS:
        rec = data_for(day, logs)
        logged = day.isoformat() in logs
        reached = minimum_met(rec)
        stretched = stretch_met(rec)
        if not logged:
            status = "Upcoming" if day > today else "Not logged"
        elif stretched == 5:
            status = "🚀 All stretch goals"
        elif reached == 5:
            status = "✅ All minimums"
        else:
            status = f"{reached}/5 minimums"
        table_rows.append({
            "Date": day.strftime("%d %b (%a)"),
            "Quant": rec["quant"],
            "TC + SE": rec["verbal"],
            "RC": rec["rc"],
            "New words": rec["new_words"],
            "Revised": rec["revised_words"],
            "Status": status,
        })

    st.dataframe(
        pd.DataFrame(table_rows),
        use_container_width=True,
        hide_index=True,
        height=535,
        column_config={
            "Date": st.column_config.TextColumn("Date", width="medium"),
            "Status": st.column_config.TextColumn("Status", width="large"),
        },
    )

    st.markdown("#### Goal totals across the full sprint")
    left, right = st.columns(2)
    with left:
        st.metric("Quant + verbal + RC · minimum", f"{14 * (50 + 35 + 20):,} questions")
        st.metric("New words · minimum", f"{14 * 50:,} words")
        st.metric("Words revised · minimum", f"{14 * 100:,} reviews")
    with right:
        st.metric("Quant + verbal + RC · stretch", f"{14 * (75 + 50 + 30):,} questions")
        st.metric("New words · stretch", f"{14 * 100:,} words")
        st.metric("Words revised · stretch", f"{14 * 200:,} reviews")

# ─────────────────────────── Analytics ──────────────────────────────────
with tab_analytics:
    st.markdown("### Performance analytics")
    st.caption("Your daily counts are shown here as soon as you save them.")

    chart_rows = []
    for day in DAYS:
        rec = data_for(day, logs)
        chart_rows.append({
            "Date": day.strftime("%d %b"),
            "Quant": rec["quant"],
            "TC + SE": rec["verbal"],
            "RC": rec["rc"],
            "New words": rec["new_words"],
            "Words revised": rec["revised_words"],
        })
    frame = pd.DataFrame(chart_rows).set_index("Date")

    st.markdown("#### GRE questions practiced each day")
    st.bar_chart(frame[["Quant", "TC + SE", "RC"]], stack=True, height=320)
    st.markdown("#### Vocabulary work each day")
    st.bar_chart(frame[["New words", "Words revised"]], height=300)

    st.markdown("#### Progress toward the 14-day stretch goals")
    for field, label, minimum, stretch in TARGETS:
        completed = sum(rec[field] for rec in logs.values())
        whole_sprint_minimum = minimum * len(DAYS)
        whole_sprint_stretch = stretch * len(DAYS)
        st.markdown(f"**{label}** — {completed:,} done")
        st.progress(
            min(completed / whole_sprint_stretch, 1.0),
            text=f"{completed:,} / {whole_sprint_stretch:,} stretch · full-sprint minimum {whole_sprint_minimum:,}",
        )

    st.markdown("#### Accuracy (if you've entered correct answers)")
    acc_cols = st.columns(3)
    for col, field, title in zip(acc_cols, QUESTION_FIELDS, ("Quant", "TC + SE", "RC")):
        correct, attempted = accuracy_summary(logs, field)
        with col:
            st.metric(title, f"{correct / attempted:.1%}" if attempted else "Not recorded")
            if attempted:
                st.caption(f"{correct} / {attempted} questions across accuracy-tracked entries")

    st.markdown("---")
    st.download_button(
        "⬇ Download CSV backup",
        data=csv_export(logs),
        file_name="gre_sprint_16-29_oct_2026.csv",
        mime="text/csv",
    )

st.caption("Progress is securely stored in Supabase. Only the owner can make changes; use the CSV export for an additional backup.")
