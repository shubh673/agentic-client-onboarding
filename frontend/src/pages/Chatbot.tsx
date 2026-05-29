import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Bot,
  CheckCircle2,
  Loader2,
  Paperclip,
  Search,
  Send,
  ThumbsDown,
  ThumbsUp,
  Upload,
} from "lucide-react";

import {
  chatbotMessageStream,
  chatbotStartStream,
  chatbotUploadStream,
  type ChatbotResponse,
  type ChatStreamHandlers,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Message =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; kind: "text"; content: string }
  | { id: string; role: "assistant"; kind: "upload"; doc: string }
  | { id: string; role: "assistant"; kind: "summary"; data: ChatbotResponse }
  | { id: string; role: "assistant"; kind: "typing" };

function nextId() {
  return Math.random().toString(36).slice(2, 10);
}

function maskAadhaar(value?: string): string | undefined {
  if (!value) return undefined;
  const digits = value.replace(/\s+/g, "");
  if (digits.length !== 12) return value;
  return `xxxx xxxx ${digits.slice(-4)}`;
}

export function Chatbot() {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [latest, setLatest] = useState<ChatbotResponse | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const startedRef = useRef(false);
  const streamingIdRef = useRef<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void begin();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  const showTyping = () => {
    setMessages((prev) => [
      ...prev,
      { id: "typing", role: "assistant", kind: "typing" },
    ]);
  };

  // Finalize a turn once the SSE `snapshot` arrives: set the streamed bubble to
  // the authoritative text, then append the upload card / summary / handoff line.
  const finalizeResponse = (resp: ChatbotResponse) => {
    setLatest(resp);

    const handoffLine = resp.application_id
      ? "Stage 1 complete — handing off to Document Verification agent. Taking you to your application…"
      : resp.submission_error
        ? `Couldn't create the application: ${resp.submission_error}`
        : null;

    const streamId = streamingIdRef.current;
    setMessages((prev) => {
      let next = prev.filter((m) => !(m.role === "assistant" && m.kind === "typing"));
      if (streamId) {
        next = next.map((m) =>
          m.id === streamId && m.role === "assistant" && m.kind === "text"
            ? { ...m, content: resp.message || m.content }
            : m,
        );
      } else if (resp.message) {
        next = [
          ...next,
          { id: nextId(), role: "assistant", kind: "text", content: resp.message },
        ];
      }
      const extra: Message[] = [];
      if (resp.expect === "file" && resp.doc) {
        extra.push({ id: nextId(), role: "assistant", kind: "upload", doc: resp.doc });
      }
      if (resp.complete) {
        extra.push({ id: nextId(), role: "assistant", kind: "summary", data: resp });
      }
      if (handoffLine) {
        extra.push({ id: nextId(), role: "assistant", kind: "text", content: handoffLine });
      }
      return [...next, ...extra];
    });

    streamingIdRef.current = null;

    if (resp.application_id) {
      const id = resp.application_id;
      setTimeout(() => navigate(`/applications/${id}`), 1500);
    }
  };

  // Shared SSE handlers: grow a single assistant bubble as `delta`s arrive.
  const makeHandlers = (): ChatStreamHandlers => {
    streamingIdRef.current = null;
    return {
      onDelta: (text) => {
        // Decide the bubble id and set the ref OUTSIDE the updater so the
        // updater stays pure (StrictMode double-invokes updaters in dev).
        if (!streamingIdRef.current) {
          const id = nextId();
          streamingIdRef.current = id;
          setMessages((prev) => [
            ...prev.filter((m) => !(m.role === "assistant" && m.kind === "typing")),
            { id, role: "assistant", kind: "text", content: text },
          ]);
        } else {
          const id = streamingIdRef.current;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id && m.role === "assistant" && m.kind === "text"
                ? { ...m, content: m.content + text }
                : m,
            ),
          );
        }
      },
      onSnapshot: (resp) => finalizeResponse(resp),
      onError: (detail) => {
        setError(detail);
        setMessages((prev) => prev.filter((m) => !(m.role === "assistant" && m.kind === "typing")));
        streamingIdRef.current = null;
      },
    };
  };

  const begin = async () => {
    setBusy(true);
    setError(null);
    showTyping();
    const handlers = makeHandlers();
    await chatbotStartStream({
      ...handlers,
      onSnapshot: (resp) => {
        setThreadId(resp.thread_id);
        handlers.onSnapshot(resp);
      },
    });
    setBusy(false);
  };

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || !threadId || busy) return;
    if (latest?.complete) return;
    if (latest?.expect === "file") return;

    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: trimmed },
    ]);
    setInput("");
    setBusy(true);
    setError(null);
    showTyping();
    await chatbotMessageStream(threadId, trimmed, makeHandlers());
    setBusy(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !threadId || busy) return;

    const verb = latest?.expect === "file" ? "Uploaded" : "Attached";
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: `${verb}: ${file.name}` },
    ]);
    setBusy(true);
    setError(null);
    showTyping();
    await chatbotUploadStream(threadId, file, makeHandlers());
    setBusy(false);
  };

  const expectingFile = latest?.expect === "file";
  const inputDisabled = busy || !threadId || expectingFile || (latest?.complete ?? false);
  const placeholder = !threadId
    ? "Starting…"
    : latest?.complete
      ? "Onboarding complete"
      : expectingFile
        ? "Use the upload card above"
        : "Type your reply… or attach a PDF";

  return (
    <div className="flex h-full flex-col bg-background">
      <header className="border-b bg-background px-8 py-4">
        <div className="mx-auto flex w-full max-w-3xl items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-full bg-orange-500/10 text-orange-600">
            <Bot className="size-5" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-foreground">Customer Onboarding agent</p>
            <p className="text-xs text-muted-foreground">KYC application intake · powered by LangGraph</p>
          </div>
        </div>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-7 px-8 py-10">
          {messages.map((m) => {
            if (m.role === "user") {
              return (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[75%] whitespace-pre-wrap rounded-2xl bg-muted px-4 py-2 text-sm text-foreground">
                    {m.content}
                  </div>
                </div>
              );
            }

            if (m.kind === "typing") {
              return (
                <div key={m.id} className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  <span className="text-sm">Thinking…</span>
                </div>
              );
            }

            if (m.kind === "text") {
              return (
                <div key={m.id} className="flex flex-col gap-3">
                  <Markdown content={m.content} />
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <button
                      type="button"
                      aria-label="Helpful"
                      className="rounded-md p-1 hover:bg-accent hover:text-foreground"
                    >
                      <ThumbsUp className="size-4" />
                    </button>
                    <button
                      type="button"
                      aria-label="Not helpful"
                      className="rounded-md p-1 hover:bg-accent hover:text-foreground"
                    >
                      <ThumbsDown className="size-4" />
                    </button>
                  </div>
                </div>
              );
            }

            if (m.kind === "upload") {
              const isActiveUpload =
                expectingFile && latest?.doc === m.doc && !busy;
              const alreadyUploaded =
                (m.doc === "PAN card" && latest?.uploads.pan_card) ||
                (m.doc === "Aadhaar card" && latest?.uploads.aadhaar_card);
              return (
                <div key={m.id}>
                  <DocUpload
                    label={m.doc}
                    uploaded={Boolean(alreadyUploaded)}
                    active={isActiveUpload}
                    onClick={() => fileInputRef.current?.click()}
                  />
                </div>
              );
            }

            return <SummaryCard key={m.id} data={m.data} />;
          })}
        </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        accept="image/jpeg,image/png,application/pdf"
        onChange={handleFile}
      />

      <div className="border-t bg-background px-8 py-5">
        <div className="mx-auto w-full max-w-3xl">
          {error && (
            <p className="mb-2 text-xs font-medium text-destructive">{error}</p>
          )}
          <div
            className={cn(
              "flex items-end gap-2 rounded-3xl border bg-background pl-4 pr-1.5 py-1.5 shadow-sm",
              !inputDisabled && "focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-1",
              inputDisabled && "opacity-60",
            )}
          >
            <Search className="mb-2 size-4 shrink-0 text-muted-foreground" />
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={inputDisabled}
              placeholder={placeholder}
              className="flex-1 resize-none overflow-y-auto bg-transparent py-1.5 text-sm leading-6 placeholder:text-muted-foreground focus:outline-none disabled:cursor-not-allowed"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              aria-label="Attach file"
              disabled={busy || !threadId || (latest?.complete ?? false)}
              className="flex size-9 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:hover:bg-transparent"
            >
              <Paperclip className="size-4" />
            </button>
            <button
              type="button"
              onClick={handleSend}
              disabled={inputDisabled || !input.trim()}
              aria-label="Send message"
              className={cn(
                "flex size-9 shrink-0 items-center justify-center rounded-full text-white transition-colors",
                !inputDisabled && input.trim()
                  ? "bg-orange-500 hover:bg-orange-600"
                  : "bg-orange-300 cursor-not-allowed",
              )}
            >
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Markdown({ content }: { content: string }) {
  return (
    <div className="text-[15px] leading-relaxed text-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: (props) => <p className="mb-2 last:mb-0" {...props} />,
          ul: (props) => <ul className="my-2 list-disc space-y-1 pl-6" {...props} />,
          ol: (props) => <ol className="my-2 list-decimal space-y-1 pl-6" {...props} />,
          li: (props) => <li className="pl-1" {...props} />,
          strong: (props) => <strong className="font-semibold" {...props} />,
          a: (props) => (
            <a className="text-orange-600 underline" target="_blank" rel="noreferrer" {...props} />
          ),
          code: (props) => (
            <code className="rounded bg-muted px-1 py-0.5 text-[13px]" {...props} />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function DocUpload({
  label,
  uploaded,
  active,
  onClick,
}: {
  label: string;
  uploaded: boolean;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!active && uploaded}
      className={cn(
        "flex w-full items-center gap-3 rounded-xl border bg-background px-4 py-3 text-left transition-colors",
        uploaded
          ? "border-emerald-200 bg-emerald-50"
          : active
            ? "hover:bg-muted/60"
            : "cursor-not-allowed opacity-60",
      )}
    >
      <div
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-full",
          uploaded ? "bg-emerald-100 text-emerald-700" : "bg-muted text-muted-foreground",
        )}
      >
        {uploaded ? <CheckCircle2 className="size-4" /> : <Upload className="size-4" />}
      </div>
      <div className="min-w-0 flex-1 leading-tight">
        <p className="text-sm font-medium text-foreground">{label}</p>
        <p className="truncate text-xs text-muted-foreground">
          {uploaded
            ? "Uploaded"
            : active
              ? "Click to upload (JPG, PNG, or PDF · up to 5 MB)"
              : "Awaiting earlier step…"}
        </p>
      </div>
    </button>
  );
}

function SummaryCard({ data }: { data: ChatbotResponse }) {
  const d = data.data;
  const rows: { label: string; value?: string }[] = [
    { label: "Full name", value: d.full_name },
    { label: "DOB", value: d.dob },
    { label: "Mobile", value: d.mobile },
    { label: "Email", value: d.email },
    { label: "Address", value: d.address },
    { label: "PAN", value: d.pan },
    { label: "Aadhaar", value: maskAadhaar(d.aadhaar) },
    {
      label: "Documents",
      value:
        data.uploads.pan_card && data.uploads.aadhaar_card
          ? "2 uploaded"
          : data.uploads.pan_card || data.uploads.aadhaar_card
            ? "1 uploaded"
            : undefined,
    },
  ];

  return (
    <div className="rounded-2xl border bg-background p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <div className="flex size-7 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
          <CheckCircle2 className="size-4" />
        </div>
        <p className="text-sm font-semibold text-foreground">Application captured</p>
      </div>
      <ul className="my-1 list-disc space-y-1 pl-6 text-[15px] leading-relaxed text-foreground">
        {rows.map((r) => (
          <li key={r.label} className="pl-1">
            <strong className="font-semibold">{r.label}:</strong> {r.value ?? "—"}
          </li>
        ))}
      </ul>
    </div>
  );
}
