"""LangGraph KYC onboarding chatbot adapted for HTTP request/response.

Differs from the standalone CLI version (main.py reference) in two ways:

1. Upload prompts say "upload your file" — the actual file is delivered via a
   multipart POST in the router, which saves it server-side and resumes the
   graph with the stored file path. The user never types a file path.

2. `run_step()` advances the graph until the next `interrupt` (or END) and
   returns a snapshot suitable for JSON serialization.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from pydantic import BaseModel

LABELS = {
    "full_name": "Full name",
    "dob": "Date of birth",
    "mobile": "Mobile",
    "email": "Email",
    "address": "Address",
    "pan": "PAN number",
    "aadhaar": "Aadhaar number",
}

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_BYTES = 5 * 1024 * 1024


class Details(BaseModel):
    full_name: Optional[str] = None
    dob: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    pan: Optional[str] = None
    aadhaar: Optional[str] = None


class Confirmed(BaseModel):
    yes: bool


class State(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    full_name: str
    dob: str
    mobile: str
    email: str
    address: str
    pan: str
    aadhaar: str
    pan_card_path: str
    aadhaar_card_path: str


_llm: Optional[ChatGroq] = None
_graph = None
_checkpointer: Optional[MemorySaver] = None


def get_llm() -> ChatGroq:
    global _llm
    if _llm is None:
        load_dotenv()
        _llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.3)
    return _llm


def _say(prompt: str) -> AIMessage:
    return get_llm().invoke([SystemMessage(content=prompt)])


PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
AADHAAR_RE = re.compile(r"^\d{12}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MOBILE_RE = re.compile(r"^\+?\d{10,15}$")


def _field_errors(values: dict) -> list[str]:
    """Format checks on extracted KYC fields. Empty list means everything passes."""
    errors: list[str] = []
    pan = values.get("pan")
    if pan and not PAN_RE.match(pan):
        errors.append(
            f"- PAN: {pan!r} doesn't look right. It should be 5 letters + 4 digits + 1 letter "
            "(e.g., ABCDE1234G)."
        )
    aadhaar = values.get("aadhaar")
    if aadhaar and not AADHAAR_RE.match(aadhaar):
        errors.append(
            f"- Aadhaar: {aadhaar!r} isn't valid. It must be exactly 12 digits."
        )
    dob = values.get("dob")
    if dob:
        ok = False
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                datetime.strptime(dob, fmt)
                ok = True
                break
            except ValueError:
                continue
        if not ok:
            errors.append(f"- Date of birth: {dob!r} should be in dd-mm-yyyy format.")
    email = values.get("email")
    if email and not EMAIL_RE.match(email):
        errors.append(f"- Email: {email!r} doesn't look like a valid email address.")
    mobile = values.get("mobile")
    if mobile:
        cleaned = mobile.replace(" ", "").replace("-", "")
        if not MOBILE_RE.match(cleaned):
            errors.append(
                f"- Mobile: {mobile!r} should be 10–15 digits, optionally with a country code."
            )
    return errors


def _validate_file(raw: str) -> tuple[Optional[str], Optional[str]]:
    p = Path(raw.strip().strip('"').strip("'"))
    if not p.is_file():
        return f"I couldn't find that file: {p}.", None
    if p.suffix.lower() not in ALLOWED_EXTS:
        return "Only JPG, PNG, or PDF are accepted.", None
    if p.stat().st_size > MAX_BYTES:
        return "That file is over 5 MB.", None
    return None, str(p.resolve())


def greet(state: State) -> dict:
    msg = _say(
        "You are a friendly KYC onboarding agent. In one short paragraph, introduce "
        "yourself and ask the user to provide ALL of these in their reply: Full name, "
        "Date of birth (dd-mm-yyyy), Mobile, Email, Address, PAN number, Aadhaar number."
    )
    return {"messages": [msg]}


def wait_for_user(state: State) -> dict:
    reply = interrupt({"prompt": state["messages"][-1].content})
    return {"messages": [HumanMessage(content=str(reply))]}


def extract(state: State) -> dict:
    convo = "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Agent'}: {m.content}"
        for m in state["messages"]
    )
    d: Details = get_llm().with_structured_output(Details).invoke(
        [
            SystemMessage(
                content=(
                    "Extract the user's KYC details from this conversation. Carry over "
                    "anything previously provided; later values override earlier ones. "
                    "Normalize: dd-mm-yyyy date, +91 prefix mobile, uppercase PAN, 12-digit Aadhaar."
                )
            ),
            HumanMessage(content=convo),
        ]
    )
    return {f: getattr(d, f).strip() for f in LABELS if getattr(d, f, None)}


def summarize(state: State) -> dict:
    have = [(LABELS[f], state[f]) for f in LABELS if state.get(f)]
    missing = [LABELS[f] for f in LABELS if not state.get(f)]
    errors = _field_errors(state)

    lines: list[str] = []
    if missing:
        lines.append("Thanks! Here's what I have so far:")
        lines += [f"{label}: {value}" for label, value in have]
        lines.append("")
        lines.append("Still need:")
        lines += [f"- {m}" for m in missing]
    elif errors:
        lines.append("Here's what I captured:")
        lines += [f"{label}: {value}" for label, value in have]
        lines.append("")
        lines.append("A few of these need to be corrected before we can proceed:")
        lines += errors
        lines.append("")
        lines.append("Please reply with the corrected value(s).")
    else:
        lines.append("Here are your details:")
        lines += [f"{label}: {value}" for label, value in have]
        lines.append("")
        lines.append("Are these correct? Reply 'yes' to proceed, or tell me what to fix.")

    return {"messages": [AIMessage(content="\n".join(lines))]}


def route_after_confirm(state: State) -> str:
    if not all(state.get(f) for f in LABELS):
        return "extract"
    # Don't let a malformed PAN/Aadhaar/DOB/email/mobile slip through into the
    # upload phase — the downstream ApplicationCreate schema would reject it.
    if _field_errors(state):
        return "extract"
    last_user = next(
        m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)
    )
    res: Confirmed = get_llm().with_structured_output(Confirmed).invoke(
        [
            SystemMessage(
                content=(
                    "Did the user confirm the KYC details are correct and want to proceed? "
                    "'yes', 'correct', 'proceed', 'looks good' => yes=true. "
                    "Any correction or 'no' => yes=false."
                )
            ),
            HumanMessage(content=last_user.content),
        ]
    )
    return "ask_pan" if res.yes else "extract"


def _make_upload(field: str, doc: str):
    def ask(state: State) -> dict:
        return {
            "messages": [
                _say(
                    f"You are the onboarding agent. Briefly ask the user to upload their {doc} "
                    "below. Mention JPG, PNG, or PDF, up to 5 MB. Do not ask for a file path — "
                    "the user will upload through the chat UI."
                )
            ]
        }

    def receive(state: State) -> dict:
        prompt = state["messages"][-1].content
        while True:
            raw = interrupt({"prompt": prompt, "expect": "file", "doc": doc})
            err, value = _validate_file(str(raw))
            if not err:
                return {
                    field: value,
                    "messages": [HumanMessage(content=f"[Uploaded {doc}]")],
                }
            prompt = f"{err} Please try uploading again."

    return ask, receive


ask_pan, receive_pan = _make_upload("pan_card_path", "PAN card")
ask_aadhaar, receive_aadhaar = _make_upload("aadhaar_card_path", "Aadhaar card")


def done(state: State) -> dict:
    return {
        "messages": [
            _say(
                "You are the onboarding agent. Both documents are uploaded — "
                "onboarding is complete. Give a warm, brief closing message."
            )
        ]
    }


def build_graph():
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()

    g = StateGraph(State)
    g.add_node("greet", greet)
    g.add_node("wait_for_details", wait_for_user)
    g.add_node("extract", extract)
    g.add_node("summarize", summarize)
    g.add_node("wait_for_confirm", wait_for_user)
    g.add_node("ask_pan", ask_pan)
    g.add_node("receive_pan", receive_pan)
    g.add_node("ask_aadhaar", ask_aadhaar)
    g.add_node("receive_aadhaar", receive_aadhaar)
    g.add_node("done", done)

    g.add_edge(START, "greet")
    g.add_edge("greet", "wait_for_details")
    g.add_edge("wait_for_details", "extract")
    g.add_edge("extract", "summarize")
    g.add_edge("summarize", "wait_for_confirm")
    g.add_conditional_edges(
        "wait_for_confirm",
        route_after_confirm,
        {"extract": "extract", "ask_pan": "ask_pan"},
    )
    g.add_edge("ask_pan", "receive_pan")
    g.add_edge("receive_pan", "ask_aadhaar")
    g.add_edge("ask_aadhaar", "receive_aadhaar")
    g.add_edge("receive_aadhaar", "done")
    g.add_edge("done", END)

    return g.compile(checkpointer=_checkpointer)


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _snapshot(app, thread_id: str) -> dict:
    """Read graph state after invoke and return a JSON-serializable snapshot."""
    config = {"configurable": {"thread_id": thread_id}}
    state = app.get_state(config)
    values = state.values or {}

    prompt: Optional[str] = None
    expect = "text"
    doc: Optional[str] = None
    interrupted = False

    for task in state.tasks:
        for intr in task.interrupts:
            interrupted = True
            v = intr.value if isinstance(intr.value, dict) else {}
            prompt = v.get("prompt")
            expect = v.get("expect", "text")
            doc = v.get("doc")
            break
        if interrupted:
            break

    last_msg: Optional[str] = None
    if not interrupted:
        msgs = values.get("messages", [])
        if msgs:
            last = msgs[-1]
            content = getattr(last, "content", None)
            if isinstance(content, str):
                last_msg = content

    return {
        "thread_id": thread_id,
        "message": prompt or last_msg or "",
        "expect": expect,
        "doc": doc,
        "complete": not interrupted,
        "data": {f: values.get(f) for f in LABELS if values.get(f)},
        "uploads": {
            "pan_card": bool(values.get("pan_card_path")),
            "aadhaar_card": bool(values.get("aadhaar_card_path")),
        },
    }


def start_session(thread_id: str) -> dict:
    """Start a fresh chat session keyed by thread_id."""
    app = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    app.invoke({"messages": []}, config=config)
    return _snapshot(app, thread_id)


def resume_session(thread_id: str, user_input: str) -> dict:
    """Resume the session with the user's reply (text or stored file path)."""
    app = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    app.invoke(Command(resume=user_input), config=config)
    return _snapshot(app, thread_id)


def session_values(thread_id: str) -> dict:
    """Return the full graph state values (including local file paths)."""
    app = get_graph()
    config = {"configurable": {"thread_id": thread_id}}
    return app.get_state(config).values or {}
