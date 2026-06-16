import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  Calendar,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileText,
  Globe2,
  Eye,
  Info,
  LogOut,
  Mail,
  MoveRight,
  Pencil,
  Plus,
  Search,
  Share2,
  Sparkles,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";
import "./styles.css";

async function requestJson(path, options = {}) {
  const { headers, timeoutMs, ...requestOptions } = options;
  const controller = timeoutMs ? new AbortController() : null;
  const timeoutId = timeoutMs ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
  const response = await fetch(path, {
    credentials: "include",
    ...requestOptions,
    signal: requestOptions.signal ?? controller?.signal,
    headers: {
      "Content-Type": "application/json",
      ...(headers ?? {}),
    },
  }).finally(() => {
    if (timeoutId) {
      window.clearTimeout(timeoutId);
    }
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

function browserTimezone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
}

const FALLBACK_TIMEZONES = [
  "Europe/Prague",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Europe/Warsaw",
  "Europe/Bratislava",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Australia/Sydney",
];

function supportedTimezones() {
  if (typeof Intl.supportedValuesOf !== "function") {
    return FALLBACK_TIMEZONES;
  }
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return FALLBACK_TIMEZONES;
  }
}

function timezoneOptions(currentTimezone) {
  return [...new Set([...(supportedTimezones() ?? []), currentTimezone].filter(Boolean))].sort();
}

function reportTimeOptions() {
  return Array.from({ length: 96 }, (_, index) => {
    const hours = Math.floor(index / 4);
    const minutes = (index % 4) * 15;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
  });
}

function normalizeTimezoneSearch(value) {
  return String(value || "").trim().toLowerCase().replaceAll("_", " ");
}

function resolveTimezoneInput(value, timezones) {
  const search = normalizeTimezoneSearch(value);
  if (!search) {
    return "";
  }
  const normalizedOptions = timezones.map((timezone) => ({
    timezone,
    normalized: normalizeTimezoneSearch(timezone),
    city: normalizeTimezoneSearch(timezone.split("/").at(-1)),
  }));
  return (
    normalizedOptions.find((option) => option.normalized === search)?.timezone ??
    normalizedOptions.find((option) => option.city === search)?.timezone ??
    normalizedOptions.find((option) => option.normalized.includes(search))?.timezone ??
    ""
  );
}

function timeInputValue(value) {
  const match = String(value || "").match(/^(\d{2}):(\d{2})/);
  return match ? `${match[1]}:${match[2]}` : "08:00";
}

function resolveTimeInput(value) {
  const trimmed = String(value || "").trim();
  const match = trimmed.match(/^(\d{1,2})(?::?(\d{2}))?$/);
  if (!match) {
    return "";
  }
  const hours = Number(match[1]);
  const minutes = Number(match[2] ?? "0");
  if (hours > 23 || minutes > 59) {
    return "";
  }
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function userSettingsFromProfile(user) {
  return {
    report_scheduled_at: timeInputValue(user?.report_scheduled_at),
    timezone: user?.timezone || browserTimezone() || "Europe/Prague",
  };
}

function dateInputValue(date) {
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 10);
}

function defaultReportFilters() {
  const today = new Date();
  const weekAgo = new Date(today);
  weekAgo.setDate(today.getDate() - 6);
  return {
    date_from: dateInputValue(weekAgo),
    date_to: dateInputValue(today),
  };
}

function formatDateTime(value) {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function parseIsoDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) {
    return new Date();
  }
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function daysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

function calendarDays(monthDate) {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstDay = new Date(year, month, 1).getDay();
  const daysBefore = (firstDay + 6) % 7;
  const totalDays = daysInMonth(year, month);
  return [
    ...Array.from({ length: daysBefore }, () => null),
    ...Array.from({ length: totalDays }, (_, index) => new Date(year, month, index + 1)),
  ];
}

function currentRoute() {
  const match = window.location.pathname.match(/^\/reports\/([^/]+)\/?$/);
  if (match) {
    return { view: "reports", reportId: decodeURIComponent(match[1]) };
  }
  if (window.location.pathname === "/reports") {
    return { view: "reports", reportId: "" };
  }
  if (window.location.pathname === "/notes") {
    return { view: "notes", reportId: "" };
  }
  if (window.location.pathname === "/research") {
    return { view: "research", reportId: "" };
  }
  return { view: "portfolio", reportId: "" };
}

function setBrowserRoute(path, replace = false) {
  const nextPath = path || "/";
  if (window.location.pathname === nextPath) {
    return;
  }
  const method = replace ? "replaceState" : "pushState";
  window.history[method]({}, "", nextPath);
  window.dispatchEvent(new Event("popstate"));
}

function enhanceReportHtml(html) {
  const enhancement = `
    <base target="_blank">
    <style>
      * { scrollbar-color: #3a3a3a #111111; scrollbar-width: thin; }
      *::-webkit-scrollbar { height: 10px; width: 10px; }
      *::-webkit-scrollbar-track { background: #111111; }
      *::-webkit-scrollbar-thumb { background: #3a3a3a; border: 2px solid #111111; border-radius: 999px; }
      *::-webkit-scrollbar-thumb:hover { background: #4a4a4a; }
    </style>
  `;
  const withTargets = String(html || "").replace(/<a\s+(?![^>]*\btarget=)/g, '<a target="_blank" rel="noopener noreferrer" ');
  if (withTargets.includes("<head>")) {
    return withTargets.replace("<head>", `<head>${enhancement}`);
  }
  return `${enhancement}${withTargets}`;
}

const THESIS_SECTIONS = {
  portfolio: [
    {
      key: "why_i_own_it",
      title: "Why I own it",
      description: "The core reason this company belongs in your portfolio. Focus on the durable thesis, not today's price move.",
    },
    {
      key: "bull_case",
      title: "Bull case",
      description: "What could go right. Include the main upside drivers, catalysts, or business improvements you want to monitor.",
    },
    {
      key: "bear_case",
      title: "Bear case",
      description: "What could go wrong. Capture the risks that would weaken your thesis or change how you think about the company.",
    },
    {
      key: "key_metrics",
      title: "Key metrics",
      description: "The numbers or signals that matter most for tracking the thesis, such as growth, margins, cash flow, users, or debt.",
    },
    {
      key: "red_flags",
      title: "Red flags",
      description: "Warning signs that deserve attention. These are early signals that the thesis may be breaking.",
    },
    {
      key: "action_triggers",
      title: "Action triggers",
      description: "Specific events that should make you review the position, such as earnings misses, guidance changes, or major news.",
    },
  ],
  watchlist: [
    {
      key: "why_i_watch_it",
      title: "Why I watch it",
      description: "Why this company is worth following even if you do not own it yet. Capture the opportunity or question you are tracking.",
    },
    {
      key: "bull_case",
      title: "Bull case",
      description: "What could make the company more attractive. Include potential upside drivers, catalysts, or improving fundamentals.",
    },
    {
      key: "bear_case",
      title: "Bear case",
      description: "What could make the company less attractive. Capture the biggest risks or reasons to stay cautious.",
    },
    {
      key: "key_metrics",
      title: "Key metrics",
      description: "The numbers or signals that would help you judge progress, such as growth, margins, cash flow, users, or valuation.",
    },
    {
      key: "red_flags",
      title: "Red flags",
      description: "Warning signs that would make you lose interest or require deeper analysis before taking the company seriously.",
    },
    {
      key: "entry_conditions",
      title: "Entry conditions",
      description: "The evidence you would need to see before considering this company as a portfolio candidate.",
    },
  ],
};

function thesisFromItem(item, itemType) {
  return Object.fromEntries(THESIS_SECTIONS[itemType].map((section) => [section.key, item?.[section.key] ?? []]));
}

function clampPosition(value, max) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return Math.min(Math.max(parsed, 0), max);
}

function sortPortfolioItems(items) {
  return [...items].sort((a, b) => {
    const positionDiff = Number(b.position_size_pct || 0) - Number(a.position_size_pct || 0);
    if (positionDiff !== 0) {
      return positionDiff;
    }
    return String(a.symbol).localeCompare(String(b.symbol));
  });
}

function stockLogoProps(src) {
  return {
    src: src || "/assets/ma-icon.png",
    onError: (event) => {
      if (event.currentTarget.src.endsWith("/assets/ma-icon.png")) {
        return;
      }
      event.currentTarget.src = "/assets/ma-icon.png";
    },
  };
}

function App() {
  const [session, setSession] = useState({ status: "checking", user: null });
  const [route, setRoute] = useState(() => currentRoute());

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

  useEffect(() => {
    const syncRoute = () => setRoute(currentRoute());
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, []);

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

  return <MainPage route={route} user={session.user} onLogout={handleLogout} />;
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
            timezone: browserTimezone(),
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

          <button className="primary-button" disabled={submitting} type="submit" style={{marginTop: "12px"}}>
            {mode === "login" ? <Mail size={18} aria-hidden="true" /> : <UserPlus size={18} aria-hidden="true" />}
            {submitting ? "Submitting..." : buttonLabel}
          </button>
        </form>
      </section>
    </main>
  );
}

