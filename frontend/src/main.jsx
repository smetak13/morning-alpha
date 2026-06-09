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
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";
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
            <h1>{activeView === "portfolio" ? "Portfolio workspace" : "Reports"}</h1>
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
              onReportToggle={(item, nextValue) => updateReportInclusion("watchlist", item, nextValue)}
              title="Watchlist"
            />
          </>
        ) : (
          <ReportsView routeReportId={route.reportId} />
        )}
      </section>

      {modal ? (
        <StockThesisModal
          modal={modal}
          onClose={() => setModal(null)}
          onSaved={async () => {
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
            <table className="reports-table">
              <thead>
                <tr>
                  <th>Report date</th>
                  <th>Created at</th>
                  <th className="actions-cell">Open</th>
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
                        <button className="icon-button" onClick={(event) => { event.stopPropagation(); openReport(report); }} title="Open report" type="button">
                          <Eye size={17} aria-hidden="true" />
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
        <ReportPreviewModal report={selectedReport} onClose={closeReport} />
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

function ReportPreviewModal({ report, onClose }) {
  const reportHtml = useMemo(() => enhanceReportHtml(report.html), [report.html]);
  return (
    <div className="modal-backdrop report-preview-backdrop">
      <section className="report-modal-panel" aria-modal="true" role="dialog">
        <div className="report-modal-header">
          <div>
            <p className="eyebrow">Saved report</p>
            <h2>{report.report_date}</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="Close report" type="button">
            <X size={18} aria-hidden="true" />
          </button>
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

function ReportToggle({ checked, onChange }) {
  return (
    <button
      aria-pressed={checked}
      className={`report-switch${checked ? " is-on" : ""}`}
      onClick={() => onChange(!checked)}
      title={checked ? "Included in report" : "Excluded from report"}
      type="button"
    >
      <span className="report-switch-knob" aria-hidden="true" />
      <span className="sr-only">{checked ? "Included in report" : "Excluded from report"}</span>
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
  const [status, setStatus] = useState(modal.mode === "edit" ? "review" : "search");
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
    <div className="modal-backdrop">
      <section className="modal-panel" aria-modal="true" role="dialog">
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

function ConfirmDialog({ item, onCancel, onConfirm }) {
  return (
    <div className="modal-backdrop">
      <section className="confirm-panel" aria-modal="true" role="dialog">
        <h2>Delete {item.symbol}?</h2>
        <p className="muted">This removes the stock and its thesis from this list.</p>
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
