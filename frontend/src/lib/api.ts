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
