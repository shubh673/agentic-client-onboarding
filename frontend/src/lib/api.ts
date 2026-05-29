import axios from "axios";

const TOKEN_KEY = "onboarding.access_token";

export const api = axios.create({
  baseURL: "/api",
  headers: { Accept: "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem("onboarding.id_token");
      localStorage.removeItem("onboarding.refresh_token");
      // Avoid redirect loops on /auth/* endpoints themselves.
      const url: string = error?.config?.url ?? "";
      if (!url.startsWith("/auth/")) {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  },
);

export type ApplicationDocument = {
  id: string;
  doc_type: "pan" | "aadhaar";
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  uploaded_at: string;
};

export type Application = {
  id: string;
  full_name: string;
  dob: string;
  mobile: string;
  email: string;
  address: string;
  pan_number: string;
  aadhaar_number: string;
  current_stage: number;
  status: string;
  verification_reason: string | null;
  created_at: string;
  updated_at: string;
  documents: ApplicationDocument[];
};

export type LogLevel = "info" | "success" | "error";

export type LogEntry = {
  id: string;
  application_id: string;
  stage: number;
  level: LogLevel;
  message: string;
  ts: string;
};

export type ApplicationEvent =
  | { type: "application_update"; application: Application }
  | { type: "log_appended"; log: LogEntry };

export async function listApplications(): Promise<Application[]> {
  const { data } = await api.get<Application[]>("/applications");
  return data;
}

export async function getApplication(id: string): Promise<Application> {
  const { data } = await api.get<Application>(`/applications/${id}`);
  return data;
}

export async function getApplicationLogs(id: string): Promise<LogEntry[]> {
  const { data } = await api.get<LogEntry[]>(`/applications/${id}/logs`);
  return data;
}

export async function createApplication(form: FormData): Promise<Application> {
  const { data } = await api.post<Application>("/applications", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function reuploadDocuments(
  id: string,
  files: { pan?: File | null; aadhaar?: File | null },
): Promise<Application> {
  const fd = new FormData();
  if (files.pan) fd.append("pan_file", files.pan);
  if (files.aadhaar) fd.append("aadhaar_file", files.aadhaar);
  const { data } = await api.patch<Application>(`/applications/${id}/documents`, fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export type ChatbotResponse = {
  thread_id: string;
  message: string;
  expect: "text" | "file";
  doc: string | null;
  complete: boolean;
  data: {
    full_name?: string;
    dob?: string;
    mobile?: string;
    email?: string;
    address?: string;
    pan?: string;
    aadhaar?: string;
  };
  uploads: { pan_card: boolean; aadhaar_card: boolean };
  application_id?: string | null;
  submission_error?: string | null;
};

export async function chatbotStart(): Promise<ChatbotResponse> {
  const { data } = await api.post<ChatbotResponse>("/chatbot/start");
  return data;
}

export async function chatbotMessage(
  thread_id: string,
  text: string,
): Promise<ChatbotResponse> {
  const { data } = await api.post<ChatbotResponse>("/chatbot/message", {
    thread_id,
    text,
  });
  return data;
}

export async function chatbotUpload(
  thread_id: string,
  file: File,
): Promise<ChatbotResponse> {
  const fd = new FormData();
  fd.append("thread_id", thread_id);
  fd.append("file", file);
  const { data } = await api.post<ChatbotResponse>("/chatbot/upload", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export type ChatStreamHandlers = {
  onDelta: (text: string) => void;
  onSnapshot: (resp: ChatbotResponse) => void;
  onError: (detail: string) => void;
};

/**
 * POST to an SSE endpoint and dispatch `delta` / `snapshot` / `error` events.
 * Uses fetch (not EventSource) so we can send a POST body and the Bearer token,
 * and mirrors the axios 401 -> /login behavior.
 */
async function streamSSE(
  path: string,
  init: RequestInit,
  h: ChatStreamHandlers,
): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch {
    h.onError("Network error. Please try again.");
    return;
  }

  // FastAPI's HTTPBearer returns 403 when the Authorization header is missing
  // and 401 when the token is invalid/expired — treat both as "please log in".
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem("onboarding.id_token");
    localStorage.removeItem("onboarding.refresh_token");
    window.location.assign("/login");
    return;
  }
  if (!res.ok || !res.body) {
    let detail = "Something went wrong. Please try again.";
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    h.onError(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (raw: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) return;
    let data: unknown;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    if (event === "delta") h.onDelta((data as { text: string }).text);
    else if (event === "snapshot") h.onSnapshot(data as ChatbotResponse);
    else if (event === "error") h.onError((data as { detail: string }).detail);
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (chunk.trim()) dispatch(chunk);
    }
  }
  if (buffer.trim()) dispatch(buffer);
}

export function chatbotStartStream(h: ChatStreamHandlers): Promise<void> {
  return streamSSE("/chatbot/start/stream", { method: "POST" }, h);
}

export function chatbotMessageStream(
  thread_id: string,
  text: string,
  h: ChatStreamHandlers,
): Promise<void> {
  return streamSSE(
    "/chatbot/message/stream",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id, text }),
    },
    h,
  );
}

export function chatbotUploadStream(
  thread_id: string,
  file: File,
  h: ChatStreamHandlers,
): Promise<void> {
  const fd = new FormData();
  fd.append("thread_id", thread_id);
  fd.append("file", file);
  // No explicit Content-Type: the browser sets the multipart boundary.
  return streamSSE("/chatbot/upload/stream", { method: "POST", body: fd }, h);
}

export function openApplicationSocket(
  id: string,
  onEvent: (event: ApplicationEvent) => void,
): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const token = localStorage.getItem(TOKEN_KEY);
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  const url = `${protocol}//${window.location.host}/api/applications/${id}/events${qs}`;
  const ws = new WebSocket(url);
  ws.onmessage = (e) => {
    try {
      const parsed = JSON.parse(e.data) as ApplicationEvent;
      onEvent(parsed);
    } catch {
      /* ignore */
    }
  };
  return ws;
}
