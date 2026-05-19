import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";

const TOKEN_KEY = "onboarding.access_token";
const ID_TOKEN_KEY = "onboarding.id_token";
const REFRESH_TOKEN_KEY = "onboarding.refresh_token";

type Customer = {
  application_number: string;
  email: string;
  name: string;
};

type AuthContextValue = {
  isAuthenticated: boolean;
  loading: boolean;
  customer: Customer | null;
  login: (username: string, password: string) => Promise<void>;
  signup: (input: { email: string; name: string; phone_number: string }) => Promise<{ application_number: string }>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

function storeTokens(t: { access_token: string; id_token: string; refresh_token?: string | null }) {
  localStorage.setItem(TOKEN_KEY, t.access_token);
  localStorage.setItem(ID_TOKEN_KEY, t.id_token);
  if (t.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, t.refresh_token);
}

function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ID_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchMe = useCallback(async () => {
    try {
      const { data } = await api.get<Customer>("/auth/me");
      setCustomer(data);
    } catch {
      clearTokens();
      setCustomer(null);
    }
  }, []);

  useEffect(() => {
    if (getAccessToken()) {
      fetchMe().finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [fetchMe]);

  const login = useCallback(async (username: string, password: string) => {
    const { data } = await api.post<{
      access_token: string;
      id_token: string;
      refresh_token?: string | null;
    }>("/auth/login", { username, password });
    storeTokens(data);
    await fetchMe();
  }, [fetchMe]);

  const signup = useCallback(
    async (input: { email: string; name: string; phone_number: string }) => {
      const { data } = await api.post<{ application_number: string }>("/auth/signup", input);
      return { application_number: data.application_number };
    },
    [],
  );

  const logout = useCallback(() => {
    clearTokens();
    setCustomer(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated: !!customer,
        loading,
        customer,
        login,
        signup,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
