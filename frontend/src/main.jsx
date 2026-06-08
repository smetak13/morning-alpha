import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Check, LogOut, Mail, Pencil, Plus, Search, Sparkles, Trash2, UserPlus, X } from "lucide-react";
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

const THESIS_SECTIONS = {
  portfolio: [
    { key: "why_i_own_it", title: "Why I own it" },
    { key: "bull_case", title: "Bull case" },
    { key: "bear_case", title: "Bear case" },
    { key: "key_metrics", title: "Key metrics" },
    { key: "red_flags", title: "Red flags" },
    { key: "action_triggers", title: "Action triggers" },
  ],
  watchlist: [
    { key: "why_i_watch_it", title: "Why I watch it" },
    { key: "bull_case", title: "Bull case" },
    { key: "bear_case", title: "Bear case" },
    { key: "key_metrics", title: "Key metrics" },
    { key: "red_flags", title: "Red flags" },
    { key: "action_triggers", title: "Action triggers" },
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
  const [portfolio, setPortfolio] = useState([]);
  const [watchlist, setWatchlist] = useState([]);
  const [itemsStatus, setItemsStatus] = useState("loading");
  const [itemsError, setItemsError] = useState("");
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
            <h1>Portfolio workspace</h1>
          </div>
          <div className="allocation-pill">{portfolioTotal.toFixed(1)}% allocated</div>
        </div>

        {itemsError ? <p className="error">{itemsError}</p> : null}
        {itemsStatus === "loading" ? <p className="muted">Loading holdings...</p> : null}

        <HoldingsSection
          actionLabel="Add holding"
          emptyText="No portfolio holdings yet."
          itemType="portfolio"
          items={portfolio}
          onAdd={() => openAddModal("portfolio")}
          onDelete={(item) => setDeleteTarget({ itemType: "portfolio", item })}
          onEdit={(item) => openEditModal("portfolio", item)}
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
          title="Watchlist"
        />
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
            <col className="actions-col" />
          </colgroup>
          <thead>
            <tr>
              <th>Company</th>
              <th>{itemType === "portfolio" ? "Position" : ""}</th>
              <th>Thesis</th>
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
                <td className="empty-table" colSpan={4}>
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
                <button key={result.symbol} className="search-result" onClick={() => selectStock(result)} type="button">
                  <img className="stock-logo" {...stockLogoProps(result.logo_url)} alt="" />
                  <strong>{result.symbol}</strong>
                  <span>{result.company_name}</span>
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
                <strong>{stock.symbol}</strong>
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
      <h3>{section.title}</h3>
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
