import axios from "axios";

export const api = axios.create({
  baseURL: "/api",
  headers: { Accept: "application/json" },
});

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

export function openApplicationSocket(
  id: string,
  onEvent: (event: ApplicationEvent) => void,
): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${window.location.host}/api/applications/${id}/events`;
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
