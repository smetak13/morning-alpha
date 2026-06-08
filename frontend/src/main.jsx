import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { LogOut, Mail, UserPlus } from "lucide-react";
import "./styles.css";

async function requestJson(path, options = {}) {
  const { headers, ...requestOptions } = options;
  const response = await fetch(path, {
    credentials: "include",
    ...requestOptions,
    headers: {
      "Content-Type": "application/json",
      ...(headers ?? {}),
    },
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorMessage(payload) || `Request failed with status ${response.status}`);
  }
  return payload;
}

function errorMessage(payload) {
  const detail = payload?.detail ?? payload?.error ?? payload?.message;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg ?? String(item)).join(" ");
  }
  if (detail && typeof detail === "object") {
    return detail.message ?? JSON.stringify(detail);
  }
  return "";
}

function hasSession(payload) {
  return Boolean(extractSessionUser(payload)?.id);
}

function extractSessionUser(payload) {
  return (
    payload?.user ??
    payload?.auth?.user ??
    payload?.auth?.session?.user ??
    payload?.auth?.data?.user ??
    payload?.auth?.data?.session?.user ??
    null
  );
}

function displayName(user) {
  return user?.display_name || user?.displayName || user?.name || user?.email || "user";
}

function App() {
  const [session, setSession] = useState({ status: "checking", user: null });

  const refreshSession = useCallback(async () => {
    setSession((current) => ({ ...current, status: "checking" }));
    try {
      const payload = await requestJson("/me", { method: "GET" });
      if (hasSession(payload)) {
        setSession({ status: "authenticated", user: extractSessionUser(payload) });
      } else {
        setSession({ status: "anonymous", user: null });
      }
    } catch {
      setSession({ status: "anonymous", user: null });
    }
  }, []);

  useEffect(() => {
    refreshSession();
  }, [refreshSession]);

  const handleLogout = useCallback(async () => {
    await requestJson("/logout", { method: "POST", body: "{}" }).catch(() => {});
    setSession({ status: "anonymous", user: null });
  }, []);

  if (session.status === "checking") {
    return <LoadingScreen />;
  }

  if (session.status !== "authenticated") {
    return <AuthPage onAuthenticated={refreshSession} />;
  }

  return <MainPage user={session.user} onLogout={handleLogout} />;
}

function LoadingScreen() {
  return (
    <main className="shell shell-centered">
      <img className="app-icon" src="/ma-icon.png" alt="" aria-hidden="true" />
      <p className="muted">Checking your session...</p>
    </main>
  );
}

function AuthPage({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({
    email: "",
    password: "",
    name: "",
    remember_me: true,
  });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const title = mode === "login" ? "Sign in" : "Create account";
  const buttonLabel = mode === "login" ? "Sign in" : "Create account";

  const updateField = (event) => {
    const { name, type, checked, value } = event.target;
    setForm((current) => ({
      ...current,
      [name]: type === "checkbox" ? checked : value,
    }));
  };

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");

    const payload =
      mode === "login"
        ? {
            email: form.email.trim(),
            password: form.password,
            remember_me: form.remember_me,
          }
        : {
            email: form.email.trim(),
            password: form.password,
            name: form.name.trim() || undefined,
          };

    try {
      await requestJson(mode === "login" ? "/login" : "/register", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await onAuthenticated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Auth request failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const tabs = useMemo(
    () => [
      { id: "login", label: "Login" },
      { id: "register", label: "Register" },
    ],
    [],
  );

  return (
    <main className="auth-layout">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="brand-row">
          <img className="app-icon" src="/ma-icon.png" alt="" aria-hidden="true" />
          <div>
            <p className="eyebrow">Morning Alpha</p>
            <h1 id="auth-title">{title}</h1>
          </div>
        </div>

        <div className="tabs" role="tablist" aria-label="Auth mode">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={tab.id === mode ? "tab active" : "tab"}
              onClick={() => {
                setMode(tab.id);
                setError("");
              }}
              role="tab"
              aria-selected={tab.id === mode}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <form className="auth-form" onSubmit={submit}>
          {mode === "register" ? (
            <label>
              Full name
              <input
                autoComplete="name"
                name="name"
                onChange={updateField}
                placeholder="Jane Doe"
                type="text"
                value={form.name}
              />
            </label>
          ) : null}

          <label>
            Email
            <input
              autoComplete="email"
              name="email"
              onChange={updateField}
              placeholder="jane.doe@example.com"
              required
              type="email"
              value={form.email}
            />
          </label>

          <label>
            Password
            <input
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              name="password"
              onChange={updateField}
              required
              type="password"
              value={form.password}
            />
          </label>

          {mode === "login" ? (
            <label className="checkbox-row">
              <input checked={form.remember_me} name="remember_me" onChange={updateField} type="checkbox" />
              Remember this device
            </label>
          ) : null}

          {error ? <p className="error">{error}</p> : null}

          <button className="primary-button" disabled={submitting} type="submit">
            {mode === "login" ? <Mail size={18} aria-hidden="true" /> : <UserPlus size={18} aria-hidden="true" />}
            {submitting ? "Submitting..." : buttonLabel}
          </button>
        </form>
      </section>
    </main>
  );
}

function MainPage({ user, onLogout }) {
  return (
    <main className="app-layout">
      <header className="topbar">
        <div className="brand-row compact">
          <img className="topbar-logo" src="/ma-logo.png" alt="Morning Alpha" />
        </div>
        <button className="icon-button" onClick={onLogout} type="button" title="Sign out">
          <LogOut size={18} aria-hidden="true" />
        </button>
      </header>
      <section className="main-content">
        <p className="eyebrow">Signed in as {displayName(user)}</p>
        <h1>Main page</h1>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