function MainPage({ route, user, onLogout }) {
  const [activeView, setActiveView] = useState(route.view);
  const [portfolio, setPortfolio] = useState([]);
  const [watchlist, setWatchlist] = useState([]);
  const [itemsStatus, setItemsStatus] = useState("loading");
  const [itemsError, setItemsError] = useState("");
  const [settings, setSettings] = useState(() => userSettingsFromProfile(user));
  const [settingsError, setSettingsError] = useState("");
  const [modal, setModal] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const portfolioTotal = useMemo(
    () => portfolio.reduce((total, item) => total + Number(item.position_size_pct || 0), 0),
    [portfolio],
  );

  const loadItems = useCallback(async () => {
    setItemsStatus("loading");
    setItemsError("");
    try {
      const [portfolioPayload, watchlistPayload] = await Promise.all([
        requestJson("/api/portfolio-items", { method: "GET" }),
        requestJson("/api/watchlist-items", { method: "GET" }),
      ]);
      setPortfolio(portfolioPayload.items ?? []);
      setWatchlist(watchlistPayload.items ?? []);
      setItemsStatus("ready");
    } catch (err) {
      setItemsError(err instanceof Error ? err.message : "Unable to load holdings.");
      setItemsStatus("error");
    }
  }, []);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  useEffect(() => {
    setSettings(userSettingsFromProfile(user));
  }, [user]);

  useEffect(() => {
    setActiveView(route.view);
  }, [route.view]);

  const showPortfolio = () => {
    setActiveView("portfolio");
    setBrowserRoute("/");
  };

  const showReports = () => {
    setActiveView("reports");
    setBrowserRoute("/reports");
  };

  const showNotes = () => {
    setActiveView("notes");
    setBrowserRoute("/notes");
  };

  const showResearch = () => {
    setActiveView("research");
    setBrowserRoute("/research");
  };

  const pageTitle =
    activeView === "portfolio" ? "Portfolio workspace" : activeView === "reports" ? "Reports" : activeView === "notes" ? "Notes" : "Research";

  const updateUserSettings = async (patch) => {
    setSettings((current) => ({ ...current, ...patch }));
    setSettingsError("");
    try {
      const payload = await requestJson("/api/user/settings", {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      setSettings(userSettingsFromProfile(payload.user));
    } catch (err) {
      setSettingsError(err instanceof Error ? err.message : "Unable to update report schedule.");
    }
  };

  const openAddModal = (itemType) => {
    const remaining = itemType === "portfolio" ? Math.max(0, 100 - portfolioTotal) : 100;
    setModal({
      mode: "add",
      itemType,
      item: null,
      positionSize: Math.min(10, remaining),
      maxPositionSize: remaining,
    });
  };

  const openEditModal = (itemType, item) => {
    const maxPositionSize =
      itemType === "portfolio" ? Math.max(0, 100 - portfolioTotal + Number(item.position_size_pct || 0)) : 100;
    setModal({
      mode: "edit",
      itemType,
      item,
      stock: { symbol: item.symbol, company_name: item.company_name, logo_url: item.logo_url },
      thesis: thesisFromItem(item, itemType),
      positionSize: Number(item.position_size_pct || 0),
      maxPositionSize,
    });
  };

  const openMoveToPortfolioModal = (item) => {
    const remaining = Math.max(0, 100 - portfolioTotal);
    setModal({
      mode: "add",
      itemType: "portfolio",
      item: null,
      stock: {
        symbol: item.symbol,
        company_name: item.company_name,
        logo_url: item.logo_url,
      },
      positionSize: Math.min(10, remaining),
      maxPositionSize: remaining,
      moveFromWatchlistId: item.id,
    });
  };

  const replacePortfolioItem = (itemId, updater) => {
    setPortfolio((current) => current.map((item) => (item.id === itemId ? updater(item) : item)));
  };

  const replaceWatchlistItem = (itemId, updater) => {
    setWatchlist((current) => current.map((item) => (item.id === itemId ? updater(item) : item)));
  };

  const savePortfolioPosition = async (item) => {
    try {
      const payload = await requestJson(`/api/portfolio-items/${item.id}`, {
        method: "PUT",
        body: JSON.stringify({ position_size_pct: item.position_size_pct }),
      });
      replacePortfolioItem(item.id, () => payload.item);
    } catch (err) {
      setItemsError(err instanceof Error ? err.message : "Unable to update position size.");
      await loadItems();
    }
  };

  const updatePortfolioPosition = (item, value) => {
    const max = Math.max(0, 100 - portfolioTotal + Number(item.position_size_pct || 0));
    const next = clampPosition(value, max);
    replacePortfolioItem(item.id, (current) => ({ ...current, position_size_pct: next }));
  };

  const updateReportInclusion = async (itemType, item, nextValue) => {
    const path =
      itemType === "portfolio" ? `/api/portfolio-items/${item.id}` : `/api/watchlist-items/${item.id}`;
    const replaceItem = itemType === "portfolio" ? replacePortfolioItem : replaceWatchlistItem;
    setItemsError("");
    replaceItem(item.id, (current) => ({ ...current, include_in_report: nextValue }));
    try {
      const payload = await requestJson(path, {
        method: "PUT",
        body: JSON.stringify({ include_in_report: nextValue }),
      });
      replaceItem(item.id, () => payload.item);
    } catch (err) {
      setItemsError(err instanceof Error ? err.message : "Unable to update report setting.");
      await loadItems();
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) {
      return;
    }
    const path =
      deleteTarget.itemType === "portfolio"
        ? `/api/portfolio-items/${deleteTarget.item.id}`
        : `/api/watchlist-items/${deleteTarget.item.id}`;
    try {
      await requestJson(path, { method: "DELETE" });
      setDeleteTarget(null);
      await loadItems();
    } catch (err) {
      setItemsError(err instanceof Error ? err.message : "Unable to delete item.");
    }
  };

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
        <div className="page-heading">
          <div>
            <h1>{pageTitle}</h1>
          </div>
          {activeView === "portfolio" ? <div className="allocation-pill">{portfolioTotal.toFixed(1)}% allocated</div> : null}
        </div>

        <div className="view-tabs">
          <button
            className={activeView === "portfolio" ? "view-tab active" : "view-tab"}
            onClick={showPortfolio}
            type="button"
          >
            Portfolio
          </button>
          <button
            className={activeView === "reports" ? "view-tab active" : "view-tab"}
            onClick={showReports}
            type="button"
          >
            Reports
          </button>
          <button
            className={activeView === "notes" ? "view-tab active" : "view-tab"}
            onClick={showNotes}
            type="button"
          >
            Notes
          </button>
          <button
            className={activeView === "research" ? "view-tab active" : "view-tab"}
            onClick={showResearch}
            type="button"
          >
            Research
          </button>
        </div>

        {activeView === "portfolio" ? (
          <>
            {itemsError ? <p className="error">{itemsError}</p> : null}
            {itemsStatus === "loading" ? <p className="muted">Loading holdings...</p> : null}

            <ReportSchedulePanel
              error={settingsError}
              onChange={updateUserSettings}
              settings={settings}
            />

            <HoldingsSection
              actionLabel="Add holding"
              emptyText="No portfolio holdings yet."
              itemType="portfolio"
              items={portfolio}
              onAdd={() => openAddModal("portfolio")}
              onDelete={(item) => setDeleteTarget({ itemType: "portfolio", item })}
              onEdit={(item) => openEditModal("portfolio", item)}
              onReportToggle={(item, nextValue) => updateReportInclusion("portfolio", item, nextValue)}
              onSort={() => setPortfolio((current) => sortPortfolioItems(current))}
              onPositionChange={updatePortfolioPosition}
              onPositionCommit={savePortfolioPosition}
              portfolioTotal={portfolioTotal}
              title="Portfolio"
            />

            <HoldingsSection
              actionLabel="Add watchlist item"
              emptyText="No watchlist items yet."
              itemType="watchlist"
              items={watchlist}
              onAdd={() => openAddModal("watchlist")}
              onDelete={(item) => setDeleteTarget({ itemType: "watchlist", item })}
              onEdit={(item) => openEditModal("watchlist", item)}
              onMoveToPortfolio={openMoveToPortfolioModal}
              onReportToggle={(item, nextValue) => updateReportInclusion("watchlist", item, nextValue)}
              title="Watchlist"
            />
          </>
        ) : activeView === "reports" ? (
          <ReportsView routeReportId={route.reportId} />
        ) : activeView === "notes" ? (
          <NotesView />
        ) : (
          <ResearchView
            portfolioItems={portfolio}
            watchlistItems={watchlist}
            onAddToWatchlist={(stock) => {
              setModal({
                mode: "add",
                itemType: "watchlist",
                item: null,
                stock,
                positionSize: 10,
                maxPositionSize: 100,
              });
            }}
            onEditItem={(itemType, stockId) => {
              const item = (itemType === "portfolio" ? portfolio : watchlist).find((current) => current.stock_id === stockId);
              if (item) {
                openEditModal(itemType, item);
              }
            }}
            onMoveToPortfolio={(stockId) => {
              const item = watchlist.find((current) => current.stock_id === stockId);
              if (item) {
                openMoveToPortfolioModal(item);
              }
            }}
          />
        )}
      </section>

      {modal ? (
        <StockThesisModal
          modal={modal}
          onClose={() => setModal(null)}
          onSaved={async () => {
            if (modal.moveFromWatchlistId) {
              await requestJson(`/api/watchlist-items/${modal.moveFromWatchlistId}`, { method: "DELETE" });
            }
            setModal(null);
            await loadItems();
          }}
        />
      ) : null}

      {deleteTarget ? (
        <ConfirmDialog
          item={deleteTarget.item}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={handleDelete}
        />
      ) : null}
    </main>
  );
}

function ReportsView({ routeReportId = "" }) {
  const [filters, setFilters] = useState(defaultReportFilters);
  const [page, setPage] = useState(1);
  const [payload, setPayload] = useState({ items: [], total: 0, page_size: 10 });
  const [selectedReport, setSelectedReport] = useState(null);
  const [notesModal, setNotesModal] = useState(null);
  const [noteFormReport, setNoteFormReport] = useState(null);
  const [notesRevision, setNotesRevision] = useState(0);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const openedRouteReportIdRef = useRef("");

  const totalPages = Math.max(1, Math.ceil((payload.total || 0) / (payload.page_size || 10)));

  const loadReports = useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const query = new URLSearchParams({
        date_from: filters.date_from,
        date_to: filters.date_to,
        page: String(page),
        page_size: "10",
      });
      const nextPayload = await requestJson(`/api/reports?${query.toString()}`, { method: "GET" });
      setPayload(nextPayload);
      setStatus("ready");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Unable to load reports.");
    }
  }, [filters.date_from, filters.date_to, page]);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  const openReport = async (report, options = {}) => {
    setError("");
    try {
      const detail = await requestJson(`/api/reports/${report.id}`, { method: "GET" });
      setSelectedReport(detail.report);
      if (options.updateRoute !== false) {
        openedRouteReportIdRef.current = report.id;
        setBrowserRoute(`/reports/${encodeURIComponent(report.id)}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load report detail.");
    }
  };

  useEffect(() => {
    if (!routeReportId) {
      if (openedRouteReportIdRef.current) {
        openedRouteReportIdRef.current = "";
        setSelectedReport(null);
      }
      return;
    }
    if (openedRouteReportIdRef.current === routeReportId) {
      return;
    }
    openedRouteReportIdRef.current = routeReportId;
    openReport({ id: routeReportId }, { updateRoute: false });
  }, [routeReportId]);

  const closeReport = () => {
    setSelectedReport(null);
    if (routeReportId) {
      openedRouteReportIdRef.current = "";
      setBrowserRoute("/reports", true);
    }
  };

  const updateFilter = (key, value) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setSelectedReport(null);
    setPage(1);
  };

  return (
    <section className="reports-view">
      <div className="reports-toolbar">
        <div>
          <p className="eyebrow">Report archive</p>
          <h2>Saved reports</h2>
        </div>
        <div className="report-filters">
          <ReportDateField label="From" value={filters.date_from} onChange={(value) => updateFilter("date_from", value)} />
          <ReportDateField label="To" value={filters.date_to} onChange={(value) => updateFilter("date_to", value)} />
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}

      <div className="reports-layout">
        <div className="reports-list-panel">
          <div className="table-shell">
            <table className="reports-table reports-archive-table">
              <colgroup>
                <col className="report-date-col" />
                <col className="report-created-col" />
                <col className="report-notes-col" />
              </colgroup>
              <thead>
                <tr>
                  <th>Report date</th>
                  <th>Created at</th>
                  <th className="actions-cell">Notes</th>
                </tr>
              </thead>
              <tbody>
                {payload.items.length ? (
                  payload.items.map((report) => (
                    <tr
                      className={selectedReport?.id === report.id ? "selected-row" : ""}
                      key={report.id}
                      onClick={() => openReport(report)}
                    >
                      <td>
                        <div className="report-date-cell">
                          <FileText size={17} aria-hidden="true" />
                          <strong>{report.report_date}</strong>
                        </div>
                      </td>
                      <td>{formatDateTime(report.created_at)}</td>
                      <td className="actions-cell">
                        <span className="notes-count-pill" title={`${report.note_count ?? 0} notes`}>
                          {report.note_count ?? 0}
                        </span>
                        <button className="icon-button" onClick={(event) => { event.stopPropagation(); setNotesModal({ report, mode: "view" }); }} title="View notes" type="button">
                          <Eye size={17} aria-hidden="true" />
                        </button>
                        <button className="icon-button" onClick={(event) => { event.stopPropagation(); setNotesModal({ report, mode: "edit" }); }} title="Edit notes" type="button">
                          <Pencil size={17} aria-hidden="true" />
                        </button>
                        <button className="icon-button" onClick={(event) => { event.stopPropagation(); setNoteFormReport(report); }} title="Add note" type="button">
                          <Plus size={17} aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td className="empty-table" colSpan={3}>
                      {status === "loading" ? "Loading reports..." : "No reports found for this date range."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="pagination-row">
            <button className="secondary-button compact-button" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} type="button">
              <ChevronLeft size={16} aria-hidden="true" />
              Previous
            </button>
            <span>Page {page} of {totalPages}</span>
            <button className="secondary-button compact-button" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)} type="button">
              Next
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      {selectedReport?.html ? (
        <ReportPreviewModal report={selectedReport} onAddNote={() => setNoteFormReport(selectedReport)} onClose={closeReport} />
      ) : null}
      {notesModal ? (
        <ReportNotesModal
          mode={notesModal.mode}
          report={notesModal.report}
          revision={notesRevision}
          onChanged={loadReports}
          onAddNote={() => setNoteFormReport(notesModal.report)}
          onClose={() => setNotesModal(null)}
        />
      ) : null}
      {noteFormReport ? (
        <NoteFormModal
          report={noteFormReport}
          onClose={() => setNoteFormReport(null)}
          onSaved={() => {
            setNoteFormReport(null);
            setNotesRevision((current) => current + 1);
            loadReports();
          }}
        />
      ) : null}
    </section>
  );
}

function ReportDateField({ label, value, onChange }) {
  const [open, setOpen] = useState(false);
  const [visibleMonth, setVisibleMonth] = useState(() => parseIsoDate(value));
  const shellRef = useRef(null);
  const selectedDate = parseIsoDate(value);
  const days = calendarDays(visibleMonth);
  const monthLabel = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(visibleMonth);

  useEffect(() => {
    setVisibleMonth(parseIsoDate(value));
  }, [value]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const closeOnOutsideClick = (event) => {
      if (!shellRef.current?.contains(event.target)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", closeOnOutsideClick);
    return () => window.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  const moveMonth = (offset) => {
    setVisibleMonth((current) => new Date(current.getFullYear(), current.getMonth() + offset, 1));
  };

  const selectDate = (date) => {
    onChange(dateInputValue(date));
    setOpen(false);
  };

  return (
    <label className="report-date-field">
      {label}
      <div className="date-input-shell" ref={shellRef}>
        <input readOnly value={value} onClick={() => setOpen(true)} />
        <button
          className="combo-icon-button"
          onMouseDown={(event) => {
            event.preventDefault();
            setOpen((current) => !current);
          }}
          title={`Choose ${label.toLowerCase()} date`}
          type="button"
        >
          <Calendar size={16} aria-hidden="true" />
        </button>
        {open ? (
          <div className="date-picker-popover">
            <div className="date-picker-header">
              <button className="mini-icon-button neutral" onMouseDown={(event) => { event.preventDefault(); moveMonth(-1); }} type="button">
                <ChevronLeft size={15} aria-hidden="true" />
              </button>
              <strong>{monthLabel}</strong>
              <button className="mini-icon-button neutral" onMouseDown={(event) => { event.preventDefault(); moveMonth(1); }} type="button">
                <ChevronRight size={15} aria-hidden="true" />
              </button>
            </div>
            <div className="date-picker-weekdays">
              {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => (
                <span key={day}>{day}</span>
              ))}
            </div>
            <div className="date-picker-grid">
              {days.map((date, index) =>
                date ? (
                  <button
                    className={dateInputValue(date) === dateInputValue(selectedDate) ? "date-picker-day selected" : "date-picker-day"}
                    key={date.toISOString()}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      selectDate(date);
                    }}
                    type="button"
                  >
                    {date.getDate()}
                  </button>
                ) : (
                  <span className="date-picker-empty" key={`empty-${index}`} />
                ),
              )}
            </div>
          </div>
        ) : null}
      </div>
    </label>
  );
}

function ReportPreviewModal({ report, onAddNote, onClose }) {
  const reportHtml = useMemo(() => enhanceReportHtml(report.html), [report.html]);
  return (
    <div className="modal-backdrop report-preview-backdrop" onMouseDown={onClose}>
      <section className="report-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="report-modal-header">
          <div>
            <p className="eyebrow">Saved report</p>
            <h2>{report.report_date}</h2>
          </div>
          <div className="modal-header-actions">
            <button className="primary-button compact-button" onClick={onAddNote} type="button">
              <Plus size={16} aria-hidden="true" />
              Add note
            </button>
            <button className="icon-button" onClick={onClose} title="Close report" type="button">
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
        <iframe
          className="report-frame"
          sandbox="allow-popups allow-popups-to-escape-sandbox"
          srcDoc={reportHtml}
          title={`Report ${report.report_date}`}
        />
      </section>
    </div>
  );
}

function useNoteStocks() {
  const [stocks, setStocks] = useState([]);
  const [error, setError] = useState("");

  const loadStocks = useCallback(async () => {
    setError("");
    try {
      const payload = await requestJson("/api/notes/stocks", { method: "GET" });
      setStocks(payload.items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load companies.");
    }
  }, []);

  useEffect(() => {
    loadStocks();
  }, [loadStocks]);

  return { error, reload: loadStocks, stocks };
}

function stockMatchesSearch(stock, search) {
  const normalized = search.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  return `${stock.symbol} ${stock.company_name}`.toLowerCase().includes(normalized);
}

function NoteFormModal({ initialStock = null, report = null, researchItem = null, onClose, onSaved }) {
  const { error: stocksError, stocks } = useNoteStocks();
  const [search, setSearch] = useState("");
  const [selectedStock, setSelectedStock] = useState(initialStock);
  const [body, setBody] = useState("");
  const [isResolved, setIsResolved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const filteredStocks = stocks.filter((stock) => stockMatchesSearch(stock, search)).slice(0, 12);

  const save = async () => {
    if (!selectedStock) {
      setError("Choose a company first.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await requestJson("/api/notes", {
        method: "POST",
        body: JSON.stringify({
          stock_id: selectedStock.stock_id,
          report_id: report?.id ?? null,
          research_item_id: researchItem?.id ?? null,
          body,
          is_resolved: isResolved,
        }),
      });
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save note.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal-panel note-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">{report ? `Report ${report.report_date}` : researchItem ? `${researchItem.symbol} research` : "Notes"}</p>
            <h2>Add note</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="Close" type="button">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="note-form-grid">
          <div className="note-field">
            <span className="note-field-label">Company</span>
            {selectedStock ? (
              <div className="selected-note-stock">
                <div className="stock-cell">
                  <img className="stock-logo" {...stockLogoProps(selectedStock.logo_url)} alt="" />
                  <div>
                    <strong>{selectedStock.symbol}</strong>
                    <span>{selectedStock.company_name}</span>
                  </div>
                </div>
                {!researchItem ? (
                  <button className="secondary-button compact-button" onClick={() => { setSelectedStock(null); setSearch(""); }} type="button">
                    Change
                  </button>
                ) : null}
              </div>
            ) : (
              <div className="search-input">
                <Search size={18} aria-hidden="true" />
                <input autoFocus onChange={(event) => setSearch(event.target.value)} placeholder="Search portfolio or watchlist" value={search} />
              </div>
            )}
          </div>
          {!selectedStock ? (
            <div className="search-results note-stock-results">
              {filteredStocks.map((stock) => (
                <button
                  className="search-result"
                  key={stock.stock_id}
                  onClick={() => { setSelectedStock(stock); setSearch(""); }}
                  type="button"
                >
                  <img className="stock-logo" {...stockLogoProps(stock.logo_url)} alt="" />
                  <div className="stock-search-copy">
                    <div className="stock-title-row">
                      <strong>{stock.symbol}</strong>
                      <span className="exchange-badge">{stock.list_name}</span>
                    </div>
                    <span>{stock.company_name}</span>
                  </div>
                </button>
              ))}
            </div>
          ) : null}

          <label>
            Note
            <textarea onChange={(event) => setBody(event.target.value)} placeholder="Write what you want to follow up on..." rows={5} value={body} />
          </label>
          <label className="checkbox-row note-checkbox">
            <input checked={isResolved} onChange={(event) => setIsResolved(event.target.checked)} type="checkbox" />
            Resolved
          </label>
        </div>

        {stocksError ? <p className="error">{stocksError}</p> : null}
        {error ? <p className="error">{error}</p> : null}

        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose} type="button">
            Cancel
          </button>
          <button className="primary-button" disabled={saving} onClick={save} type="button">
            <Check size={18} aria-hidden="true" />
            {saving ? "Saving..." : "Save note"}
          </button>
        </div>
      </section>
    </div>
  );
}

function ReportNotesModal({ mode, report = null, researchItem = null, revision = 0, onAddNote, onChanged, onClose }) {
  const [notes, setNotes] = useState([]);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  const targetId = report?.id ?? researchItem?.id;
  const queryKey = report ? "report_id" : "research_item_id";
  const title = report ? report.report_date : `${researchItem?.symbol} research`;
  const emptyText = report ? "No notes for this report yet." : "No notes for this research yet.";

  const loadNotes = useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const payload = await requestJson(`/api/notes?${queryKey}=${encodeURIComponent(targetId)}&page_size=100`, { method: "GET" });
      setNotes(payload.items ?? []);
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load notes.");
      setStatus("error");
    }
  }, [queryKey, targetId]);

  useEffect(() => {
    loadNotes();
  }, [loadNotes, revision]);

  const replaceNote = (noteId, nextNote) => {
    setNotes((current) => current.map((note) => (note.id === noteId ? nextNote : note)));
  };

  const saveNote = async (note, patch) => {
    setError("");
    try {
      const payload = await requestJson(`/api/notes/${note.id}`, {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      replaceNote(note.id, payload.note);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update note.");
    }
  };

  const deleteNote = async (note) => {
    setError("");
    try {
      await requestJson(`/api/notes/${note.id}`, { method: "DELETE" });
      setNotes((current) => current.filter((item) => item.id !== note.id));
      await onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete note.");
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal-panel note-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">{report ? "Report notes" : "Research notes"}</p>
            <h2>{title}</h2>
          </div>
          <div className="modal-header-actions">
            <button className="primary-button compact-button" onClick={onAddNote} type="button">
              <Plus size={16} aria-hidden="true" />
              Add note
            </button>
            <button className="icon-button" onClick={onClose} title="Close" type="button">
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </div>

        {error ? <p className="error">{error}</p> : null}
        <div className="notes-stack">
          {notes.length ? (
            notes.map((note) => (
              <NoteCard
                editable={mode === "edit"}
                key={note.id}
                note={note}
                onDelete={() => setDeleteTarget(note)}
                onSave={(patch) => saveNote(note, patch)}
              />
            ))
          ) : (
            <p className="empty-table">{status === "loading" ? "Loading notes..." : emptyText}</p>
          )}
        </div>
        {deleteTarget ? (
          <ConfirmDialog
            item={deleteTarget}
            message={report ? "This removes the note from this report." : "This removes the note from this research."}
            onCancel={() => setDeleteTarget(null)}
            onConfirm={async () => {
              await deleteNote(deleteTarget);
              setDeleteTarget(null);
            }}
            title={`Delete note for ${deleteTarget.symbol}?`}
          />
        ) : null}
      </section>
    </div>
  );
}

function NoteCard({ editable, largeEditor = false, note, onDelete, onSave }) {
  const [body, setBody] = useState(note.body);
  const [isResolved, setIsResolved] = useState(note.is_resolved);
  const hasChanges = body !== note.body || isResolved !== note.is_resolved;

  useEffect(() => {
    setBody(note.body);
    setIsResolved(note.is_resolved);
  }, [note.body, note.is_resolved]);

  return (
    <section className="note-card">
      <div className="note-card-header">
        <div className="stock-cell">
          <img className="stock-logo" {...stockLogoProps(note.logo_url)} alt="" />
          <div>
            <strong>{note.symbol}</strong>
            <span>{note.company_name}</span>
          </div>
        </div>
        <span className={isResolved ? "status-pill resolved-pill" : "status-pill"}>{isResolved ? "Resolved" : "Open"}</span>
      </div>
      {editable ? (
        <>
          <textarea onChange={(event) => setBody(event.target.value)} rows={largeEditor ? 9 : 4} value={body} />
          <div className="note-card-actions">
            <label className="checkbox-row note-checkbox">
              <input checked={isResolved} onChange={(event) => setIsResolved(event.target.checked)} type="checkbox" />
              Resolved
            </label>
            <div className="toolbar-actions">
              <button className="primary-button compact-button" disabled={!hasChanges} onClick={() => onSave({ body, is_resolved: isResolved })} type="button">
                <Check size={16} aria-hidden="true" />
                Save changes
              </button>
              <button className="icon-button danger" onClick={onDelete} title="Delete note" type="button">
                <Trash2 size={17} aria-hidden="true" />
              </button>
            </div>
          </div>
        </>
      ) : (
        <p>{note.body}</p>
      )}
      <p className="note-meta">
        {note.report_date ? `Report ${note.report_date} - ` : ""}Created {formatDateTime(note.created_at)}
      </p>
    </section>
  );
}

function NotesView() {
  const { error: stocksError, stocks } = useNoteStocks();
  const [filters, setFilters] = useState(defaultReportFilters);
  const [stockSearch, setStockSearch] = useState("");
  const [selectedStock, setSelectedStock] = useState(null);
  const [resolvedFilter, setResolvedFilter] = useState("all");
  const [notes, setNotes] = useState([]);
  const [payload, setPayload] = useState({ total: 0, page_size: 10 });
  const [page, setPage] = useState(1);
  const [selectedNote, setSelectedNote] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [showAddNote, setShowAddNote] = useState(false);
  const [showGrouped, setShowGrouped] = useState(false);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const filteredStocks = stocks.filter((stock) => stockMatchesSearch(stock, stockSearch)).slice(0, 8);
  const totalPages = Math.max(1, Math.ceil((payload.total || 0) / (payload.page_size || 10)));

  const loadNotes = useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const query = new URLSearchParams({
        date_from: filters.date_from,
        date_to: filters.date_to,
        page: String(page),
        page_size: "10",
      });
      if (selectedStock?.stock_id) {
        query.set("stock_id", selectedStock.stock_id);
      }
      if (resolvedFilter !== "all") {
        query.set("is_resolved", resolvedFilter === "resolved" ? "true" : "false");
      }
      const payload = await requestJson(`/api/notes?${query.toString()}`, { method: "GET" });
      setNotes(payload.items ?? []);
      setPayload(payload);
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load notes.");
      setStatus("error");
    }
  }, [filters.date_from, filters.date_to, page, resolvedFilter, selectedStock?.stock_id]);

  useEffect(() => {
    loadNotes();
  }, [loadNotes]);

  const updateFilter = (key, value) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };

  const updateNote = async (note, patch) => {
    setError("");
    const optimisticNote = { ...note, ...patch };
    setNotes((current) => current.map((item) => (item.id === note.id ? optimisticNote : item)));
    setSelectedNote((current) => (current?.id === note.id ? optimisticNote : current));
    try {
      const payload = await requestJson(`/api/notes/${note.id}`, {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      const serverVisible =
        resolvedFilter === "all" ||
        (resolvedFilter === "resolved" && payload.note.is_resolved) ||
        (resolvedFilter === "open" && !payload.note.is_resolved);
      setNotes((current) =>
        serverVisible
          ? current.some((item) => item.id === note.id)
            ? current.map((item) => (item.id === note.id ? payload.note : item))
            : [payload.note, ...current]
          : current.filter((item) => item.id !== note.id),
      );
      setSelectedNote((current) => (current?.id === note.id ? payload.note : current));
      return true;
    } catch (err) {
      const originalVisible =
        resolvedFilter === "all" ||
        (resolvedFilter === "resolved" && note.is_resolved) ||
        (resolvedFilter === "open" && !note.is_resolved);
      setNotes((current) =>
        originalVisible
          ? current.some((item) => item.id === note.id)
            ? current.map((item) => (item.id === note.id ? note : item))
            : [note, ...current]
          : current.filter((item) => item.id !== note.id),
      );
      setSelectedNote((current) => (current?.id === note.id ? note : current));
      setError(err instanceof Error ? err.message : "Unable to update note.");
      return false;
    }
  };

  const deleteNote = async (note) => {
    setError("");
    try {
      await requestJson(`/api/notes/${note.id}`, { method: "DELETE" });
      setNotes((current) => current.filter((item) => item.id !== note.id));
      setSelectedNote(null);
      if (notes.length <= 1 && page > 1) {
        setPage((current) => Math.max(1, current - 1));
      } else {
        await loadNotes();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete note.");
    }
  };

  return (
    <section className="reports-view">
      <div className="reports-toolbar notes-toolbar">
        <div>
          <p className="eyebrow">Notes archive</p>
          <h2>Saved notes</h2>
        </div>
        <div className="notes-toolbar-side">
          <div className="report-filters notes-filters">
            <div className="company-filter">
              <label className="report-date-field">
                Company
                <div className="date-input-shell">
                  <input onChange={(event) => setStockSearch(event.target.value)} placeholder={selectedStock ? selectedStock.symbol : "All companies"} value={stockSearch} />
                  {selectedStock ? (
                    <button className="combo-icon-button" onClick={() => { setSelectedStock(null); setStockSearch(""); setPage(1); }} title="Clear company" type="button">
                      <X size={16} aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
              </label>
              {stockSearch.trim() ? (
                <div className="company-filter-menu">
                  {filteredStocks.map((stock) => (
                    <button key={stock.stock_id} onClick={() => { setSelectedStock(stock); setStockSearch(""); setPage(1); }} type="button">
                      <img className="stock-logo" {...stockLogoProps(stock.logo_url)} alt="" />
                      <span>{stock.symbol}</span>
                      <small>{stock.company_name}</small>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <ReportDateField label="From" value={filters.date_from} onChange={(value) => updateFilter("date_from", value)} />
            <ReportDateField label="To" value={filters.date_to} onChange={(value) => updateFilter("date_to", value)} />
          </div>
          <div className="notes-top-actions">
            <button className="primary-button compact-button grouped-view-button" onClick={() => setShowAddNote(true)} type="button">
              <Plus size={15} aria-hidden="true" />
              Add note
            </button>
            <button className="secondary-button compact-button grouped-view-button" disabled={!notes.length} onClick={() => setShowGrouped(true)} type="button">
              <FileText size={15} aria-hidden="true" />
              Grouped view
            </button>
            <div className="resolved-filter" aria-label="Resolved filter">
              {[
                ["all", "All"],
                ["open", "Open"],
                ["resolved", "Resolved"],
              ].map(([value, label]) => (
                <button
                  className={resolvedFilter === value ? "resolved-filter-button active" : "resolved-filter-button"}
                  key={value}
                  onClick={() => { setResolvedFilter(value); setPage(1); }}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {stocksError ? <p className="error">{stocksError}</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <div className="reports-list-panel">
        <div className="table-shell">
          <table className="reports-table notes-table">
            <colgroup>
              <col className="notes-company-col" />
              <col className="notes-body-col" />
              <col className="notes-created-col" />
              <col className="notes-resolved-col" />
              <col className="notes-actions-col" />
            </colgroup>
            <thead>
              <tr>
                <th>Company</th>
                <th>Note</th>
                <th>Created at</th>
                <th>Resolved</th>
                <th className="actions-cell">Actions</th>
              </tr>
            </thead>
            <tbody>
              {notes.length ? (
                notes.map((note) => (
                  <tr key={note.id} onClick={() => setSelectedNote(note)}>
                    <td>
                      <div className="stock-cell">
                        <img className="stock-logo" {...stockLogoProps(note.logo_url)} alt="" />
                        <div>
                          <strong>{note.symbol}</strong>
                          <span>{note.company_name}</span>
                        </div>
                      </div>
                    </td>
                    <td className="note-preview-cell">{note.body}</td>
                    <td>{formatDateTime(note.created_at)}</td>
                    <td>
                      <ReportToggle
                        checked={note.is_resolved}
                        offLabel="Open"
                        onChange={(next) => updateNote(note, { is_resolved: next })}
                        onLabel="Resolved"
                      />
                    </td>
                    <td className="actions-cell">
                      <button className="icon-button" onClick={(event) => { event.stopPropagation(); setSelectedNote(note); }} title="Edit note" type="button">
                        <Pencil size={17} aria-hidden="true" />
                      </button>
                      <button className="icon-button danger" onClick={(event) => { event.stopPropagation(); setDeleteTarget(note); }} title="Delete note" type="button">
                        <Trash2 size={17} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="empty-table" colSpan={5}>
                    {status === "loading" ? "Loading notes..." : "No notes found for this filter."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="pagination-row">
          <button className="secondary-button compact-button" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} type="button">
            <ChevronLeft size={16} aria-hidden="true" />
            Previous
          </button>
          <span>Page {page} of {totalPages}</span>
          <button className="secondary-button compact-button" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)} type="button">
            Next
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {selectedNote ? (
        <SingleNoteModal
          note={selectedNote}
          onClose={() => setSelectedNote(null)}
          onDelete={() => setDeleteTarget(selectedNote)}
          onSave={async (patch) => {
            const saved = await updateNote(selectedNote, patch);
            if (saved) {
              setSelectedNote(null);
            }
          }}
        />
      ) : null}
      {deleteTarget ? (
        <ConfirmDialog
          item={deleteTarget}
          message="This removes the note from your notes."
          onCancel={() => setDeleteTarget(null)}
          onConfirm={async () => {
            await deleteNote(deleteTarget);
            setDeleteTarget(null);
          }}
          title={`Delete note for ${deleteTarget.symbol}?`}
        />
      ) : null}
      {showAddNote ? (
        <NoteFormModal
          onClose={() => setShowAddNote(false)}
          onSaved={() => {
            setShowAddNote(false);
            if (page === 1) {
              loadNotes();
            } else {
              setPage(1);
            }
          }}
        />
      ) : null}
      {showGrouped ? <GroupedNotesModal notes={notes} onClose={() => setShowGrouped(false)} /> : null}
    </section>
  );
}

function SingleNoteModal({ note, onClose, onDelete, onSave }) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal-panel note-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">Note</p>
            <h2>{note.symbol}</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="Close" type="button">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <NoteCard editable largeEditor note={note} onDelete={onDelete} onSave={onSave} />
      </section>
    </div>
  );
}

function GroupedNotesModal({ notes, onClose }) {
  const grouped = notes.reduce((groups, note) => {
    const key = note.report_date || String(note.created_at).slice(0, 10);
    return { ...groups, [key]: [...(groups[key] ?? []), note] };
  }, {});

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal-panel note-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">Grouped view</p>
            <h2>Notes by date</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="Close" type="button">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="notes-stack grouped-notes-stack">
          {Object.entries(grouped).map(([date, items]) => (
            <section className="note-group" key={date}>
              <h3>{date}</h3>
              {items.map((note) => (
                <NoteCard editable={false} key={note.id} note={note} />
              ))}
            </section>
          ))}
        </div>
      </section>
    </div>
  );
}

function defaultResearchWindow() {
  const today = new Date();
  const start = new Date(today);
  start.setDate(today.getDate() - 30);
  return {
    date_from: dateInputValue(start),
    date_to: dateInputValue(today),
  };
}

function defaultResearchHistoryFilters() {
  const today = new Date();
  const start = new Date(today);
  start.setDate(today.getDate() - 30);
  return {
    date_from: dateInputValue(start),
    date_to: dateInputValue(today),
    stock_query: "",
    research_type: "",
  };
}

function researchRelationshipForStock(stock, portfolioItems, watchlistItems) {
  const symbol = String(stock?.symbol || "").trim().toUpperCase();
  if (!symbol) {
    return "new";
  }
  if (portfolioItems.some((item) => String(item.symbol || "").trim().toUpperCase() === symbol)) {
    return "portfolio";
  }
  if (watchlistItems.some((item) => String(item.symbol || "").trim().toUpperCase() === symbol)) {
    return "watchlist";
  }
  return "new";
}

function defaultResearchTypeForRelationship(relationship) {
  if (relationship === "portfolio") {
    return "portfolio_check";
  }
  if (relationship === "watchlist") {
    return "watchlist_check";
  }
  return "company_primer";
}

function ResearchView({ portfolioItems = [], watchlistItems = [], onAddToWatchlist, onEditItem, onMoveToPortfolio }) {
  const [researchMode, setResearchMode] = useState("new");
  const [search, setSearch] = useState("");
  const [results, setResults] = useState([]);
  const [selectedStock, setSelectedStock] = useState(null);
  const [researchType, setResearchType] = useState("company_primer");
  const [filters, setFilters] = useState(defaultResearchWindow);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [payload, setPayload] = useState(null);
  const [showNoteForm, setShowNoteForm] = useState(false);
  const [shareTarget, setShareTarget] = useState(null);
  const [generatedNotes, setGeneratedNotes] = useState([]);
  const [generatedNotesRevision, setGeneratedNotesRevision] = useState(0);
  const [generatedNotesError, setGeneratedNotesError] = useState("");
  const selectedRelationship = useMemo(
    () => researchRelationshipForStock(selectedStock, portfolioItems, watchlistItems),
    [portfolioItems, selectedStock, watchlistItems],
  );

  useEffect(() => {
    setResearchType(defaultResearchTypeForRelationship(selectedRelationship));
  }, [selectedRelationship, selectedStock?.symbol]);

  useEffect(() => {
    if (search.trim().length < 1 || selectedStock) {
      setResults([]);
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      setError("");
      try {
        const response = await requestJson(`/api/stocks/search?q=${encodeURIComponent(search.trim())}`, { method: "GET" });
        setResults(response.results ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed.");
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search, selectedStock]);

  const runResearch = async () => {
    if (!selectedStock) {
      setError("Choose a company first.");
      return;
    }
    setStatus("loading");
    setError("");
    setPayload(null);
    try {
      const response = await requestJson("/api/research/company", {
        method: "POST",
        timeoutMs: 60000,
        body: JSON.stringify({
          symbol: selectedStock.symbol,
          company_name: selectedStock.company_name,
          date_from: filters.date_from,
          date_to: filters.date_to,
          research_type: selectedRelationship === "new" ? "company_primer" : researchType,
        }),
      });
      setPayload(response);
      setStatus("ready");
    } catch (err) {
      setStatus("error");
      setError(err?.name === "AbortError" ? "Research timed out after 60 seconds. Try a shorter window or run it again." : err instanceof Error ? err.message : "Unable to run research.");
    }
  };

  const resetCompany = () => {
    setSelectedStock(null);
    setPayload(null);
    setSearch("");
  };

  const modeLabel = payload?.mode === "portfolio" ? "Portfolio thesis check" : payload?.mode === "watchlist" ? "Watchlist entry check" : "Company primer";
  const payloadRelationship = payload?.relationship ?? payload?.mode;
  const generatedResearchItem = researchItemFromPayload(payload);
  const canAddNote = Boolean(generatedResearchItem?.stock_id);
  const showResearchTypeSwitch = Boolean(selectedStock) && selectedRelationship !== "new";
  const researchTypeOptions = selectedRelationship === "portfolio"
    ? [["portfolio_check", "Portfolio check"], ["company_primer", "Company primer"]]
    : [["watchlist_check", "Watchlist check"], ["company_primer", "Company primer"]];

  useEffect(() => {
    const researchItemId = generatedResearchItem?.id;
    if (!researchItemId) {
      setGeneratedNotes([]);
      setGeneratedNotesError("");
      return undefined;
    }
    let ignore = false;
    const loadGeneratedNotes = async () => {
      setGeneratedNotesError("");
      try {
        const response = await requestJson(`/api/notes?research_item_id=${encodeURIComponent(researchItemId)}&page_size=100`, { method: "GET" });
        if (!ignore) {
          setGeneratedNotes(response.items ?? []);
        }
      } catch (err) {
        if (!ignore) {
          setGeneratedNotesError(err instanceof Error ? err.message : "Unable to load research notes.");
        }
      }
    };
    loadGeneratedNotes();
    return () => {
      ignore = true;
    };
  }, [generatedResearchItem?.id, generatedNotesRevision]);

  return (
    <section className="research-view">
      <div className="view-tabs compact-tabs">
        <button className={researchMode === "new" ? "view-tab active" : "view-tab"} onClick={() => setResearchMode("new")} type="button">
          New research
        </button>
        <button className={researchMode === "history" ? "view-tab active" : "view-tab"} onClick={() => setResearchMode("history")} type="button">
          History
        </button>
      </div>
      {researchMode === "history" ? <ResearchHistoryView /> : (
      <>
      <div className="reports-toolbar research-toolbar">
        <div>
          <p className="eyebrow">Company research</p>
          <h2>Research workspace</h2>
        </div>
        <div className="research-controls">
          <div className="research-company-search">
            <label className="research-search-label">
              Company
              <div className="search-input research-search-input">
                <Search size={18} aria-hidden="true" />
                <input
                  onChange={(event) => {
                    setSelectedStock(null);
                    setSearch(event.target.value);
                  }}
                  placeholder={selectedStock ? selectedStock.symbol : "Search company"}
                  value={selectedStock ? `${selectedStock.symbol} - ${selectedStock.company_name}` : search}
                />
                {selectedStock ? (
                  <button className="combo-icon-button" onClick={resetCompany} title="Clear company" type="button">
                    <X size={16} aria-hidden="true" />
                  </button>
                ) : null}
              </div>
            </label>
            {results.length ? (
              <div className="search-results research-search-results">
                {results.map((result) => (
                  <button
                    className="search-result"
                    key={`${result.symbol}-${result.exchange || ""}`}
                    onClick={() => {
                      setSelectedStock(result);
                      setSearch("");
                    }}
                    type="button"
                  >
                    <img className="stock-logo" {...stockLogoProps(result.logo_url)} alt="" />
                    <div className="stock-search-copy">
                      <div className="stock-title-row">
                        <strong>{result.symbol}</strong>
                        {result.exchange ? <span className="exchange-badge">{result.exchange}</span> : null}
                      </div>
                      <span>{result.company_name}</span>
                    </div>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="research-date-actions">
            <div className="research-date-row">
              <ReportDateField label="From" value={filters.date_from} onChange={(value) => setFilters((current) => ({ ...current, date_from: value }))} />
              <ReportDateField label="To" value={filters.date_to} onChange={(value) => setFilters((current) => ({ ...current, date_to: value }))} />
            </div>
            <div className="research-action-row">
              {showResearchTypeSwitch ? (
                <div className="research-type-switch" aria-label="Research type">
                  {researchTypeOptions.map(([value, label]) => (
                    <button className={researchType === value ? "active" : ""} key={value} onClick={() => setResearchType(value)} type="button">
                      {label}
                    </button>
                  ))}
                </div>
              ) : null}
              <button className="primary-button compact-button research-run-button" disabled={status === "loading"} onClick={runResearch} type="button">
                <Sparkles size={16} aria-hidden="true" />
                {status === "loading" ? "Researching..." : "Run research"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {status === "idle" ? <p className="muted">Choose a company to run a thesis check, entry condition check, or company primer.</p> : null}
      {status === "loading" ? (
        <div className="generating-state research-loading">
          <Sparkles size={22} aria-hidden="true" />
          <p>Building focused research...</p>
        </div>
      ) : null}
      {payload ? (
        <div className="research-result">
          <div className="research-result-header">
            <div className="selected-stock">
              <img className="stock-logo large" {...stockLogoProps(payload.stock.logo_url)} alt="" />
              <div>
                <div className="stock-title-row">
                  <strong>{payload.stock.symbol}</strong>
                  <span className="exchange-badge">{modeLabel}</span>
                </div>
                <span>{payload.stock.company_name}</span>
              </div>
            </div>
            <div className="toolbar-actions">
              {canAddNote ? (
                <button className="primary-button compact-button" onClick={() => setShowNoteForm(true)} type="button">
                  <Plus size={16} aria-hidden="true" />
                  Add note
                </button>
              ) : null}
              {generatedResearchItem ? (
                <button className="secondary-button compact-button" onClick={() => setShareTarget(generatedResearchItem)} type="button">
                  <Share2 size={16} aria-hidden="true" />
                  Share research
                </button>
              ) : null}
              {payload.mode === "portfolio" ? (
                <button className="secondary-button compact-button" onClick={() => onEditItem("portfolio", payload.stock.stock_id)} type="button">
                  <Pencil size={16} aria-hidden="true" />
                  Edit thesis
                </button>
              ) : null}
              {payload.mode === "watchlist" ? (
                <>
                  <button className="secondary-button compact-button" onClick={() => onEditItem("watchlist", payload.stock.stock_id)} type="button">
                    <Pencil size={16} aria-hidden="true" />
                    Edit watchlist
                  </button>
                  <button className="secondary-button compact-button" onClick={() => onMoveToPortfolio(payload.stock.stock_id)} type="button">
                    <MoveRight size={16} aria-hidden="true" />
                    Move to portfolio
                  </button>
                </>
              ) : null}
              {payload.mode === "new" && payloadRelationship === "new" ? (
                <button className="primary-button compact-button" onClick={() => onAddToWatchlist(payload.stock)} type="button">
                  <Plus size={16} aria-hidden="true" />
                  Add to Watchlist
                </button>
              ) : null}
            </div>
          </div>
          <ResearchResultContent payload={payload} />
          {generatedNotesError ? <p className="error">{generatedNotesError}</p> : null}
          {generatedNotes.length ? (
            <ResearchNotesSection notes={generatedNotes} />
          ) : null}
        </div>
      ) : null}
      {showNoteForm ? (
        <NoteFormModal
          initialStock={{
            stock_id: payload.stock.stock_id,
            symbol: payload.stock.symbol,
            company_name: payload.stock.company_name,
            logo_url: payload.stock.logo_url,
            list_name: payloadRelationship,
          }}
          researchItem={generatedResearchItem}
          onClose={() => setShowNoteForm(false)}
          onSaved={() => {
            setShowNoteForm(false);
            setGeneratedNotesRevision((current) => current + 1);
          }}
        />
      ) : null}
      {shareTarget ? (
        <ShareResearchModal
          item={shareTarget}
          onClose={() => setShareTarget(null)}
          onShared={() => setShareTarget(null)}
        />
      ) : null}
      </>
      )}
    </section>
  );
}

function researchTypeLabel(value) {
  const labels = {
    portfolio_check: "Portfolio check",
    watchlist_check: "Watchlist check",
    company_primer: "Company primer",
  };
  return labels[value] ?? researchHumanLabel(value || "Research");
}

function researchStockFromItem(item) {
  return {
    stock_id: item.stock_id,
    symbol: item.symbol,
    company_name: item.company_name,
    logo_url: item.logo_url,
    list_name: researchTypeLabel(item.research_type),
  };
}

function researchItemFromPayload(payload) {
  if (!payload?.research_item_id || !payload?.stock) {
    return null;
  }
  return {
    id: payload.research_item_id,
    stock_id: payload.stock.stock_id,
    symbol: payload.stock.symbol,
    company_name: payload.stock.company_name,
    logo_url: payload.stock.logo_url,
    research_type: researchTypeForMode(payload.mode),
    signal: researchSignalFromPayload(payload),
    body: payload,
  };
}

function researchTypeForMode(mode) {
  return {
    portfolio: "portfolio_check",
    watchlist: "watchlist_check",
    new: "company_primer",
  }[mode] ?? "company_primer";
}

function researchSignalFromPayload(payload) {
  const research = payload?.research ?? {};
  return research.signal ?? research.watchlist_suitability ?? null;
}

function ResearchHistoryView() {
  const [filters, setFilters] = useState(defaultResearchHistoryFilters);
  const [page, setPage] = useState(1);
  const [payload, setPayload] = useState({ items: [], total: 0, page_size: 10 });
  const [selectedItem, setSelectedItem] = useState(null);
  const [notesModal, setNotesModal] = useState(null);
  const [noteFormItem, setNoteFormItem] = useState(null);
  const [shareTarget, setShareTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [notesRevision, setNotesRevision] = useState(0);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const totalPages = Math.max(1, Math.ceil((payload.total || 0) / (payload.page_size || 10)));

  const loadHistory = useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const query = new URLSearchParams({
        date_from: filters.date_from,
        date_to: filters.date_to,
        page: String(page),
        page_size: "10",
      });
      if (filters.stock_query.trim()) {
        query.set("stock_query", filters.stock_query.trim());
      }
      if (filters.research_type) {
        query.set("research_type", filters.research_type);
      }
      const nextPayload = await requestJson(`/api/research-items?${query.toString()}`, { method: "GET" });
      setPayload(nextPayload);
      setStatus("ready");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Unable to load research history.");
    }
  }, [filters.date_from, filters.date_to, filters.research_type, filters.stock_query, page]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const updateFilter = (key, value) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };

  const openItem = async (item) => {
    setError("");
    try {
      const detail = await requestJson(`/api/research-items/${item.id}`, { method: "GET" });
      setSelectedItem(detail.item);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load research detail.");
    }
  };

  const deleteItem = async (item) => {
    setError("");
    try {
      await requestJson(`/api/research-items/${item.id}`, { method: "DELETE" });
      setDeleteTarget(null);
      if (selectedItem?.id === item.id) {
        setSelectedItem(null);
      }
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete research.");
    }
  };

  return (
    <section className="reports-view research-history-view">
      <div className="reports-toolbar research-history-toolbar">
        <div>
          <p className="eyebrow">Research archive</p>
          <h2>Saved research</h2>
        </div>
        <div className="research-history-filters">
          <div className="research-history-filter-row">
            <label className="research-search-label research-history-company-filter">
              Company
              <div className="search-input research-search-input">
                <Search size={18} aria-hidden="true" />
                <input onChange={(event) => updateFilter("stock_query", event.target.value)} placeholder="Symbol or name" value={filters.stock_query} />
              </div>
            </label>
            <ReportDateField label="From" value={filters.date_from} onChange={(value) => updateFilter("date_from", value)} />
            <ReportDateField label="To" value={filters.date_to} onChange={(value) => updateFilter("date_to", value)} />
          </div>
          <div className="research-history-filter-row">
            <div className="research-type-filter">
              {[
                ["", "All"],
                ["portfolio_check", "Portfolio"],
                ["watchlist_check", "Watchlist"],
                ["company_primer", "Primer"],
              ].map(([value, label]) => (
                <button className={filters.research_type === value ? "active" : ""} key={value || "all"} onClick={() => updateFilter("research_type", value)} type="button">
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}

      <div className="research-history-table-panel">
        <div className="table-shell">
          <table className="reports-table research-history-table">
            <colgroup>
              <col className="research-history-company-col" />
              <col className="research-history-type-col" />
              <col className="research-history-signal-col" />
              <col className="report-created-col" />
              <col className="report-notes-col" />
              <col className="research-history-actions-col" />
            </colgroup>
            <thead>
              <tr>
                <th>Company</th>
                <th>Type</th>
                <th>Signal</th>
                <th>Created at</th>
                <th className="actions-cell">Notes</th>
                <th className="actions-cell">Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.items.length ? (
                payload.items.map((item) => (
                  <tr key={item.id} onClick={() => openItem(item)}>
                    <td>
                      <div className="stock-cell">
                        <img className="stock-logo" {...stockLogoProps(item.logo_url)} alt="" />
                        <div>
                          <strong>{item.symbol}</strong>
                          <span>{item.company_name}</span>
                        </div>
                      </div>
                    </td>
                    <td><span className="status-pill">{researchTypeLabel(item.research_type)}</span></td>
                    <td><span className="research-signal-pill">{researchHumanLabel(item.signal || "Unknown")}</span></td>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td className="actions-cell">
                      <span className="notes-count-pill" title={`${item.note_count ?? 0} notes`}>{item.note_count ?? 0}</span>
                      <button className="icon-button" onClick={(event) => { event.stopPropagation(); setNotesModal({ researchItem: item, mode: "view" }); }} title="View notes" type="button">
                        <Eye size={17} aria-hidden="true" />
                      </button>
                      <button className="icon-button" onClick={(event) => { event.stopPropagation(); setNotesModal({ researchItem: item, mode: "edit" }); }} title="Edit notes" type="button">
                        <Pencil size={17} aria-hidden="true" />
                      </button>
                      <button className="icon-button" onClick={(event) => { event.stopPropagation(); setNoteFormItem(item); }} title="Add note" type="button">
                        <Plus size={17} aria-hidden="true" />
                      </button>
                    </td>
                  <td className="actions-cell">
                      <button className="icon-button" onClick={(event) => { event.stopPropagation(); setShareTarget(item); }} title="Share research" type="button">
                        <Share2 size={17} aria-hidden="true" />
                      </button>
                      <button className="icon-button danger" onClick={(event) => { event.stopPropagation(); setDeleteTarget(item); }} title="Delete research" type="button">
                        <Trash2 size={17} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="empty-table" colSpan={6}>
                    {status === "loading" ? "Loading research..." : "No research found for these filters."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="pagination-row">
          <button className="secondary-button compact-button" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} type="button">
            <ChevronLeft size={16} aria-hidden="true" />
            Previous
          </button>
          <span>Page {page} of {totalPages}</span>
          <button className="secondary-button compact-button" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)} type="button">
            Next
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {selectedItem?.body ? (
        <ResearchPreviewModal
          item={selectedItem}
          revision={notesRevision}
          onAddNote={() => setNoteFormItem(selectedItem)}
          onShare={() => setShareTarget(selectedItem)}
          onClose={() => setSelectedItem(null)}
        />
      ) : null}
      {notesModal ? (
        <ReportNotesModal
          mode={notesModal.mode}
          researchItem={notesModal.researchItem}
          revision={notesRevision}
          onAddNote={() => setNoteFormItem(notesModal.researchItem)}
          onChanged={loadHistory}
          onClose={() => setNotesModal(null)}
        />
      ) : null}
      {noteFormItem ? (
        <NoteFormModal
          initialStock={researchStockFromItem(noteFormItem)}
          researchItem={noteFormItem}
          onClose={() => setNoteFormItem(null)}
          onSaved={() => {
            setNoteFormItem(null);
            setNotesRevision((current) => current + 1);
            loadHistory();
          }}
        />
      ) : null}
      {deleteTarget ? (
        <ConfirmDialog
          item={deleteTarget}
          message="This removes the saved research and its linked notes."
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => deleteItem(deleteTarget)}
          title={`Delete research for ${deleteTarget.symbol}?`}
        />
      ) : null}
      {shareTarget ? (
        <ShareResearchModal
          item={shareTarget}
          onClose={() => setShareTarget(null)}
          onShared={() => setShareTarget(null)}
        />
      ) : null}
    </section>
  );
}

function ResearchPreviewModal({ item, revision = 0, onAddNote, onShare, onClose }) {
  const [notes, setNotes] = useState([]);
  const [notesStatus, setNotesStatus] = useState("loading");
  const [notesError, setNotesError] = useState("");

  useEffect(() => {
    let ignore = false;
    const loadNotes = async () => {
      setNotesStatus("loading");
      setNotesError("");
      try {
        const payload = await requestJson(`/api/notes?research_item_id=${encodeURIComponent(item.id)}&page_size=100`, { method: "GET" });
        if (!ignore) {
          setNotes(payload.items ?? []);
          setNotesStatus("ready");
        }
      } catch (err) {
        if (!ignore) {
          setNotesError(err instanceof Error ? err.message : "Unable to load research notes.");
          setNotesStatus("error");
        }
      }
    };
    loadNotes();
    return () => {
      ignore = true;
    };
  }, [item.id, revision]);

  return (
    <div className="modal-backdrop report-preview-backdrop" onMouseDown={onClose}>
      <section className="modal-panel research-preview-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="report-modal-header">
          <div className="selected-stock no-margin">
            <img className="stock-logo large" {...stockLogoProps(item.logo_url)} alt="" />
            <div>
              <p className="eyebrow">{researchTypeLabel(item.research_type)}</p>
              <h2>{item.symbol} research</h2>
            </div>
          </div>
          <div className="modal-header-actions">
            <button className="primary-button compact-button" onClick={onAddNote} type="button">
              <Plus size={16} aria-hidden="true" />
              Add note
            </button>
            <button className="secondary-button compact-button" onClick={onShare} type="button">
              <Share2 size={16} aria-hidden="true" />
              Share research
            </button>
            <button className="icon-button" onClick={onClose} title="Close" type="button">
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
        <div className="research-preview-content">
          <ResearchResultContent payload={item.body} />
          {notesError ? <p className="error">{notesError}</p> : null}
          {notes.length ? (
            <ResearchNotesSection notes={notes} />
          ) : null}
        </div>
      </section>
    </div>
  );
}

function ResearchNotesSection({ notes }) {
  return (
    <section className="research-preview-notes">
      <div className="research-card-header">
        <h3>Research notes</h3>
      </div>
      <div className="notes-stack research-preview-notes-stack">
        {notes.map((note) => <NoteCard editable={false} key={note.id} note={note} />)}
      </div>
    </section>
  );
}

function ShareResearchModal({ item, onClose, onShared }) {
  const [recipientEmail, setRecipientEmail] = useState("");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");

  const share = async () => {
    setStatus("sending");
    setError("");
    try {
      await requestJson(`/api/research-items/${item.id}/share`, {
        method: "POST",
        body: JSON.stringify({
          recipient_email: recipientEmail,
          message,
        }),
      });
      await onShared();
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Unable to share research.");
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal-panel share-research-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">Share research</p>
            <h2>{item.symbol}</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="Close" type="button">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="note-form-grid">
          <label>
            Recipient email
            <input autoFocus onChange={(event) => setRecipientEmail(event.target.value)} placeholder="friend@example.com" type="email" value={recipientEmail} />
          </label>
          <label>
            Message
            <textarea onChange={(event) => setMessage(event.target.value)} placeholder="Add a short note..." rows={5} value={message} />
          </label>
          <p className="muted">The email will include this research along with your research notes.</p>
        </div>
        {error ? <p className="error">{error}</p> : null}
        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose} type="button">
            Cancel
          </button>
          <button className="primary-button" disabled={status === "sending" || !recipientEmail.trim()} onClick={share} type="button">
            <Share2 size={18} aria-hidden="true" />
            {status === "sending" ? "Sending..." : "Share research"}
          </button>
        </div>
      </section>
    </div>
  );
}

function formatCompactNumber(value) {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "N/A";
  }
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: number >= 100 ? 0 : 2,
    notation: Math.abs(number) >= 1000000 ? "compact" : "standard",
  }).format(number);
}

function formatMetricPercent(value) {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "N/A";
  }
  return `${number.toFixed(1)}%`;
}

function metricValue(key, value) {
  if (key.includes("growth")) {
    return formatMetricPercent(value);
  }
  if (key.includes("margin") || key === "roe_pct" || key.includes("yield")) {
    return formatMetricPercent(value);
  }
  if (key === "market_cap") {
    return formatCompactNumber(value);
  }
  if (key === "price" || key === "year_high" || key === "year_low") {
    if (value === null || value === undefined || value === "") {
      return "N/A";
    }
    const number = Number(value);
    return Number.isFinite(number) ? `$${formatCompactNumber(number)}` : "N/A";
  }
  return formatCompactNumber(value);
}

function metricLabel(key) {
  const labels = {
    price: "Price",
    market_cap: "Market cap",
    pe: "P/E TTM",
    ps: "P/S TTM",
    ev_to_ebitda: "EV/EBITDA",
    fcf_yield_pct: "FCF yield",
    eps: "EPS",
    eps_growth_3y_pct: "EPS growth 3Y",
    eps_growth_5y_pct: "EPS growth 5Y",
    revenue_growth_3y_pct: "Revenue growth 3Y",
    eps_growth_next_year_pct: "EPS growth next year",
    revenue_per_share: "Revenue/share",
    fcf_per_share: "FCF/share",
    gross_margin_pct: "Gross margin",
    operating_margin_pct: "Operating margin",
    net_margin_pct: "Net margin",
    roe_pct: "ROE",
    debt_to_equity: "Debt/equity",
    year_high: "52W high",
    year_low: "52W low",
  };
  return labels[key] ?? researchHumanLabel(key);
}

function parseDateOnlyStrict(value) {
  const match = String(value || "").slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) {
    return null;
  }
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function formatDateOnly(value) {
  const date = parseDateOnlyStrict(value);
  if (!date) {
    return value ? String(value) : "N/A";
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function earningsReportLabel(report, index) {
  if (report.report_type === "fy") {
    return report.fiscal_year ? `FY ${report.fiscal_year}` : "Last FY";
  }
  const date = parseDateOnlyStrict(report.date);
  if (date) {
    return `Q${Math.floor(date.getMonth() / 3) + 1} ${date.getFullYear()}`;
  }
  return `Quarter ${index + 1}`;
}

function EarningsReportsPanel({ reports = [], nextEarningsDate }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const items = Array.isArray(reports) ? reports.filter(Boolean) : [];
  const activeReport = items[Math.min(activeIndex, Math.max(items.length - 1, 0))];

  useEffect(() => {
    if (activeIndex >= items.length) {
      setActiveIndex(0);
    }
  }, [activeIndex, items.length]);

  if (!items.length && !nextEarningsDate) {
    return null;
  }

  return (
    <div className="earnings-panel">
      <div className="earnings-panel-header">
        <div>
          <strong>Earnings reports</strong>
          <span>Next earnings: {nextEarningsDate ? formatDateOnly(nextEarningsDate) : "N/A"}</span>
        </div>
      </div>
      {items.length ? (
        <>
          <div className="earnings-tabs" role="tablist" aria-label="Earnings reports">
            {items.map((report, index) => (
              <button
                className={index === activeIndex ? "active" : ""}
                key={`${report.report_type || "q"}-${report.date || index}`}
                onClick={() => setActiveIndex(index)}
                type="button"
              >
                {earningsReportLabel(report, index)}
              </button>
            ))}
          </div>
          {activeReport ? (
            <div className="earnings-report-detail">
              <div className="earnings-report-date">
                <span>{activeReport.report_type === "fy" ? "Fiscal year report" : "Quarterly report"}</span>
                <strong>{formatDateOnly(activeReport.date)}</strong>
              </div>
              <div className="earnings-detail-grid">
                <div>
                  <span>EPS actual</span>
                  <strong>{activeReport.eps_actual === null || activeReport.eps_actual === undefined ? "N/A" : `$${formatCompactNumber(activeReport.eps_actual)}`}</strong>
                </div>
                <div>
                  <span>EPS est.</span>
                  <strong>{activeReport.eps_estimated === null || activeReport.eps_estimated === undefined ? "N/A" : `$${formatCompactNumber(activeReport.eps_estimated)}`}</strong>
                </div>
                <div>
                  <span>Revenue actual</span>
                  <strong>{activeReport.revenue_actual === null || activeReport.revenue_actual === undefined ? "N/A" : `$${formatCompactNumber(activeReport.revenue_actual)}`}</strong>
                </div>
                <div>
                  <span>Revenue est.</span>
                  <strong>{activeReport.revenue_estimated === null || activeReport.revenue_estimated === undefined ? "N/A" : `$${formatCompactNumber(activeReport.revenue_estimated)}`}</strong>
                </div>
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <p className="muted">No earnings reports available.</p>
      )}
    </div>
  );
}

function parseChartDate(value) {
  return new Date(String(value || "").replace(" ", "T"));
}

function formatChartDate(value, period) {
  const date = parseChartDate(value);
  if (Number.isNaN(date.getTime())) {
    return value || "";
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: period === "5Y" || period === "MAX" ? "numeric" : undefined });
}

function formatAxisDate(value, period) {
  const date = parseChartDate(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  if (period === "5Y" || period === "MAX") {
    return date.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function filterPriceHistory(dailyPoints, period) {
  if (!Array.isArray(dailyPoints) || !dailyPoints.length) {
    return [];
  }
  if (period === "MAX") {
    return dailyPoints;
  }
  const days = { "1W": 7, "1M": 31, "3M": 93, "6M": 186, "1Y": 370, "5Y": 365 * 5 + 10 }[period] ?? 370;
  const latest = parseChartDate(dailyPoints[dailyPoints.length - 1].date);
  const cutoff = new Date(latest);
  cutoff.setDate(latest.getDate() - days);
  return dailyPoints.filter((point) => parseChartDate(point.date) >= cutoff);
}

function StockPriceChart({ dailyPoints }) {
  const [period, setPeriod] = useState("6M");
  const [hoverIndex, setHoverIndex] = useState(null);
  const [tooltipSide, setTooltipSide] = useState("right");
  const visiblePoints = filterPriceHistory(dailyPoints, period);
  const width = 720;
  const height = 260;
  const left = 54;
  const right = 16;
  const top = 18;
  const bottom = 34;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  if (!visiblePoints.length) {
    return <div className="price-chart-empty">Price chart unavailable.</div>;
  }
  const closes = visiblePoints.map((point) => point.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const coordinate = (point, index) => {
    const x = left + (index / Math.max(1, visiblePoints.length - 1)) * plotWidth;
    const y = top + (1 - (point.close - min) / range) * plotHeight;
    return { x, y };
  };
  const path = visiblePoints
    .map((point, index) => {
      const { x, y } = coordinate(point, index);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const first = visiblePoints[0].close;
  const last = visiblePoints[visiblePoints.length - 1].close;
  const change = ((last / first) - 1) * 100;
  const yTicks = Array.from({ length: 4 }, (_, index) => max - (index / 3) * range);
  const xTickIndexes = Array.from(new Set([0, Math.floor((visiblePoints.length - 1) / 2), visiblePoints.length - 1]));
  const hovered = hoverIndex === null ? null : visiblePoints[hoverIndex];
  const hoveredCoord = hovered ? coordinate(hovered, hoverIndex) : null;
  const handleHover = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - bounds.left) / bounds.width) * width;
    const ratio = Math.min(1, Math.max(0, (svgX - left) / plotWidth));
    setTooltipSide(svgX > width * 0.72 ? "left" : "right");
    setHoverIndex(Math.round(ratio * (visiblePoints.length - 1)));
  };

  return (
    <div className="price-chart">
      <div className="price-chart-header">
        <div>
          <strong>${formatCompactNumber(last)}</strong>
          <span className={change >= 0 ? "chart-change positive" : "chart-change negative"}>
            {change >= 0 ? "+" : ""}{change.toFixed(1)}%
          </span>
        </div>
        <div className="chart-periods">
          {["1W", "1M", "3M", "6M", "1Y", "5Y"].map((item) => (
            <button className={period === item ? "active" : ""} key={item} onClick={() => setPeriod(item)} type="button">
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="price-chart-plot" onMouseLeave={() => setHoverIndex(null)} onMouseMove={handleHover}>
        {hovered && hoveredCoord ? (
          <div className={`chart-tooltip ${tooltipSide}`} style={{ left: `${(hoveredCoord.x / width) * 100}%` }}>
            <strong>${formatCompactNumber(hovered.close)}</strong>
            <span>{formatChartDate(hovered.date, period)}</span>
          </div>
        ) : null}
        <svg className="price-chart-svg" viewBox={`0 0 ${width} ${height}`}>
          {yTicks.map((tick) => {
            const y = top + (1 - (tick - min) / range) * plotHeight;
            return (
              <g key={tick}>
                <line className="chart-grid-line" x1={left} x2={width - right} y1={y} y2={y} />
                <text className="chart-axis-label" x={left - 10} y={y + 4} textAnchor="end">${formatCompactNumber(tick)}</text>
              </g>
            );
          })}
          {xTickIndexes.map((index) => {
            const point = visiblePoints[index];
            const { x } = coordinate(point, index);
            return (
              <text className="chart-axis-label" key={`${point.date}-${index}`} textAnchor={index === 0 ? "start" : index === visiblePoints.length - 1 ? "end" : "middle"} x={x} y={height - 8}>
                {formatAxisDate(point.date, period)}
              </text>
            );
          })}
          <line className="chart-axis-line" x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} />
          <line className="chart-axis-line" x1={left} x2={left} y1={top} y2={height - bottom} />
          <path d={path} fill="none" stroke="#f4c430" strokeLinecap="round" strokeWidth="3" />
          {hovered && hoveredCoord ? (
            <>
              <line className="chart-hover-line" x1={hoveredCoord.x} x2={hoveredCoord.x} y1={top} y2={height - bottom} />
              <circle className="chart-hover-point" cx={hoveredCoord.x} cy={hoveredCoord.y} r="4" />
            </>
          ) : null}
        </svg>
      </div>
    </div>
  );
}

function ResearchMarketSnapshot({ marketData }) {
  if (!marketData) {
    return null;
  }
  const metrics = marketData.metrics || {};
  const metricEntries = [
    "price",
    "market_cap",
    "pe",
    "ps",
    "ev_to_ebitda",
    "fcf_yield_pct",
    "eps",
    "revenue_growth_3y_pct",
    "eps_growth_3y_pct",
    "eps_growth_5y_pct",
    "revenue_per_share",
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
    "year_high",
    "year_low",
  ];
  return (
    <section className="research-market-panel">
      <div className="research-chart-panel">
        <StockPriceChart dailyPoints={marketData.price_history ?? []} />
      </div>
      <div className="research-metrics-panel">
        <div className="metric-grid">
          {metricEntries.map((key) => (
            <div className="metric-tile" key={key}>
              <span>{metricLabel(key)}</span>
              <strong>{metricValue(key, metrics[key])}</strong>
            </div>
          ))}
        </div>
        {marketData.latest_earnings?.source_url ? (
          <div className="earnings-source">
            <strong>Latest earnings</strong>
            <span>{marketData.latest_earnings.date || "Date unavailable"}</span>
            <div className="earnings-details">
              <span>EPS {formatCompactNumber(marketData.latest_earnings.eps)}</span>
              <span>Est. {formatCompactNumber(marketData.latest_earnings.eps_estimated)}</span>
              <span>Revenue {formatCompactNumber(marketData.latest_earnings.revenue)}</span>
            </div>
            <a href={marketData.latest_earnings.source_url} rel="noreferrer" target="_blank">Source</a>
          </div>
        ) : null}
        <EarningsReportsPanel reports={marketData.earnings_reports ?? []} nextEarningsDate={marketData.next_earnings_date} />
      </div>
    </section>
  );
}

function ResearchResultContent({ payload }) {
  const research = payload.research || {};
  if (payload.mode === "portfolio") {
    return (
      <div className="research-section-grid">
        <ResearchSignal label="Signal" value={research.signal} />
        <ResearchMarketSnapshot marketData={payload.market_data} />
        <ResearchList title="Executive summary" items={research.executive_summary} />
        <ResearchAssessmentList title="Thesis check" items={research.thesis_check} titleKey="field" />
        <ResearchArticleList title="Recent developments" items={research.recent_developments} />
        <ResearchList title="Risks to watch" items={research.risks_to_watch} />
        <ResearchList title="Suggested next steps" items={research.suggested_next_steps} />
      </div>
    );
  }
  if (payload.mode === "watchlist") {
    return (
      <div className="research-section-grid">
        <ResearchSignal label="Signal" value={research.signal} />
        <ResearchMarketSnapshot marketData={payload.market_data} />
        <ResearchList title="Executive summary" items={research.executive_summary} />
        <ResearchAssessmentList title="Entry conditions check" items={research.entry_conditions_check} titleKey="condition" />
        <ResearchArticleList title="Recent developments" items={research.recent_developments} />
        <ResearchList title="Still missing" items={research.still_missing} />
        <ResearchList title="Suggested next steps" items={research.suggested_next_steps} />
      </div>
    );
  }
  return (
    <div className="research-section-grid">
      <ResearchSignal label="Watchlist suitability" value={research.watchlist_suitability} />
      <ResearchMarketSnapshot marketData={payload.market_data} />
      <ResearchList title="Company overview" items={research.company_overview} />
      <ResearchList title="Business model" items={research.business_model} />
      <ResearchList title="Products and customers" items={research.products_and_customers} />
      <ResearchList title="Current situation" items={research.current_situation} />
      <ResearchList title="Future outlook" items={research.future_outlook} />
      <ResearchList title="Bull case" items={research.bull_case} />
      <ResearchList title="Bear case" items={research.bear_case} />
      <ResearchList title="What to understand next" items={research.what_to_understand_next} />
    </div>
  );
}

function researchHumanLabel(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function capitalizeFirst(value) {
  const text = String(value || "").trim();
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}` : "";
}

function stripInlineSourceDomains(value) {
  return String(value || "").replace(/\s*\(([a-z0-9.-]+\.[a-z]{2,})(?:\/[^)]*)?\)/gi, "");
}

function ResearchSignal({ label, value }) {
  const signalKey = String(value || "unknown").replaceAll("_", "-").toLowerCase();
  return (
    <section className={`research-card signal-card signal-${signalKey}`}>
      <div className="signal-card-copy">
        <p className="eyebrow">{label}</p>
        <h3>{researchHumanLabel(value || "Unknown")}</h3>
      </div>
      <div className="signal-orbit" aria-hidden="true">
        <Sparkles size={24} />
      </div>
    </section>
  );
}

function ResearchList({ title, items }) {
  return (
    <section className="research-card">
      <div className="research-card-header">
        <h3>{title}</h3>
      </div>
      {items?.length ? (
        <ul>
          {items.map((item, index) => (
            <li key={`${title}-${index}`}>
              <span className="research-list-index">{String(index + 1).padStart(2, "0")}</span>
              <p>{stripInlineSourceDomains(typeof item === "string" ? item : JSON.stringify(item))}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No material points returned.</p>
      )}
    </section>
  );
}

function ResearchAssessmentList({ title, items, titleKey }) {
  return (
    <section className="research-card">
      <div className="research-card-header">
        <h3>{title}</h3>
      </div>
      <div className="research-assessment-list">
        {items?.length ? (
          items.map((item, index) => (
            <div className="research-assessment" key={`${title}-${index}`}>
              <strong>{capitalizeFirst(item?.[titleKey]) || `Item ${index + 1}`}</strong>
              {item?.assessment ? <p>{stripInlineSourceDomains(item.assessment)}</p> : null}
              {Array.isArray(item?.evidence) && item.evidence.length ? (
                <ul>
                  {item.evidence.map((point, pointIndex) => {
                    const text = typeof point === "string" ? point : point?.text;
                    const sourceUrl = typeof point === "object" ? point?.source_url : "";
                    return (
                      <li key={`${title}-${index}-${pointIndex}`}>
                        {stripInlineSourceDomains(text)}
                        {sourceUrl ? (
                          <>
                            {" "}
                            <a href={sourceUrl} rel="noreferrer" target="_blank">Source</a>
                          </>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </div>
          ))
        ) : (
          <p className="muted">No checks returned.</p>
        )}
      </div>
    </section>
  );
}

function ResearchArticleList({ title, items }) {
  return (
    <section className="research-card">
      <div className="research-card-header">
        <h3>{title}</h3>
      </div>
      <div className="research-assessment-list">
        {items?.length ? (
          items.map((item, index) => (
            <div className="research-assessment" key={`${title}-${index}`}>
              <strong>{item?.headline || `Article ${index + 1}`}</strong>
              {item?.summary ? <p>{stripInlineSourceDomains(item.summary)}</p> : null}
              {item?.source_url ? (
                <a href={item.source_url} rel="noreferrer" target="_blank">
                  Full article
                </a>
              ) : null}
            </div>
          ))
        ) : (
          <p className="muted">No material articles returned.</p>
        )}
      </div>
    </section>
  );
}

function ReportSchedulePanel({ error, onChange, settings }) {
  const timezones = useMemo(() => timezoneOptions(settings.timezone), [settings.timezone]);
  return (
    <section className="schedule-panel">
      <div className="schedule-copy">
        <p className="eyebrow">Report delivery</p>
        <h2>Daily report schedule</h2>
      </div>
      <div className="schedule-controls">
        <ReportTimePicker value={settings.report_scheduled_at} onChange={(value) => onChange({ report_scheduled_at: value })} />
        <TimezoneCombobox
          options={timezones}
          value={settings.timezone}
          onChange={(value) => onChange({ timezone: value })}
        />
      </div>
      {error ? <p className="error schedule-error">{error}</p> : null}
    </section>
  );
}

function ReportTimePicker({ value, onChange }) {
  const options = useMemo(reportTimeOptions, []);
  const [draft, setDraft] = useState(value);
  const [open, setOpen] = useState(false);
  const inputRef = useRef(null);
  const optionsRef = useRef(null);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const activeOption = optionsRef.current?.querySelector("[data-active='true']");
    activeOption?.scrollIntoView({ block: "center" });
  }, [open, value]);

  const commit = (nextValue) => {
    const resolved = resolveTimeInput(nextValue);
    if (!resolved) {
      setDraft(value);
      setOpen(false);
      return;
    }
    setDraft(resolved);
    setOpen(false);
    if (resolved !== value) {
      onChange(resolved);
    }
  };

  return (
    <div className="schedule-field time-field">
      <span className="schedule-label">
        <Clock size={16} aria-hidden="true" />
        Time
      </span>
      <div className="custom-combobox">
        <input
          autoComplete="off"
          inputMode="numeric"
          onBlur={() => window.setTimeout(() => commit(draft), 120)}
          onChange={(event) => setDraft(event.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              commit(event.currentTarget.value);
            }
            if (event.key === "Escape") {
              setDraft(value);
              setOpen(false);
            }
          }}
          placeholder="08:00"
          ref={inputRef}
          value={draft}
        />
        <button
          className="combo-icon-button"
          onMouseDown={(event) => {
            event.preventDefault();
            setOpen((current) => !current);
            inputRef.current?.focus();
          }}
          title="Choose time"
          type="button"
        >
          <Clock size={16} aria-hidden="true" />
        </button>
        {open ? (
          <div className="custom-options time-options" ref={optionsRef}>
            {options.map((option) => (
              <button
                className={option === value ? "custom-option active" : "custom-option"}
                data-active={option === value ? "true" : undefined}
                key={option}
                onMouseDown={(event) => {
                  event.preventDefault();
                  commit(option);
                }}
                type="button"
              >
                {option}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TimezoneCombobox({ options, value, onChange }) {
  const [draft, setDraft] = useState(value);
  const [open, setOpen] = useState(false);
  const [filtering, setFiltering] = useState(false);
  const inputRef = useRef(null);
  const optionsRef = useRef(null);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  useEffect(() => {
    if (!open || filtering) {
      return;
    }
    const activeOption = optionsRef.current?.querySelector("[data-active='true']");
    activeOption?.scrollIntoView({ block: "center" });
  }, [filtering, open, value]);

  const filteredOptions = useMemo(() => {
    if (!filtering) {
      return options;
    }
    const search = normalizeTimezoneSearch(draft);
    if (!search) {
      return options;
    }
    return options.filter((timezone) => normalizeTimezoneSearch(timezone).includes(search));
  }, [draft, filtering, options, value]);

  const commit = (nextValue) => {
    const resolved = resolveTimezoneInput(nextValue, options);
    if (!resolved) {
      setDraft(value);
      setOpen(false);
      setFiltering(false);
      return;
    }
    setDraft(resolved);
    setOpen(false);
    setFiltering(false);
    if (resolved !== value) {
      onChange(resolved);
    }
  };

  return (
    <div className="schedule-field timezone-field">
      <span className="schedule-label">
        <Globe2 size={16} aria-hidden="true" />
        Timezone
      </span>
      <div className="custom-combobox">
        <input
          autoComplete="off"
          onBlur={() => window.setTimeout(() => commit(draft), 120)}
          onChange={(event) => {
            setDraft(event.target.value);
            setFiltering(true);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
            setFiltering(false);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              commit(event.currentTarget.value);
            }
            if (event.key === "Escape") {
              setDraft(value);
              setOpen(false);
              setFiltering(false);
            }
          }}
          ref={inputRef}
          value={draft}
        />
        <button
          className="combo-icon-button"
          onMouseDown={(event) => {
            event.preventDefault();
            setFiltering(false);
            setOpen((current) => !current);
            inputRef.current?.focus();
          }}
          title="Choose timezone"
          type="button"
        >
          <ChevronDown size={17} aria-hidden="true" />
        </button>
        {open ? (
          <div className="custom-options timezone-options" ref={optionsRef}>
            {filteredOptions.map((timezone) => (
              <button
                className={timezone === value ? "custom-option active" : "custom-option"}
                data-active={timezone === value ? "true" : undefined}
                key={timezone}
                onMouseDown={(event) => {
                  event.preventDefault();
                  commit(timezone);
                }}
                type="button"
              >
                {timezone}
              </button>
            ))}
            {!filteredOptions.length ? <div className="custom-option empty">No matching timezone</div> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function HoldingsSection({
  actionLabel,
  emptyText,
  itemType,
  items,
  onAdd,
  onDelete,
  onEdit,
  onMoveToPortfolio,
  onPositionChange,
  onPositionCommit,
  onReportToggle,
  onSort,
  portfolioTotal = 0,
  title,
}) {
  return (
    <section className="data-section">
      <div className="section-toolbar">
        <h2>{title}</h2>
        <div className="toolbar-actions">
          <button className="primary-button compact-button" onClick={onAdd} type="button">
            <Plus size={17} aria-hidden="true" />
            {actionLabel}
          </button>
          {itemType === "portfolio" ? (
            <button className="secondary-button compact-button" onClick={onSort} type="button">
              Sort by %
            </button>
          ) : null}
        </div>
      </div>
      <div className="table-shell">
        <table className="holdings-table">
          <colgroup>
            <col className="company-col" />
            <col className="position-col" />
            <col className="thesis-col" />
            <col className="report-col" />
            <col className="actions-col" />
          </colgroup>
          <thead>
            <tr>
              <th>Company</th>
              <th>{itemType === "portfolio" ? "Position" : ""}</th>
              <th>Thesis</th>
              <th>In report</th>
              <th className="actions-cell">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length ? (
              items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <div className="stock-cell">
                      <img className="stock-logo" {...stockLogoProps(item.logo_url)} alt="" />
                      <div>
                        <strong>{item.symbol}</strong>
                        <span>{item.company_name}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    {itemType === "portfolio" ? (
                      <PositionSlider
                        item={item}
                        onChange={onPositionChange}
                        onCommit={onPositionCommit}
                        portfolioTotal={portfolioTotal}
                      />
                    ) : null}
                  </td>
                  <td>
                    <span className="status-pill">{thesisPointCount(item, itemType)} points</span>
                  </td>
                  <td>
                    <ReportToggle checked={item.include_in_report !== false} onChange={(next) => onReportToggle(item, next)} />
                  </td>
                  <td className="actions-cell">
                    <button className="icon-button" onClick={() => onEdit(item)} title="Edit thesis" type="button">
                      <Pencil size={17} aria-hidden="true" />
                    </button>
                    {itemType === "watchlist" ? (
                      <button className="icon-button" onClick={() => onMoveToPortfolio(item)} title="Move to portfolio" type="button">
                        <MoveRight size={17} aria-hidden="true" />
                      </button>
                    ) : null}
                    <button className="icon-button danger" onClick={() => onDelete(item)} title="Delete" type="button">
                      <Trash2 size={17} aria-hidden="true" />
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="empty-table" colSpan={5}>
                  {emptyText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ReportToggle({ checked, onChange, onLabel = "Included in report", offLabel = "Excluded from report" }) {
  return (
    <button
      aria-pressed={checked}
      className={`report-switch${checked ? " is-on" : ""}`}
      onClick={(event) => {
        event.stopPropagation();
        onChange(!checked);
      }}
      title={checked ? onLabel : offLabel}
      type="button"
    >
      <span className="report-switch-knob" aria-hidden="true" />
      <span className="sr-only">{checked ? onLabel : offLabel}</span>
    </button>
  );
}

function thesisPointCount(item, itemType) {
  return THESIS_SECTIONS[itemType].reduce((total, section) => total + (item[section.key]?.length ?? 0), 0);
}

function PositionSlider({ item, onChange, onCommit, portfolioTotal }) {
  const current = Number(item.position_size_pct || 0);
  const max = Math.max(0, 100 - portfolioTotal + current);
  return (
    <div className="position-control">
      <input
        max={max}
        min="0"
        onBlur={() => onCommit(item)}
        onChange={(event) => onChange(item, event.target.value)}
        onMouseUp={() => onCommit(item)}
        onTouchEnd={() => onCommit(item)}
        step="0.5"
        type="range"
        value={current}
      />
      <span>{current.toFixed(1)}%</span>
    </div>
  );
}

function StockThesisModal({ modal, onClose, onSaved }) {
  const [search, setSearch] = useState("");
  const [results, setResults] = useState([]);
  const [stock, setStock] = useState(modal.stock ?? null);
  const [thesis, setThesis] = useState(modal.thesis ?? null);
  const [positionSize, setPositionSize] = useState(modal.positionSize ?? 10);
  const [status, setStatus] = useState(modal.mode === "edit" ? "review" : modal.stock ? "generating" : "search");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (modal.mode !== "add" || status !== "search" || search.trim().length < 1) {
      setResults([]);
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      setError("");
      try {
        const payload = await requestJson(`/api/stocks/search?q=${encodeURIComponent(search.trim())}`, {
          method: "GET",
        });
        setResults(payload.results ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed.");
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [modal.mode, search, status]);

  const selectStock = async (selected) => {
    setStock(selected);
    setStatus("generating");
    setError("");
    try {
      const payload = await requestJson("/api/thesis/draft", {
        method: "POST",
        body: JSON.stringify({
          item_type: modal.itemType,
          symbol: selected.symbol,
          company_name: selected.company_name,
        }),
      });
      setThesis(payload.thesis);
      setStatus("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Draft generation failed.");
      setStatus("search");
    }
  };

  useEffect(() => {
    if (modal.mode === "add" && modal.stock && status === "generating" && !thesis) {
      selectStock(modal.stock);
    }
  }, [modal.mode, modal.stock, status, thesis]);

  const save = async () => {
    if (!stock || !thesis) {
      return;
    }
    setSaving(true);
    setError("");
    const path =
      modal.itemType === "portfolio"
        ? modal.mode === "edit"
          ? `/api/portfolio-items/${modal.item.id}`
          : "/api/portfolio-items"
        : modal.mode === "edit"
          ? `/api/watchlist-items/${modal.item.id}`
          : "/api/watchlist-items";
    const method = modal.mode === "edit" ? "PUT" : "POST";
    const body =
      modal.itemType === "portfolio"
        ? {
            symbol: stock.symbol,
            company_name: stock.company_name,
            position_size_pct: positionSize,
            ...thesis,
          }
        : {
            symbol: stock.symbol,
            company_name: stock.company_name,
            ...thesis,
          };
    try {
      await requestJson(path, { method, body: JSON.stringify(body) });
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save item.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">{modal.itemType === "portfolio" ? "Portfolio" : "Watchlist"}</p>
            <h2>{modal.mode === "edit" ? `Edit ${stock?.symbol}` : "Add stock"}</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="Close" type="button">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {modal.mode === "add" && status === "search" ? (
          <div className="modal-search">
            <label>
              Search by symbol or company name
              <div className="search-input">
                <Search size={18} aria-hidden="true" />
                <input autoFocus onChange={(event) => setSearch(event.target.value)} value={search} />
              </div>
            </label>
            <div className="search-results">
              {results.map((result) => (
                <button
                  key={`${result.symbol}-${result.exchange || ""}`}
                  className="search-result"
                  onClick={() => selectStock(result)}
                  type="button"
                >
                  <img className="stock-logo" {...stockLogoProps(result.logo_url)} alt="" />
                  <div className="stock-search-copy">
                    <div className="stock-title-row">
                      <strong>{result.symbol}</strong>
                      {result.exchange ? <span className="exchange-badge">{result.exchange}</span> : null}
                    </div>
                    <span>{result.company_name}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {status === "generating" ? (
          <div className="generating-state">
            <Sparkles size={22} aria-hidden="true" />
            <p>Generating draft thesis...</p>
          </div>
        ) : null}

        {status === "review" && stock && thesis ? (
          <div className="review-layout">
            <div className="selected-stock">
              <img className="stock-logo large" {...stockLogoProps(stock.logo_url)} alt="" />
              <div>
                <div className="stock-title-row">
                  <strong>{stock.symbol}</strong>
                  {stock.exchange ? <span className="exchange-badge">{stock.exchange}</span> : null}
                </div>
                <span>{stock.company_name}</span>
              </div>
            </div>
            {modal.itemType === "portfolio" ? (
              <label>
                Position size: {Number(positionSize).toFixed(1)}%
                <input
                  max={modal.maxPositionSize}
                  min="0"
                  onChange={(event) => setPositionSize(clampPosition(event.target.value, modal.maxPositionSize))}
                  step="0.5"
                  type="range"
                  value={positionSize}
                />
              </label>
            ) : null}
            <div className="thesis-grid">
              {THESIS_SECTIONS[modal.itemType].map((section) => (
                <ThesisSectionEditor
                  key={section.key}
                  section={section}
                  value={thesis[section.key] ?? []}
                  onChange={(next) => setThesis((current) => ({ ...current, [section.key]: next }))}
                />
              ))}
            </div>
          </div>
        ) : null}

        {error ? <p className="error">{error}</p> : null}

        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose} type="button">
            Cancel
          </button>
          <button className="primary-button" disabled={status !== "review" || saving} onClick={save} type="button">
            <Check size={18} aria-hidden="true" />
            {saving ? "Saving..." : modal.mode === "edit" ? "Save changes" : "Confirm and add"}
          </button>
        </div>
      </section>
    </div>
  );
}

function ThesisSectionEditor({ section, value, onChange }) {
  const updatePoint = (index, nextValue) => {
    onChange(value.map((point, currentIndex) => (currentIndex === index ? nextValue : point)));
  };
  const removePoint = (index) => {
    onChange(value.filter((_, currentIndex) => currentIndex !== index));
  };
  const addPoint = () => {
    onChange([...value, ""]);
  };
  return (
    <section className="thesis-section">
      <div className="thesis-section-heading">
        <h3>{section.title}</h3>
        <button className="info-tooltip-trigger" type="button" aria-label={`${section.title}: ${section.description}`}>
          <Info size={15} aria-hidden="true" />
          <span className="info-tooltip" role="tooltip">
            {section.description}
          </span>
        </button>
      </div>
      <div className="bullet-list">
        {value.map((point, index) => (
          <div className="bullet-row" key={`${section.key}-${index}`}>
            <span aria-hidden="true">•</span>
            <input onChange={(event) => updatePoint(index, event.target.value)} value={point} />
            <button className="mini-icon-button" onClick={() => removePoint(index)} title="Remove point" type="button">
              <Trash2 size={15} aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
      <button className="text-button" onClick={addPoint} type="button">
        <Plus size={15} aria-hidden="true" />
        Add point
      </button>
    </section>
  );
}

function ConfirmDialog({ item, message = "This removes the stock and its thesis from this list.", onCancel, onConfirm, title }) {
  return (
    <div className="modal-backdrop" onMouseDown={onCancel}>
      <section className="confirm-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <h2>{title ?? `Delete ${item.symbol}?`}</h2>
        <p className="muted">{message}</p>
        <div className="modal-actions">
          <button className="secondary-button" onClick={onCancel} type="button">
            Cancel
          </button>
          <button className="danger-button" onClick={onConfirm} type="button">
            Delete
          </button>
        </div>
      </section>
    </div>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
