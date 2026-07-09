import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Bell,
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
  Timeline,
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

const REPORT_FREQUENCIES = [
  ["daily", "Daily"],
  ["weekly", "Weekly"],
  ["monthly", "Monthly"],
];

function reportFrequencyValue(value) {
  return REPORT_FREQUENCIES.some(([option]) => option === value) ? value : "daily";
}

function userSettingsFromProfile(user) {
  return {
    report_scheduled_at: timeInputValue(user?.report_scheduled_at),
    report_frequency: reportFrequencyValue(user?.report_frequency),
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

function formatLongDate(value) {
  if (!value) {
    return "";
  }
  if (!String(value).match(/^\d{4}-\d{2}-\d{2}$/)) {
    return String(value);
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(parseIsoDate(value));
}

function formatShortDate(value) {
  if (!value) {
    return "";
  }
  if (!String(value).match(/^\d{4}-\d{2}-\d{2}$/)) {
    return String(value);
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(parseIsoDate(value));
}

function reportFrequencyLabel(value) {
  return REPORT_FREQUENCIES.find(([option]) => option === value)?.[1] ?? "Daily";
}

function reportPeriodDisplay(report) {
  return report?.report_period_display || formatLongDate(report?.report_date) || report?.report_date || "";
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
  if (window.location.pathname === "/landing") {
    return { view: "landing", reportId: "", researchId: "" };
  }
  if (window.location.pathname === "/pricing") {
    return { view: "pricing", reportId: "", researchId: "" };
  }
  const reportMatch = window.location.pathname.match(/^\/reports\/([^/]+)\/?$/);
  if (reportMatch) {
    return { view: "reports", reportId: decodeURIComponent(reportMatch[1]), researchId: "" };
  }
  if (window.location.pathname === "/reports") {
    return { view: "reports", reportId: "", researchId: "" };
  }
  if (window.location.pathname === "/notes") {
    return { view: "notes", reportId: "", researchId: "" };
  }
  if (window.location.pathname === "/feedback") {
    return { view: "feedback", reportId: "", researchId: "" };
  }
  const researchMatch = window.location.pathname.match(/^\/research\/([^/]+)\/?$/);
  if (researchMatch) {
    return { view: "research", reportId: "", researchId: decodeURIComponent(researchMatch[1]) };
  }
  if (window.location.pathname === "/research") {
    return { view: "research", reportId: "", researchId: "" };
  }
  return { view: "portfolio", reportId: "", researchId: "" };
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
      @media (max-width: 760px) {
        html body table.brand-report-row,
        html body table.brand-report-row tbody,
        html body table.brand-report-row tr,
        html body table.brand-report-row td {
          display: block !important;
          text-align: left !important;
          width: 100% !important;
        }
        html body table.brand-report-row td.desktop-report-meta-cell.report-meta-cell {
          display: block !important;
          max-height: none !important;
          overflow: visible !important;
          padding-top: 11px !important;
          text-align: left !important;
          width: 100% !important;
        }
        html body table.brand-report-row tr.mobile-report-meta-row {
          display: none !important;
          max-height: 0 !important;
          overflow: hidden !important;
        }
        html body .report-date-main {
          text-align: left !important;
        }
      }
      @media (min-width: 761px) {
        .container { max-width: 1180px !important; }
        .company-nav {
          position: sticky !important;
          top: 0 !important;
          z-index: 4 !important;
          background: rgba(17, 17, 17, 0.94) !important;
          border-bottom: 1px solid #2a2a2a !important;
          margin-left: -28px !important;
          margin-right: -28px !important;
          padding: 12px 28px 6px !important;
          backdrop-filter: blur(10px);
        }
        .company-card {
          scroll-margin-top: 78px;
        }
        .company-chip:hover {
          border-color: #f4c430 !important;
          color: #f4c430 !important;
        }
        .memory-link {
          align-items: center !important;
          border: 0 !important;
          border-radius: 6px !important;
          box-sizing: border-box !important;
          display: inline-flex !important;
          height: 32px !important;
          justify-content: center !important;
          line-height: 0 !important;
          overflow: hidden !important;
          width: 104px !important;
        }
        .memory-link img {
          display: block !important;
          height: 32px !important;
          max-width: 104px !important;
          width: 104px !important;
        }
        .memory-link:hover {
          background: transparent !important;
          border: 0 !important;
          box-shadow: none !important;
          color: #111111 !important;
        }
        .memory-link:hover img {
          filter: brightness(1.06) !important;
        }
      }
      .app-thesis-impact {
        padding: 0 !important;
      }
      .app-thesis-toggle {
        align-items: center;
        background: transparent;
        border: 0;
        color: #f4c430;
        cursor: pointer;
        display: flex;
        font: inherit;
        font-size: 11px;
        font-weight: bold;
        justify-content: space-between;
        letter-spacing: 0.04em;
        margin: 0;
        padding: 12px;
        text-align: left;
        text-transform: uppercase;
        width: 100%;
      }
      .app-thesis-toggle:hover {
        color: #f7d75a;
      }
      .app-thesis-chevron {
        color: #f4c430;
        font-size: 15px;
        line-height: 1;
        margin-left: 12px;
        transform: rotate(0deg);
        transition: transform 140ms ease;
      }
      .app-thesis-impact.open .app-thesis-chevron {
        transform: rotate(90deg);
      }
      .app-thesis-body {
        display: none;
        padding: 0 12px 12px;
      }
      .app-thesis-impact.open .app-thesis-body {
        display: block;
      }
    </style>
  `;
  const withTargets = String(html || "").replace(/<a\s+(?![^>]*\btarget=)/g, '<a target="_blank" rel="noopener noreferrer" ');
  if (withTargets.includes("<head>")) {
    return withTargets.replace("<head>", `<head>${enhancement}`);
  }
  return `${enhancement}${withTargets}`;
}

function setupReportThesisImpactToggles(doc) {
  const subpanels = Array.from(doc.querySelectorAll(".subpanel"));
  subpanels.forEach((panel, index) => {
    const title = panel.querySelector(".subpanel-title");
    const titleText = title?.textContent?.trim().toLowerCase();
    if (titleText === "attention") {
      panel.remove();
      return;
    }
    if (titleText !== "thesis impact" || panel.classList.contains("app-thesis-impact")) {
      return;
    }
    const body = doc.createElement("div");
    body.className = "app-thesis-body";
    const siblings = [];
    let node = title.nextSibling;
    while (node) {
      siblings.push(node);
      node = node.nextSibling;
    }
    siblings.forEach((child) => body.appendChild(child));

    const button = doc.createElement("button");
    const contentId = `app-thesis-impact-${index}`;
    button.className = "app-thesis-toggle";
    button.type = "button";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", contentId);
    button.innerHTML = '<span>Thesis impact</span><span class="app-thesis-chevron" aria-hidden="true">&#8250;</span>';

    body.id = contentId;
    panel.classList.add("app-thesis-impact");
    panel.replaceChild(button, title);
    panel.appendChild(body);
    button.addEventListener("click", () => {
      const isOpen = panel.classList.toggle("open");
      button.setAttribute("aria-expanded", String(isOpen));
    });
  });
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
    if (route.view !== "landing" && route.view !== "pricing") {
      refreshSession();
    }
  }, [refreshSession, route.view]);

  useEffect(() => {
    const syncRoute = () => setRoute(currentRoute());
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, []);

  const handleLogout = useCallback(async () => {
    await requestJson("/logout", { method: "POST", body: "{}" }).catch(() => {});
    setSession({ status: "anonymous", user: null });
  }, []);

  if (route.view === "landing") {
    return <LandingPage />;
  }

  if (route.view === "pricing") {
    return <PricingPage />;
  }

  if (session.status === "checking") {
    return <LoadingScreen />;
  }

  if (session.status !== "authenticated") {
    return <AuthPage onAuthenticated={refreshSession} />;
  }

  return <MainPage route={route} user={session.user} onLogout={handleLogout} />;
}

const LANDING_FEATURES = [
  {
    title: "Email Report",
    tag: "Daily intelligence",
    text: "A personalized morning report for your portfolio and watchlist. Morning Alpha tracks your investment thesis, preserves its context over time, and highlights the news that matters most for every company you follow.",
    icon: Mail,
  },
  {
    title: "Company Research",
    tag: "Instant insights",
    text: "Instantly see where a company stands today, how it compares with your investment thesis, and whether new information strengthens or weakens your conviction. Ideal for both existing holdings and evaluating new ideas.",
    icon: Search,
  },
  {
    title: "Notes",
    tag: "Persistent context",
    text: "Add notes and action items directly to reports and research pages. Track what needs follow-up, keep the context close to the source, and resolve items when the work is done.",
    icon: Pencil,
  },
  {
    title: "Premium Deep Research",
    tag: "Professional analysis",
    text: "Everything you need to understand a business—from filings and earnings calls to valuation models, financials, risks, recent developments and long-term catalysts—all organized in one research workspace.",
    icon: Sparkles,
    premium: true,
  },
];

const PRICING_TIERS = [
  {
    name: "Starter",
    price: "$12.99",
    description: "For investors who want portfolio and watchlist updates filtered through their own thesis, not a generic market news feed.",
    features: [
      "Personalized email reports for portfolio and watchlist",
      "Thesis-aware alerts for important company events",
      "Company research and lightweight primers",
      "Notes and action items tied to reports and research",
      "Portfolio and watchlist thesis tracking",
    ],
  },
  {
    name: "Professional",
    price: "$19.99",
    description: "For investors who want the daily workflow plus a premium deep research workspace.",
    featured: true,
    features: [
      "Everything in Starter",
      "Premium Deep Research workspace",
      "50 deep researches per month",
      "DCF calculator, charts, filings, transcripts, and financial statements",
      "Business model, risks, catalysts, and current situation summaries",
    ],
  },
];

function HeroReportMockup() {
  const portfolioItems = [
    {
      ticker: "META",
      section: "Portfolio holding",
      tone: "Mixed",
      headline: "AI capex raises the bar for free cash flow execution.",
      thesis: "Infrastructure spend supports the AI thesis, but monitor whether revenue growth keeps pace with capex intensity.",
      source: "WSJ",
    },
    {
      ticker: "MELI",
      section: "Portfolio holding",
      tone: "Review Thesis",
      toneVariant: "negative",
      headline: "Credit losses and margin pressure are the main follow-up.",
      thesis: "Directly tests the operating leverage thesis and the quality of Mercado Pago growth.",
      source: "Earnings call",
    },
  ];

  return (
    <div className="hero-report-stage" aria-label="Morning Alpha email report preview">
      <div className="hero-report-shadow" />
      <section className="hero-report-card">
        <header className="hero-report-header">
          <img src="/ma-logo.png" alt="Morning Alpha" />
          <div>
            <span>Morning Report</span>
            <strong>June 22, 2026</strong>
          </div>
        </header>

        <section className="hero-report-block">
          <h3>Executive Summary</h3>
          <div className="hero-report-summary">
            <ul>
              <li>Portfolio news is concentrated in AI infrastructure, lending quality, and margin durability.</li>
              <li>Two holdings have thesis-level follow-up items before the next earnings cycle.</li>
            </ul>
          </div>
        </section>

        <div className="hero-report-section">
          <div className="hero-report-title-row">
            <h3>Portfolio</h3>
            <span>Thesis impact</span>
          </div>
          <div className="hero-report-news-list">
            {portfolioItems.map((item) => (
              <article className="hero-report-news" key={item.ticker}>
                <header className="hero-report-company-head">
                  <div className="hero-report-logo-tile">{item.ticker.slice(0, 2)}</div>
                  <div>
                    <strong>{item.ticker}</strong>
                    <span>{item.section}</span>
                  </div>
                  <em className={item.toneVariant === "negative" ? "negative" : undefined}>{item.tone}</em>
                </header>
                <div>
                  <h4>{item.headline}</h4>
                  <div className="hero-report-subpanel">
                    <span>Thesis impact</span>
                    <p>{item.thesis}</p>
                  </div>
                  <p className="hero-report-source">Full article - {item.source}</p>
                </div>
              </article>
            ))}
          </div>
        </div>

      </section>

    </div>
  );
}

function LandingPage() {
  return (
    <main className="landing-page">
      <header className="landing-header">
        <img className="landing-logo" src="/ma-logo.png" alt="Morning Alpha" />
        <nav className="landing-nav" aria-label="Landing navigation">
          <a href="#pricing">Pricing</a>
          <a href="/">Sign in</a>
        </nav>
      </header>

      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy">
          <h1 id="landing-title">Wake up to what matters.</h1>
          <p>Personalized investment intelligence for long-term investors who want signal, not noise.</p>
          <a className="landing-cta" href="/">
            Get Started
          </a>
        </div>
        <HeroReportMockup />
      </section>

      <section className="landing-features" aria-label="Product overview">
        <div className="landing-features-heading">
          <h2>Reports, research, notes, and deeper analysis in one workflow.</h2>
        </div>
        <div className="landing-feature-grid">
          {LANDING_FEATURES.map((section) => {
            const Icon = section.icon;
            return (
              <article className={section.premium ? "landing-feature premium-feature" : "landing-feature"} key={section.title}>
                <div className="landing-feature-head">
                  <span className="landing-feature-icon">
                    <Icon size={20} aria-hidden="true" />
                  </span>
                  <span>{section.tag}</span>
                </div>
                <div className="landing-feature-copy">
                  <h2>{section.title}</h2>
                  <p>{section.text}</p>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="landing-close">
        <div className="landing-close-copy">
          <p className="eyebrow">Built for long-term investors</p>
          <h2>Less market noise. More thesis-level context.</h2>
          <p>
            Keep your portfolio, watchlist, research, and follow-up notes connected to the investment thesis you actually care about.
          </p>
          <a className="landing-cta secondary-landing-cta" href="/">
            Get Started
          </a>
        </div>
        <div className="landing-close-media workflow-composite" aria-label="Morning Alpha workflow preview">
          <article className="workflow-layer report-layer">
            <div>
              <Mail size={17} aria-hidden="true" />
              <strong>Report</strong>
            </div>
            <p>Daily thesis alerts for the companies you follow.</p>
          </article>
          <article className="workflow-layer research-layer">
            <div>
              <Search size={17} aria-hidden="true" />
              <strong>Research</strong>
            </div>
            <p>Check new information against your portfolio context.</p>
          </article>
          <article className="workflow-layer notes-layer">
            <div>
              <Pencil size={17} aria-hidden="true" />
              <strong>Notes</strong>
            </div>
            <p>Keep follow-up items visible until they are resolved.</p>
          </article>
        </div>
      </section>
      <PricingSection />
      <LandingFooter />
    </main>
  );
}

function PricingSection() {
  return (
    <section className="pricing-section" id="pricing" aria-labelledby="pricing-title">
      <div className="pricing-section-heading">
        <h2 id="pricing-title">Choose how deep you want your research workflow to go.</h2>
      </div>

      <div className="pricing-grid" aria-label="Pricing tiers">
        {PRICING_TIERS.map((tier) => (
          <article className={tier.featured ? "pricing-card professional-pricing-card" : "pricing-card"} key={tier.name}>
            <div className="pricing-card-header">
              <h2>{tier.name}</h2>
              <p>{tier.description}</p>
            </div>
            <div className="pricing-price">
              <strong>{tier.price}</strong>
              <span>/ month</span>
            </div>
            <ul className="pricing-feature-list">
              {tier.features.map((feature) => (
                <li key={feature}>
                  <Check size={16} aria-hidden="true" />
                  <span>{feature}</span>
                </li>
              ))}
            </ul>
            <a className={tier.featured ? "landing-cta pricing-cta" : "secondary-button pricing-cta"} href="/">
              Get Started
            </a>
          </article>
        ))}
      </div>
    </section>
  );
}

function PricingPage() {
  return (
    <main className="landing-page pricing-page">
      <header className="landing-header">
        <a href="/landing" aria-label="Morning Alpha landing page">
          <img className="landing-logo" src="/ma-logo.png" alt="Morning Alpha" />
        </a>
        <nav className="landing-nav" aria-label="Pricing navigation">
          <a href="/landing">Product</a>
          <a href="/">Sign in</a>
        </nav>
      </header>

      <PricingSection />
      <LandingFooter />
    </main>
  );
}

function LandingFooter() {
  return (
    <footer className="landing-footer">
      <div className="landing-footer-brand">
        <img src="/ma-logo.png" alt="Morning Alpha" />
      </div>
      <span className="landing-footer-copy">&copy; 2026 All Rights Reserved.</span>
      <a className="landing-footer-mail" href="mailto:info@morning-alpha.com" aria-label="Email Morning Alpha">
        <Mail size={18} aria-hidden="true" />
      </a>
    </footer>
  );
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
  const [contextTarget, setContextTarget] = useState(null);
  const [notifications, setNotifications] = useState([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notificationsStatus, setNotificationsStatus] = useState("idle");
  const notificationRef = useRef(null);
  const notificationUnreadOnOpenRef = useRef(0);

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

  const loadNotifications = useCallback(async () => {
    setNotificationsStatus("loading");
    try {
      const payload = await requestJson("/api/notifications?limit=5", { method: "GET" });
      setNotifications(payload.items ?? []);
      setUnreadNotifications(Number(payload.unread_count || 0));
      setNotificationsStatus("ready");
      return payload;
    } catch {
      setNotificationsStatus("error");
      return null;
    }
  }, []);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  useEffect(() => {
    loadNotifications();
  }, [loadNotifications]);

  useEffect(() => {
    if (!notificationsOpen) {
      return undefined;
    }
    const handlePointerDown = (event) => {
      if (notificationRef.current && !notificationRef.current.contains(event.target)) {
        closeNotifications();
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [notificationsOpen]);

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

  const showFeedback = () => {
    setActiveView("feedback");
    setBrowserRoute("/feedback");
  };

  const showResearch = () => {
    setActiveView("research");
    setBrowserRoute("/research");
  };

  const pageTitle =
    activeView === "portfolio"
      ? "Portfolio workspace"
      : activeView === "reports"
        ? "Reports"
        : activeView === "notes"
          ? "Notes"
          : activeView === "feedback"
            ? "Feedback"
            : "Research";

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

  const markOpenNotificationsRead = async () => {
    const unreadCount = notificationUnreadOnOpenRef.current;
    if (unreadCount <= 0) {
      return;
    }
    const readAt = new Date().toISOString();
    notificationUnreadOnOpenRef.current = 0;
    setUnreadNotifications(0);
    setNotifications((current) => current.map((notification) => ({ ...notification, read_at: notification.read_at || readAt })));
    await requestJson("/api/notifications/read", { method: "POST", body: "{}" }).catch(() => {
      setUnreadNotifications(unreadCount);
      loadNotifications();
    });
  };

  const closeNotifications = () => {
    setNotificationsOpen(false);
    markOpenNotificationsRead();
  };

  const toggleNotifications = async () => {
    const nextOpen = !notificationsOpen;
    if (!nextOpen) {
      closeNotifications();
      return;
    }
    setNotificationsOpen(true);
    const payload = await loadNotifications();
    notificationUnreadOnOpenRef.current = Number(payload?.unread_count || unreadNotifications || 0);
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
        <div className="topbar-actions">
          <div className="notification-menu" ref={notificationRef}>
            <button
              aria-expanded={notificationsOpen}
              aria-haspopup="menu"
              className="icon-button notification-button"
              onClick={toggleNotifications}
              type="button"
              title="Notifications"
            >
              <Bell size={18} aria-hidden="true" />
              {unreadNotifications > 0 ? <span className="notification-dot" aria-hidden="true" /> : null}
            </button>
            {notificationsOpen ? (
              <div className="notification-popover" role="menu">
                <div className="notification-popover-header">
                  <strong>Notifications</strong>
                </div>
                {notificationsStatus === "loading" ? <p className="notification-empty">Loading...</p> : null}
                {notificationsStatus === "error" ? <p className="notification-empty">Unable to load notifications.</p> : null}
                {notificationsStatus !== "loading" && notificationsStatus !== "error" && notifications.length === 0 ? (
                  <p className="notification-empty">No notifications.</p>
                ) : null}
                {notificationsStatus !== "loading" && notificationsStatus !== "error" && notifications.length > 0 ? (
                  <div className="notification-list">
                    {notifications.map((notification) => (
                      <div
                        className={notification.read_at ? "notification-item" : "notification-item unread"}
                        key={notification.id}
                        role="menuitem"
                      >
                        <span>
                          <strong>{notification.title}</strong>
                          {notification.body ? <em>{notification.body}</em> : null}
                        </span>
                        {notification.event_date ? <small>{formatShortDate(notification.event_date)}</small> : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
          <button className="icon-button" onClick={onLogout} type="button" title="Sign out">
            <LogOut size={18} aria-hidden="true" />
          </button>
        </div>
      </header>
      <section className={`main-content main-content-${activeView}`}>
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
            className={activeView === "research" ? "view-tab active" : "view-tab"}
            onClick={showResearch}
            type="button"
          >
            Research
          </button>
          <button
            className={activeView === "notes" ? "view-tab active" : "view-tab"}
            onClick={showNotes}
            type="button"
          >
            Notes
          </button>
          <button
            className={activeView === "feedback" ? "view-tab active" : "view-tab"}
            onClick={showFeedback}
            type="button"
          >
            Feedback
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
              onOpenContext={(item) => setContextTarget(item)}
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
              onOpenContext={(item) => setContextTarget(item)}
              onMoveToPortfolio={openMoveToPortfolioModal}
              onReportToggle={(item, nextValue) => updateReportInclusion("watchlist", item, nextValue)}
              title="Watchlist"
            />
          </>
        ) : activeView === "reports" ? (
          <ReportsView routeReportId={route.reportId} />
        ) : activeView === "notes" ? (
          <NotesView />
        ) : activeView === "feedback" ? (
          <FeedbackView user={user} />
        ) : (
          <ResearchView
            portfolioItems={portfolio}
            routeResearchId={route.researchId}
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

      {contextTarget ? (
        <CompanyContextModal
          item={contextTarget}
          onClose={() => setContextTarget(null)}
        />
      ) : null}
    </main>
  );
}

const FEEDBACK_CATEGORY_OPTIONS = [
  { value: "bug", label: "Bug" },
  { value: "feature_request", label: "Feature request" },
  { value: "small_improvement", label: "Small improvement" },
  { value: "data_quality", label: "Data or calculation issue" },
  { value: "usability", label: "Usability / UX" },
  { value: "other", label: "Other" },
];

function FeedbackView({ user }) {
  const accountEmail = user?.email || "";
  const categoryDropdownRef = useRef(null);
  const [form, setForm] = useState({
    email: accountEmail,
    category: "bug",
    message: "",
  });
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [categoryOpen, setCategoryOpen] = useState(false);
  const selectedCategory = FEEDBACK_CATEGORY_OPTIONS.find((option) => option.value === form.category) ?? FEEDBACK_CATEGORY_OPTIONS[0];

  useEffect(() => {
    setForm((current) => ({ ...current, email: accountEmail }));
  }, [accountEmail]);

  useEffect(() => {
    if (!categoryOpen) {
      return undefined;
    }
    const handlePointerDown = (event) => {
      if (categoryDropdownRef.current && !categoryDropdownRef.current.contains(event.target)) {
        setCategoryOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [categoryOpen]);

  const updateField = (event) => {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
    setError("");
    if (status === "sent") {
      setStatus("idle");
    }
  };

  const selectCategory = (value) => {
    setForm((current) => ({ ...current, category: value }));
    setCategoryOpen(false);
    setError("");
    if (status === "sent") {
      setStatus("idle");
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    const email = accountEmail.trim();
    const message = form.message.trim();
    if (!email || !message) {
      setError("Your account email and feedback message are required.");
      return;
    }
    setStatus("sending");
    setError("");
    try {
      await requestJson("/api/feedback", {
        method: "POST",
        body: JSON.stringify({
          email,
          category: form.category,
          message,
        }),
      });
      setStatus("sent");
      setForm((current) => ({ ...current, message: "" }));
    } catch (err) {
      setStatus("idle");
      setError(err instanceof Error ? err.message : "Unable to send feedback.");
    }
  };

  return (
    <section className="feedback-view">
      <div className="research-card feedback-card">
        <div className="research-card-header feedback-card-header">
          <div>
            <h3>Send feedback</h3>
            <p className="muted">
              Share bugs, product ideas, small improvements, or data issues. The message goes directly to the founder.
            </p>
          </div>
        </div>
        <form className="feedback-form" onSubmit={submit}>
          <div className="feedback-form-grid">
            <label className="note-field">
              <span className="note-field-label">Email</span>
              <input
                autoComplete="email"
                name="email"
                placeholder="you@example.com"
                readOnly
                required
                type="email"
                value={accountEmail}
              />
            </label>
            <div className="note-field" ref={categoryDropdownRef}>
              <span className="note-field-label">Category</span>
              <div className="feedback-select">
                <button
                  aria-expanded={categoryOpen}
                  className="feedback-select-button"
                  onClick={() => setCategoryOpen((current) => !current)}
                  type="button"
                >
                  <span>{selectedCategory.label}</span>
                  <ChevronDown size={17} aria-hidden="true" />
                </button>
                {categoryOpen ? (
                  <div className="feedback-select-menu" role="listbox">
                    {FEEDBACK_CATEGORY_OPTIONS.map((option) => (
                      <button
                        aria-selected={form.category === option.value}
                        className={form.category === option.value ? "selected" : ""}
                        key={option.value}
                        onClick={() => selectCategory(option.value)}
                        role="option"
                        type="button"
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
          <label className="note-field">
            <span className="note-field-label">Message</span>
            <textarea
              minLength={10}
              name="message"
              onChange={updateField}
              placeholder="Describe what happened, what you expected, or what would make the app better."
              required
              rows={9}
              value={form.message}
            />
          </label>
          {error ? <p className="error">{error}</p> : null}
          {status === "sent" ? <p className="success-message">Feedback sent. Thank you.</p> : null}
          <div className="feedback-actions">
            <button className="primary-button" disabled={status === "sending"} type="submit">
              <Mail size={18} aria-hidden="true" />
              {status === "sending" ? "Sending..." : "Send feedback"}
            </button>
          </div>
        </form>
      </div>
    </section>
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
                      <td data-label="Report date">
                        <div className="mobile-card-title-row">
                          <div className="report-date-cell">
                            <FileText size={17} aria-hidden="true" />
                            <span>
                              <strong>{reportPeriodDisplay(report)}</strong>
                              <em>{reportFrequencyLabel(report.report_frequency)} report</em>
                            </span>
                          </div>
                          <button className="mobile-open-button" onClick={(event) => { event.stopPropagation(); openReport(report); }} type="button">
                            Open
                          </button>
                        </div>
                      </td>
                      <td data-label="Created at">{formatDateTime(report.created_at)}</td>
                      <td className="actions-cell" data-label="Notes">
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
  const iframeRef = useRef(null);
  const [memoryDetail, setMemoryDetail] = useState(null);
  const [memoryStatus, setMemoryStatus] = useState("idle");
  const [memoryError, setMemoryError] = useState("");

  const openMemory = useCallback(async (memoryId) => {
    if (!memoryId) {
      return;
    }
    setMemoryStatus("loading");
    setMemoryError("");
    setMemoryDetail(null);
    try {
      const payload = await requestJson(`/api/company-memory/${encodeURIComponent(memoryId)}`, { method: "GET" });
      setMemoryDetail(payload.memory);
      setMemoryStatus("ready");
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "Unable to load tracked context.");
      setMemoryStatus("error");
    }
  }, []);

  const scrollReportFrameTo = useCallback((anchor) => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc || !anchor) {
      return false;
    }
    const target = doc.getElementById(anchor);
    if (!target) {
      return false;
    }
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    return true;
  }, []);

  const wireReportFrame = useCallback(() => {
    const frame = iframeRef.current;
    const doc = frame?.contentDocument;
    if (!doc) {
      return;
    }
    setupReportThesisImpactToggles(doc);
    const companyLinks = Array.from(doc.querySelectorAll("[data-company-anchor]"));
    companyLinks.forEach((link) => {
      link.addEventListener("click", (event) => {
        const anchor = link.getAttribute("data-company-anchor");
        if (!anchor) {
          return;
        }
        event.preventDefault();
        scrollReportFrameTo(anchor);
      });
    });
    const links = Array.from(doc.querySelectorAll("[data-memory-id]"));
    links.forEach((link) => {
      link.addEventListener("click", (event) => {
        const memoryId = link.getAttribute("data-memory-id");
        if (!memoryId) {
          return;
        }
        event.preventDefault();
        openMemory(memoryId);
      });
    });
    const companyMatch = window.location.hash.match(/^#(portfolio|watchlist)-([^#?]+)/);
    if (companyMatch?.[0]) {
      const anchor = decodeURIComponent(companyMatch[0].slice(1));
      window.setTimeout(() => {
        if (scrollReportFrameTo(anchor)) {
          window.history.replaceState({}, "", window.location.pathname);
        }
      }, 50);
    }
  }, [openMemory, scrollReportFrameTo]);

  useEffect(() => {
    const match = window.location.hash.match(/^#memory-([^#?]+)/);
    if (match?.[1]) {
      openMemory(decodeURIComponent(match[1]));
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [openMemory, report.id]);

  return (
    <div className="modal-backdrop report-preview-backdrop" onMouseDown={onClose}>
      <section className="report-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="report-modal-header">
          <div>
            <p className="eyebrow">Saved report</p>
            <h2>{reportPeriodDisplay(report)}</h2>
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
          onLoad={wireReportFrame}
          ref={iframeRef}
          sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin"
          srcDoc={reportHtml}
          title={`Report ${reportPeriodDisplay(report)}`}
        />
      </section>
      {memoryStatus !== "idle" ? (
        <CompanyMemoryModal
          error={memoryError}
          memory={memoryDetail}
          onClose={() => {
            setMemoryStatus("idle");
            setMemoryDetail(null);
            setMemoryError("");
          }}
          onChanged={(nextMemory) => setMemoryDetail(nextMemory)}
          status={memoryStatus}
        />
      ) : null}
    </div>
  );
}

function CompanyMemoryModal({ error, memory, onChanged, onClose, status }) {
  const [localMemory, setLocalMemory] = useState(memory);
  const [deletingEventId, setDeletingEventId] = useState("");
  const [eventError, setEventError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => {
    setLocalMemory(memory);
    setEventError("");
  }, [memory]);

  const activeMemory = localMemory ?? memory;
  const memoryStatusLabel = activeMemory?.status === "resolved"
    ? "Resolved"
    : activeMemory?.status === "stale"
      ? "Developing"
      : "Active";

  const deleteMemoryEvent = async () => {
    if (!activeMemory?.id || !deleteTarget?.id || deletingEventId) {
      return;
    }
    setDeletingEventId(deleteTarget.id);
    setEventError("");
    try {
      const payload = await requestJson(`/api/company-memory/${encodeURIComponent(activeMemory.id)}/events/${encodeURIComponent(deleteTarget.id)}`, {
        method: "DELETE",
      });
      setLocalMemory(payload.memory);
      onChanged?.(payload.memory);
      setDeleteTarget(null);
    } catch (err) {
      setEventError(err instanceof Error ? err.message : "Unable to remove tracked context item.");
    } finally {
      setDeletingEventId("");
    }
  };

  return (
    <div className="modal-backdrop nested-modal-backdrop" onMouseDown={(event) => { event.stopPropagation(); onClose(); }}>
      <section className="modal-panel company-memory-panel long-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <div className="selected-stock no-margin">
            {activeMemory ? <img className="stock-logo large" {...stockLogoProps(activeMemory.logo_url)} alt="" /> : <Info size={22} aria-hidden="true" />}
            <div>
              <p className="eyebrow">Tracked context</p>
              <h2>{activeMemory ? `${activeMemory.symbol}: ${activeMemory.theme}` : "Company memory"}</h2>
            </div>
          </div>
          <button className="icon-button" onClick={onClose} title="Close context" type="button">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {status === "loading" ? <p className="muted">Loading tracked context...</p> : null}
        {status === "error" ? <p className="form-error">{error}</p> : null}
        {status === "ready" && activeMemory ? (
          <div className="company-memory-content">
            <div className="company-memory-summary">
              <div>
                <span>First seen</span>
                <strong>{formatDateOnly(activeMemory.first_seen_at)}</strong>
              </div>
              <div>
                <span>Last update</span>
                <strong>{formatDateOnly(activeMemory.last_seen_at)}</strong>
              </div>
              <div>
                <span>Developments</span>
                <strong>{activeMemory.evidence_count}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>{memoryStatusLabel}</strong>
              </div>
            </div>

            <section className="research-card company-memory-section">
              <div className="research-card-header">
                <strong>What we know so far</strong>
              </div>
              <p>{activeMemory.description}</p>
              {activeMemory.latest_development ? <p><strong>Latest development:</strong> {activeMemory.latest_development}</p> : null}
              {activeMemory.thesis_points?.length ? (
                <div className="company-memory-thesis">
                  {activeMemory.thesis_points.map((point) => <span key={point}>{point}</span>)}
                </div>
              ) : null}
            </section>

            <section className="research-card company-memory-section">
              <div className="research-card-header">
                <strong>Timeline</strong>
              </div>
              {eventError ? <p className="form-error company-memory-event-error">{eventError}</p> : null}
              <div className="company-memory-timeline">
                {(activeMemory.events ?? []).map((event, index) => (
                  <article className="company-memory-event" key={event.id}>
                    <div className="company-memory-event-date">
                      <span>{formatDateOnly(event.event_date)}</span>
                      <strong>{event.event_type === "created" ? "Started tracking" : "New development"}</strong>
                    </div>
                    <div className="company-memory-event-body">
                      <div className="company-memory-event-title-row">
                        {event.headline ? <h3>{event.headline}</h3> : <span />}
                        {index > 0 ? (
                          <button
                            className="icon-button danger company-memory-delete-event"
                            disabled={deletingEventId === event.id}
                            onClick={() => setDeleteTarget(event)}
                            title="Remove from tracked context"
                            type="button"
                          >
                            <Trash2 size={16} aria-hidden="true" />
                          </button>
                        ) : null}
                      </div>
                      <p>{event.summary}</p>
                      <div className="company-memory-event-links">
                        {event.source_url ? <a href={event.source_url} rel="noreferrer" target="_blank">Full article</a> : null}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          </div>
        ) : null}
      </section>
      {deleteTarget ? (
        <ConfirmDialog
          item={{ symbol: activeMemory?.symbol, company_name: deleteTarget.headline || deleteTarget.summary }}
          message="This removes the item from tracked context. The original report stays unchanged."
          onCancel={() => setDeleteTarget(null)}
          onConfirm={deleteMemoryEvent}
          title="Remove context item?"
        />
      ) : null}
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

function noteSourceLabel(note) {
  if (note.research_item_id) {
    return "Research";
  }
  if (note.report_id) {
    return "Report";
  }
  return "Standalone";
}

function noteResourceActionTitle(note) {
  if (note.research_item_id) {
    return "View research";
  }
  if (note.report_id) {
    return "View report";
  }
  return "";
}

function noteMatchesSourceFilter(note, sourceFilter) {
  if (sourceFilter === "standalone") {
    return !note.report_id && !note.research_item_id;
  }
  if (sourceFilter === "report") {
    return Boolean(note.report_id) && !note.research_item_id;
  }
  if (sourceFilter === "research") {
    return Boolean(note.research_item_id);
  }
  return true;
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
      <section className="modal-panel note-modal-panel long-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">{report ? `Report ${reportPeriodDisplay(report)}` : researchItem ? `${researchItem.symbol} research` : "Notes"}</p>
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
  const title = report ? reportPeriodDisplay(report) : `${researchItem?.symbol} research`;
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
      <section className="modal-panel note-modal-panel long-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
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
  const [sourceFilter, setSourceFilter] = useState("all");
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
      if (sourceFilter !== "all") {
        query.set("source", sourceFilter);
      }
      const payload = await requestJson(`/api/notes?${query.toString()}`, { method: "GET" });
      setNotes(payload.items ?? []);
      setPayload(payload);
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load notes.");
      setStatus("error");
    }
  }, [filters.date_from, filters.date_to, page, resolvedFilter, selectedStock?.stock_id, sourceFilter]);

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
        noteMatchesSourceFilter(payload.note, sourceFilter) &&
        (resolvedFilter === "all" ||
          (resolvedFilter === "resolved" && payload.note.is_resolved) ||
          (resolvedFilter === "open" && !payload.note.is_resolved));
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
        noteMatchesSourceFilter(note, sourceFilter) &&
        (resolvedFilter === "all" ||
          (resolvedFilter === "resolved" && note.is_resolved) ||
          (resolvedFilter === "open" && !note.is_resolved));
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

  const openNoteResource = (note) => {
    if (note.research_item_id) {
      setBrowserRoute(`/research/${encodeURIComponent(note.research_item_id)}`);
      return;
    }
    if (note.report_id) {
      setBrowserRoute(`/reports/${encodeURIComponent(note.report_id)}`);
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
            <div className="resolved-filter source-filter" aria-label="Source filter">
              {[
                ["all", "All"],
                ["standalone", "Standalone"],
                ["report", "Report"],
                ["research", "Research"],
              ].map(([value, label]) => (
                <button
                  className={sourceFilter === value ? "resolved-filter-button active" : "resolved-filter-button"}
                  key={value}
                  onClick={() => { setSourceFilter(value); setPage(1); }}
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
              <col className="notes-source-col" />
              <col className="notes-created-col" />
              <col className="notes-resolved-col" />
              <col className="notes-actions-col" />
            </colgroup>
            <thead>
              <tr>
                <th>Company</th>
                <th>Note</th>
                <th>Source</th>
                <th>Created at</th>
                <th>Resolved</th>
                <th className="actions-cell">Actions</th>
              </tr>
            </thead>
            <tbody>
              {notes.length ? (
                notes.map((note) => (
                  <tr key={note.id} onClick={() => setSelectedNote(note)}>
                    <td data-label="Company">
                      <div className="mobile-card-title-row">
                        <div className="stock-cell">
                          <img className="stock-logo" {...stockLogoProps(note.logo_url)} alt="" />
                          <div>
                            <strong>{note.symbol}</strong>
                            <span>{note.company_name}</span>
                          </div>
                        </div>
                        <button className="mobile-open-button" onClick={(event) => { event.stopPropagation(); setSelectedNote(note); }} type="button">
                          Open
                        </button>
                      </div>
                    </td>
                    <td className="note-preview-cell" data-label="Note">{note.body}</td>
                    <td data-label="Source">
                      <span className="status-pill note-source-pill">{noteSourceLabel(note)}</span>
                    </td>
                    <td data-label="Created at">{formatDateTime(note.created_at)}</td>
                    <td data-label="Resolved">
                      <ReportToggle
                        checked={note.is_resolved}
                        offLabel="Open"
                        onChange={(next) => updateNote(note, { is_resolved: next })}
                        onLabel="Resolved"
                      />
                    </td>
                    <td className="actions-cell" data-label="Actions">
                      <button className="icon-button" onClick={(event) => { event.stopPropagation(); setSelectedNote(note); }} title="Edit note" type="button">
                        <Pencil size={17} aria-hidden="true" />
                      </button>
                      {note.report_id || note.research_item_id ? (
                        <button className="icon-button" onClick={(event) => { event.stopPropagation(); openNoteResource(note); }} title={noteResourceActionTitle(note)} type="button">
                          <MoveRight size={17} aria-hidden="true" />
                        </button>
                      ) : null}
                      <button className="icon-button danger" onClick={(event) => { event.stopPropagation(); setDeleteTarget(note); }} title="Delete note" type="button">
                        <Trash2 size={17} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="empty-table" colSpan={6}>
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
      <section className="modal-panel note-modal-panel long-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
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
    const key = String(note.created_at).slice(0, 10);
    return { ...groups, [key]: [...(groups[key] ?? []), note] };
  }, {});

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal-panel note-modal-panel long-modal-panel grouped-notes-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
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

function ResearchView({ portfolioItems = [], routeResearchId = "", watchlistItems = [], onAddToWatchlist, onEditItem, onMoveToPortfolio }) {
  const [researchMode, setResearchMode] = useState(routeResearchId ? "history" : "new");
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
  const [activeResearchRun, setActiveResearchRun] = useState(null);
  const selectedRelationship = useMemo(
    () => researchRelationshipForStock(selectedStock, portfolioItems, watchlistItems),
    [portfolioItems, selectedStock, watchlistItems],
  );

  useEffect(() => {
    setResearchType(defaultResearchTypeForRelationship(selectedRelationship));
  }, [selectedRelationship, selectedStock?.symbol]);

  useEffect(() => {
    if (routeResearchId) {
      setResearchMode("history");
    }
  }, [routeResearchId]);

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
      } catch {
        setError("Stock search is temporarily unavailable.");
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
    setActiveResearchRun(null);
    try {
      const response = await requestJson("/api/research/company", {
        method: "POST",
        timeoutMs: 60000,
        body: JSON.stringify({
          symbol: selectedStock.symbol,
          company_name: selectedStock.company_name,
          date_from: filters.date_from,
          date_to: filters.date_to,
          research_type: researchType,
        }),
      });
      if (response.mode === "deep_research" && response.research_run_id && response.status !== "completed") {
        setActiveResearchRun(response);
        setStatus("loading");
      } else {
        setPayload(response);
        setStatus("ready");
      }
    } catch (err) {
      setStatus("error");
      setError(err?.name === "AbortError" ? "Research timed out after 60 seconds. Try a shorter window or run it again." : err instanceof Error ? err.message : "Unable to run research.");
    }
  };

  useEffect(() => {
    const runId = activeResearchRun?.research_run_id || activeResearchRun?.id;
    if (!runId || status !== "loading") {
      return undefined;
    }
    let ignore = false;
    const pollRun = async () => {
      try {
        const response = await requestJson(`/api/research-runs/${encodeURIComponent(runId)}`, { method: "GET" });
        const run = response.run;
        if (ignore || !run) {
          return;
        }
        setActiveResearchRun(run);
        if (run.status === "completed" && run.research_item?.body) {
          setPayload({
            ...run.research_item.body,
            research_item_id: run.research_item.id,
            stock: run.research_item.body.stock || run.stock,
          });
          setStatus("ready");
          setActiveResearchRun(null);
        } else if (run.status === "failed") {
          setStatus("error");
          setError(run.error || "Deep research failed.");
          setActiveResearchRun(null);
        }
      } catch (err) {
        if (!ignore) {
          setStatus("error");
          setError(err instanceof Error ? err.message : "Unable to refresh deep research status.");
        }
      }
    };
    pollRun();
    const timer = window.setInterval(pollRun, 5000);
    return () => {
      ignore = true;
      window.clearInterval(timer);
    };
  }, [activeResearchRun?.research_run_id, activeResearchRun?.id, status]);

  const resetCompany = () => {
    setSelectedStock(null);
    setPayload(null);
    setSearch("");
  };

  const modeLabel = payload?.mode === "portfolio" ? "Portfolio thesis check" : payload?.mode === "watchlist" ? "Watchlist entry check" : payload?.mode === "deep_research" ? "Deep research" : "Company primer";
  const payloadRelationship = payload?.relationship ?? payload?.mode;
  const generatedResearchItem = researchItemFromPayload(payload);
  const canAddNote = Boolean(generatedResearchItem?.stock_id);
  const showResearchTypeSwitch = Boolean(selectedStock);
  const researchTypeOptions = selectedRelationship === "portfolio"
    ? [["portfolio_check", "Portfolio check"], ["company_primer", "Company primer"], ["deep_research", "Deep research"]]
    : selectedRelationship === "watchlist"
      ? [["watchlist_check", "Watchlist check"], ["company_primer", "Company primer"], ["deep_research", "Deep research"]]
      : [["company_primer", "Company primer"], ["deep_research", "Deep research"]];

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
        <button className={researchMode === "new" ? "view-tab active" : "view-tab"} onClick={() => { setResearchMode("new"); setBrowserRoute("/research"); }} type="button">
          New research
        </button>
        <button className={researchMode === "history" ? "view-tab active" : "view-tab"} onClick={() => { setResearchMode("history"); setBrowserRoute("/research"); }} type="button">
          History
        </button>
      </div>
      {researchMode === "history" ? <ResearchHistoryView routeResearchId={routeResearchId} /> : (
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
                    <button className={`${researchType === value ? "active" : ""} ${value === "deep_research" ? "deep-research-option" : ""}`.trim()} key={value} onClick={() => setResearchType(value)} type="button">
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
          <p>{activeResearchRun ? `${activeResearchRun.progress_step || "Running deep research"}${activeResearchRun.progress_pct ? ` (${activeResearchRun.progress_pct}%)` : ""}` : "Building focused research..."}</p>
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
              {generatedResearchItem && generatedResearchItem.research_type !== "deep_research" ? (
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
    deep_research: "Deep research",
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
    deep_research: "deep_research",
  }[mode] ?? "company_primer";
}

function researchSignalFromPayload(payload) {
  const research = payload?.research ?? {};
  return research.signal ?? research.watchlist_suitability ?? null;
}

function ResearchHistoryView({ routeResearchId = "" }) {
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
  const openedRouteResearchIdRef = useRef("");
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

  const openItem = async (item, options = {}) => {
    setError("");
    try {
      const detail = await requestJson(`/api/research-items/${item.id}`, { method: "GET" });
      setSelectedItem(detail.item);
      if (options.updateRoute !== false) {
        openedRouteResearchIdRef.current = item.id;
        setBrowserRoute(`/research/${encodeURIComponent(item.id)}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load research detail.");
    }
  };

  useEffect(() => {
    if (!routeResearchId) {
      if (openedRouteResearchIdRef.current) {
        openedRouteResearchIdRef.current = "";
        setSelectedItem(null);
      }
      return;
    }
    if (openedRouteResearchIdRef.current === routeResearchId) {
      return;
    }
    openedRouteResearchIdRef.current = routeResearchId;
    openItem({ id: routeResearchId }, { updateRoute: false });
  }, [routeResearchId]);

  const closeItem = () => {
    setSelectedItem(null);
    if (routeResearchId) {
      openedRouteResearchIdRef.current = "";
      setBrowserRoute("/research", true);
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
                ["deep_research", "Deep"],
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
                    <td data-label="Company">
                      <div className="mobile-card-title-row">
                        <div className="stock-cell">
                          <img className="stock-logo" {...stockLogoProps(item.logo_url)} alt="" />
                          <div>
                            <strong>{item.symbol}</strong>
                            <span>{item.company_name}</span>
                          </div>
                        </div>
                        <button className="mobile-open-button" onClick={(event) => { event.stopPropagation(); openItem(item); }} type="button">
                          Open
                        </button>
                      </div>
                    </td>
                    <td data-label="Type"><span className="status-pill">{researchTypeLabel(item.research_type)}</span></td>
                    <td data-label="Signal"><span className="research-signal-pill">{researchHumanLabel(item.signal || "Unknown")}</span></td>
                    <td data-label="Created at">{formatDateTime(item.created_at)}</td>
                    <td className="actions-cell" data-label="Notes">
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
                    <td className="actions-cell" data-label="Actions">
                      {item.research_type !== "deep_research" ? (
                        <button className="icon-button" onClick={(event) => { event.stopPropagation(); setShareTarget(item); }} title="Share research" type="button">
                          <Share2 size={17} aria-hidden="true" />
                        </button>
                      ) : null}
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
          onClose={closeItem}
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
      <section className="modal-panel research-preview-panel long-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
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
            {item.research_type !== "deep_research" ? (
              <button className="secondary-button compact-button" onClick={onShare} type="button">
                <Share2 size={16} aria-hidden="true" />
                Share research
              </button>
            ) : null}
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
      <section className="modal-panel share-research-panel long-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
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
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
    notation: Math.abs(number) >= 1000000 ? "compact" : "standard",
  }).format(number);
}

function formatStatementNumber(value) {
  if (value === null || value === undefined || value === "") {
    return "N/A";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "N/A";
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
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

function formatDividendYield(value) {
  if (value === null || value === undefined || value === "" || Number(value) === 0) {
    return "-";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "-";
  }
  return `${number.toFixed(2)}%`;
}

const currencyMetricKeys = new Set([
  "capitalExpenditure",
  "cashAndCashEquivalents",
  "ebitda",
  "enterprise_value",
  "eps",
  "fcf_per_share",
  "freeCashFlow",
  "free_cash_flow",
  "grossProfit",
  "gross_profit",
  "market_cap",
  "netIncome",
  "net_debt",
  "net_income",
  "operatingCashFlow",
  "operatingIncome",
  "operating_income",
  "price",
  "revenue",
  "revenue_per_share",
  "totalAssets",
  "totalDebt",
  "totalLiabilities",
  "totalStockholdersEquity",
  "year_high",
  "year_low",
]);

function metricValue(key, value) {
  if (key === "dividend_yield_pct") {
    return formatDividendYield(value);
  }
  if (key.includes("growth")) {
    return formatMetricPercent(value);
  }
  if (key.includes("margin") || key === "roe_pct" || key.includes("yield")) {
    return formatMetricPercent(value);
  }
  if (currencyMetricKeys.has(key)) {
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
    pb: "P/B",
    ev_to_ebitda: "EV/EBITDA",
    ev_to_sales: "EV/Sales",
    fcf_yield_pct: "FCF yield",
    dividend_yield_pct: "Dividend yield",
    eps: "EPS",
    revenue: "Revenue",
    grossProfit: "Gross profit",
    gross_profit: "Gross profit",
    operatingIncome: "Operating income",
    operating_income: "Operating income",
    netIncome: "Net income",
    net_income: "Net income",
    freeCashFlow: "Free cash flow",
    free_cash_flow: "Free cash flow",
    operatingCashFlow: "Operating cash flow",
    capitalExpenditure: "Capex",
    cashAndCashEquivalents: "Cash",
    totalDebt: "Total debt",
    totalAssets: "Total assets",
    totalLiabilities: "Total liabilities",
    totalStockholdersEquity: "Equity",
    calendarYear: "Year",
    period: "Period",
    ebitda: "EBITDA",
    net_debt: "Net debt",
    shares_outstanding: "Shares out.",
    enterprise_value: "Enterprise value",
    revenue_growth_pct: "Revenue growth",
    eps_growth_pct: "EPS growth",
    ebitda_growth_pct: "EBITDA growth",
    fcf_growth_pct: "FCF growth",
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
    roic_pct: "ROIC",
    debt_to_equity: "Debt/equity",
    current_ratio: "Current ratio",
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
    return report.fiscal_year ? `FY ${report.fiscal_year}` : "Fiscal year";
  }
  const explicitQuarter = report.fiscal_quarter || report.fiscalQuarter || report.period || report.quarter;
  const quarterText = explicitQuarter ? String(explicitQuarter).trim().toUpperCase() : "";
  const fiscalYear = report.fiscal_year || report.fiscalYear || report.calendarYear || report.year;
  if (quarterText && !["FY", "ANNUAL"].includes(quarterText)) {
    if (/^Q[1-4]\s+\d{4}$/.test(quarterText)) {
      return quarterText;
    }
    const quarterMatch = quarterText.match(/^Q?([1-4])$/);
    if (quarterMatch) {
      return fiscalYear ? `Q${quarterMatch[1]} ${fiscalYear}` : `Q${quarterMatch[1]}`;
    }
    if (quarterText.startsWith("Q")) {
      return fiscalYear && !quarterText.includes(String(fiscalYear)) ? `${quarterText} ${fiscalYear}` : quarterText;
    }
  }
  if (report.report_type === "upcoming") {
    return "Upcoming";
  }
  return `Quarter ${index + 1}`;
}

function EarningsReportsPanel({ reports = [], nextEarningsDate }) {
  const items = Array.isArray(reports) ? reports.filter((report) => report && report.report_type !== "fy") : [];
  const defaultActiveIndex = useMemo(() => {
    const today = new Date();
    today.setHours(23, 59, 59, 999);
    const index = items.findIndex((report) => {
      const date = parseDateOnlyStrict(report?.date);
      return date && date <= today;
    });
    return index >= 0 ? index : 0;
  }, [items]);
  const [activeIndex, setActiveIndex] = useState(defaultActiveIndex);
  const activeReport = items[Math.min(activeIndex, Math.max(items.length - 1, 0))];

  useEffect(() => {
    setActiveIndex(defaultActiveIndex);
  }, [defaultActiveIndex, items.length]);

  useEffect(() => {
    if (activeIndex >= items.length || activeIndex < 0) {
      setActiveIndex(defaultActiveIndex);
    }
  }, [activeIndex, defaultActiveIndex, items.length]);

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
                <span>{activeReport.report_type === "upcoming" ? "Upcoming report" : activeReport.report_type === "fy" ? "Fiscal year report" : "Quarterly report"}</span>
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
  const firstCoord = coordinate(visiblePoints[0], 0);
  const lastCoord = coordinate(visiblePoints[visiblePoints.length - 1], visiblePoints.length - 1);
  const areaPath = `${path} L ${lastCoord.x.toFixed(2)} ${height - bottom} L ${firstCoord.x.toFixed(2)} ${height - bottom} Z`;
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
          <path className="price-chart-area" d={areaPath} />
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

function ResearchMarketSnapshot({ marketData, showEarnings = true }) {
  if (!marketData) {
    return null;
  }
  const metrics = marketData.metrics || {};
  const metricEntries = [
    "price",
    "market_cap",
    "pe",
    "ps",
    "pb",
    "ev_to_ebitda",
    "ev_to_sales",
    "fcf_yield_pct",
    "dividend_yield_pct",
    "eps",
    "revenue",
    "gross_profit",
    "ebitda",
    "operating_income",
    "net_income",
    "free_cash_flow",
    "revenue_growth_pct",
    "eps_growth_pct",
    "ebitda_growth_pct",
    "fcf_growth_pct",
    "revenue_per_share",
    "fcf_per_share",
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
    "roe_pct",
    "roic_pct",
    "debt_to_equity",
    "current_ratio",
    "shares_outstanding",
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
        {showEarnings ? <EarningsReportsPanel reports={marketData.earnings_reports ?? []} nextEarningsDate={marketData.next_earnings_date} /> : null}
      </div>
    </section>
  );
}

function recomputeDeepDcf(base, assumptions) {
  const latestRevenue = Number(base?.latest_revenue);
  const shares = Number(base?.shares_outstanding);
  const netDebt = Number(base?.net_debt || 0);
  const currentPrice = Number(base?.current_price);
  const years = Number(assumptions?.projection_years || 5);
  if (!Number.isFinite(latestRevenue) || !Number.isFinite(shares) || shares === 0) {
    return { projection: [], intrinsic_value_per_share: null, upside_downside_pct: null };
  }
  const growth = Number(assumptions.revenue_growth_pct || 0) / 100;
  const fcfMargin = Number(assumptions.fcf_margin_pct || 0) / 100;
  const discount = Math.max(Number(assumptions.wacc_pct || 9) / 100, 0.001);
  const terminalGrowth = Math.min(Number(assumptions.terminal_growth_pct || 2.5) / 100, discount - 0.001);
  let revenue = latestRevenue;
  let presentValueSum = 0;
  const projection = [];
  for (let year = 1; year <= years; year += 1) {
    revenue *= 1 + growth;
    const freeCashFlow = revenue * fcfMargin;
    const presentValue = freeCashFlow / ((1 + discount) ** year);
    presentValueSum += presentValue;
    projection.push({ year, revenue, free_cash_flow: freeCashFlow, present_value: presentValue });
  }
  const terminalFcf = (projection.at(-1)?.free_cash_flow || 0) * (1 + terminalGrowth);
  const terminalValue = terminalFcf / Math.max(discount - terminalGrowth, 0.001);
  const terminalPresentValue = terminalValue / ((1 + discount) ** years);
  const enterpriseValue = presentValueSum + terminalPresentValue;
  const equityValue = enterpriseValue - netDebt;
  const intrinsic = equityValue / shares;
  const upside = Number.isFinite(currentPrice) && currentPrice !== 0 ? ((intrinsic / currentPrice) - 1) * 100 : null;
  return {
    projection,
    terminal_value: terminalValue,
    enterprise_value: enterpriseValue,
    equity_value: equityValue,
    intrinsic_value_per_share: intrinsic,
    upside_downside_pct: upside,
  };
}

function impliedGrowthForCurrentDcf(base, assumptions) {
  const currentPrice = Number(base?.current_price);
  const latestRevenue = Number(base?.latest_revenue);
  const shares = Number(base?.shares_outstanding);
  if (!Number.isFinite(currentPrice) || currentPrice === 0 || !Number.isFinite(latestRevenue) || !Number.isFinite(shares) || shares === 0) {
    return null;
  }
  let low = -30;
  let high = 50;
  const targetPrice = currentPrice;
  for (let index = 0; index < 48; index += 1) {
    const mid = (low + high) / 2;
    const result = recomputeDeepDcf(base, { ...assumptions, revenue_growth_pct: mid });
    const intrinsic = Number(result.intrinsic_value_per_share);
    if (!Number.isFinite(intrinsic)) {
      return null;
    }
    if (intrinsic < targetPrice) {
      low = mid;
    } else {
      high = mid;
    }
  }
  return (low + high) / 2;
}

function DeepResearchDcfCalculator({ dcf }) {
  const [assumptions, setAssumptions] = useState(() => dcf?.assumptions || {});
  useEffect(() => {
    setAssumptions(dcf?.assumptions || {});
  }, [dcf]);
  if (!dcf) {
    return null;
  }
  const result = recomputeDeepDcf(dcf.base || {}, assumptions);
  const sources = dcf.assumption_sources || {};
  const impliedGrowth = impliedGrowthForCurrentDcf(dcf.base || {}, assumptions);
  const defaultGrowth = Number(assumptions.revenue_growth_pct);
  const analystGrowth = Number(sources.analyst_revenue_growth_pct);
  const showAnalystGrowth = Number.isFinite(analystGrowth) && (!Number.isFinite(defaultGrowth) || Math.abs(analystGrowth - defaultGrowth) > 0.05);
  const updateAssumption = (key, value) => {
    setAssumptions((current) => ({ ...current, [key]: Number(value) }));
  };
  const controls = [
    ["revenue_growth_pct", "Revenue growth", -20, 35, 0.5],
    ["fcf_margin_pct", "FCF margin", -10, 40, 0.5],
    ["wacc_pct", "WACC", 4, 18, 0.25],
    ["terminal_growth_pct", "Terminal growth", 0, 5, 0.25],
  ];
  return (
    <section className="research-card deep-dcf-card">
      <div className="research-card-header">
        <h3>DCF calculator</h3>
      </div>
      <div className="deep-dcf-summary">
        <div>
          <span>Intrinsic value</span>
          <strong>{metricValue("price", result.intrinsic_value_per_share)}</strong>
        </div>
        <div>
          <span>Current price</span>
          <strong>{metricValue("price", dcf.base?.current_price)}</strong>
        </div>
        <div>
          <span>Upside / downside</span>
          <strong className={Number(result.upside_downside_pct) >= 0 ? "positive" : "negative"}>{formatMetricPercent(result.upside_downside_pct)}</strong>
        </div>
        <div>
          <span>Default revenue growth</span>
          <strong>{formatMetricPercent(assumptions.revenue_growth_pct)}</strong>
          <small>{sources.revenue_growth_pct?.source_label || "Base assumption"}</small>
        </div>
        {showAnalystGrowth ? (
          <div>
            <span>Analyst growth</span>
            <strong>{formatMetricPercent(sources.analyst_revenue_growth_pct)}</strong>
            <small>Nearest available estimate</small>
          </div>
        ) : null}
        <div>
          <span>Market-implied growth</span>
          <strong>{formatMetricPercent(impliedGrowth ?? sources.market_implied_revenue_growth_pct)}</strong>
          <small>Growth needed to match current price</small>
        </div>
        <div>
          <span>Provider DCF fair value</span>
          <strong>{metricValue("price", dcf.provider_dcf?.dcf)}</strong>
          <small>
            {dcf.provider_dcf?.date || "Reference model"}
            {dcf.provider_dcf?.upside_downside_pct !== null && dcf.provider_dcf?.upside_downside_pct !== undefined
              ? `, ${formatMetricPercent(dcf.provider_dcf.upside_downside_pct)} vs current`
              : ""}
          </small>
        </div>
      </div>
      <div className="deep-dcf-controls">
        {controls.map(([key, label, min, max, step]) => (
          <label key={key}>
            <span>{label}</span>
            <div className="deep-dcf-input-row">
              <input max={max} min={min} onChange={(event) => updateAssumption(key, event.target.value)} step={step} type="range" value={assumptions[key] ?? 0} />
              <input max={max} min={min} onChange={(event) => updateAssumption(key, event.target.value)} step={step} type="number" value={assumptions[key] ?? 0} />
            </div>
          </label>
        ))}
      </div>
      <div className="deep-dcf-projection">
        {result.projection.map((row) => (
          <div key={row.year}>
            <span>Year {row.year}</span>
            <strong>{formatCompactNumber(row.free_cash_flow)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function SimpleDeepChart({ artifact }) {
  const [hoverIndex, setHoverIndex] = useState(null);
  const series = artifact?.data?.series || [];
  const suffix = artifact?.data?.value_suffix || "";
  if (series.length < 2) {
    return null;
  }
  const values = series.map((point) => Number(point.value ?? point.close)).filter((value) => Number.isFinite(value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 520;
  const height = 170;
  const left = 42;
  const right = 12;
  const top = 14;
  const bottom = 32;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const coordinate = (point, index) => {
    const value = Number(point.value ?? point.close);
    const isBar = (artifact?.data?.chart_type || "bar") !== "line";
    return {
      x: isBar ? left + ((index + 0.5) / Math.max(1, series.length)) * plotWidth : left + (index / Math.max(1, series.length - 1)) * plotWidth,
      y: top + (1 - (value - min) / range) * plotHeight,
      value,
    };
  };
  const chartType = artifact?.data?.chart_type || "bar";
  const hovered = hoverIndex === null ? null : series[hoverIndex];
  const hoveredCoord = hovered ? coordinate(hovered, hoverIndex) : null;
  const handleHover = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - bounds.left) / bounds.width) * width;
    const ratio = Math.min(1, Math.max(0, (svgX - left) / plotWidth));
    if ((artifact?.data?.chart_type || "bar") === "line") {
      setHoverIndex(Math.round(ratio * (series.length - 1)));
    } else {
      setHoverIndex(Math.min(series.length - 1, Math.floor(ratio * series.length)));
    }
  };
  const path = series.map((point, index) => {
    const { x, y } = coordinate(point, index);
    return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");
  const firstCoord = coordinate(series[0], 0);
  const lastCoord = coordinate(series[series.length - 1], series.length - 1);
  const areaPath = `${path} L ${lastCoord.x.toFixed(2)} ${height - bottom} L ${firstCoord.x.toFixed(2)} ${height - bottom} Z`;
  const avg = artifact?.data?.average;
  const avgY = Number.isFinite(Number(avg)) ? top + (1 - (Number(avg) - min) / range) * plotHeight : null;
  return (
    <div className="deep-chart">
      <div className="deep-chart-stats">
        <span>Min {formatCompactNumber(artifact?.data?.min)}{suffix}</span>
        <span>Avg {formatCompactNumber(avg)}{suffix}</span>
        <span>Max {formatCompactNumber(artifact?.data?.max)}{suffix}</span>
      </div>
      <div className="deep-chart-plot" onMouseLeave={() => setHoverIndex(null)} onMouseMove={handleHover}>
        {hovered && hoveredCoord ? (
          <div className="deep-chart-tooltip" style={{ left: `${(hoveredCoord.x / width) * 100}%` }}>
            <strong>{formatCompactNumber(hovered.value ?? hovered.close)}{suffix}</strong>
            <span>{formatDeepPeriodLabel(hovered, artifact?.data?.period)}</span>
          </div>
        ) : null}
      <svg className="deep-chart-svg" viewBox={`0 0 ${width} ${height}`}>
        {avgY !== null ? <line className="deep-chart-average" x1={left} x2={width - right} y1={avgY} y2={avgY} /> : null}
        {chartType === "line" ? (
          <>
            <path className="deep-chart-area" d={areaPath} />
            <path d={path} fill="none" stroke="#f4c430" strokeLinecap="round" strokeWidth="2.5" />
          </>
        ) : (
          series.map((point, index) => {
            const { x, y, value } = coordinate(point, index);
            const barWidth = Math.max(8, plotWidth / series.length - 7);
            const zeroY = min < 0 && max > 0 ? top + (1 - (0 - min) / range) * plotHeight : height - bottom;
            const barY = Math.min(y, zeroY);
            const barHeight = Math.max(1, Math.abs(zeroY - y));
            return <rect className={value < 0 ? "deep-chart-bar negative" : "deep-chart-bar"} height={barHeight} key={`${point.date}-${index}`} width={barWidth} x={x - barWidth / 2} y={barY} />;
          })
        )}
        {series.map((point, index) => {
          const shouldShow = series.length <= 12 || index === 0 || index === series.length - 1 || index === Math.floor((series.length - 1) / 2);
          if (!shouldShow) {
            return null;
          }
          const { x } = coordinate(point, index);
          return (
            <text className="chart-axis-label-charts" key={`${point.date}-label`} textAnchor="middle" x={x} y={height - 8}>
              {formatDeepPeriodLabel(point, artifact?.data?.period)}
            </text>
          );
        })}
      </svg>
      </div>
    </div>
  );
}

function formatDeepPeriodLabel(point, period) {
  if (point?.label) {
    if (period === "quarter") {
      const [quarter, year] = point.label.split(" ");
      return `${quarter} ${year.slice(-2)}`;
    }
    return point.label;
  }
  if (period === "quarter") {
    return point?.period || point?.date || "";
  }
  const date = parseChartDate(point?.date);
  if (Number.isNaN(date.getTime())) {
    return point?.date || "";
  }
  return String(date.getFullYear());
}

function DeepResearchArtifacts({ artifacts }) {
  const [period, setPeriod] = useState("annual");
  const visibleArtifacts = Array.isArray(artifacts)
    ? artifacts.filter((artifact) => (artifact?.data?.period || "annual") === period).slice(0, 12)
    : [];
  if (!visibleArtifacts.length) {
    return null;
  }
  return (
    <section className="research-card deep-artifacts-card">
      <div className="research-card-header">
        <h3>Charts and metrics</h3>
        <div className="deep-chart-tabs">
          {["annual", "quarter"].map((value) => (
            <button className={period === value ? "active" : ""} key={value} onClick={() => setPeriod(value)} type="button">
              {value === "annual" ? "Annual" : "Quarterly"}
            </button>
          ))}
        </div>
      </div>
      <div className="deep-artifact-grid">
        {visibleArtifacts.map((artifact, index) => {
          const series = artifact?.data?.series || [];
          const last = series.at(-1)?.value ?? series.at(-1)?.close;
          return (
            <div className="deep-artifact-tile" key={`${artifact.title}-${index}`}>
              <span>{artifact.title}</span>
              <strong>{formatCompactNumber(last)}{artifact?.data?.value_suffix || ""}</strong>
              <SimpleDeepChart artifact={artifact} />
            </div>
          );
        })}
      </div>
    </section>
  );
}

function stripSourceBrackets(value) {
  return stripInlineSourceDomains(value).replace(/\s*\[[^[\]]+\]/g, "");
}

function DeepResearchList({ title, items }) {
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
              <p>{stripSourceBrackets(typeof item === "string" ? item : JSON.stringify(item))}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No material points returned.</p>
      )}
    </section>
  );
}

function sourceByKeyMap(sources) {
  return new Map((Array.isArray(sources) ? sources : []).map((source) => [source.source_key, source]));
}

function hasDataError(value) {
  if (!value || typeof value !== "object") {
    return false;
  }
  return Object.keys(value).some((key) => ["error", "error message"].includes(String(key).trim().toLowerCase()));
}

function hasAnnualReportError(value) {
  if (!value || typeof value !== "object") {
    return false;
  }
  return hasDataError(value) || hasDataError(value.metadata) || hasDataError(value.metadata?.report);
}

function DeepSourceChips({ sourceKeys, sourceMap, onOpenResource }) {
  const keys = Array.isArray(sourceKeys) ? sourceKeys.filter(Boolean) : [];
  if (!keys.length) {
    return null;
  }
  return (
    <div className="deep-source-chips">
      {keys.map((key) => {
        const source = sourceMap.get(key);
        if (!source) {
          return null;
        }
        if (source.source_type === "annual_report_json" && hasAnnualReportError(source)) {
          return null;
        }
        if (["financial_statement", "earnings_transcript", "annual_report_json"].includes(source.source_type)) {
          return (
            <button key={key} onClick={() => onOpenResource(source)} type="button">
              {source.title || key}
            </button>
          );
        }
        if (source.url) {
          return (
            <a href={source.url} key={key} rel="noreferrer" target="_blank">
              {source.title || key}
            </a>
          );
        }
        return null;
      })}
    </div>
  );
}

function DeepResearchSections({ sections, sourceMap, onOpenResource }) {
  const items = Array.isArray(sections) ? sections : [];
  if (!items.length) {
    return null;
  }
  return items.map((section, index) => (
    <section className="research-card deep-section-card" key={`${section?.title || "section"}-${index}`}>
      <div className="research-card-header">
        <h3>{section?.title || `Section ${index + 1}`}</h3>
      </div>
      {section?.summary ? <p className="deep-section-summary">{stripSourceBrackets(section.summary)}</p> : null}
      {Array.isArray(section?.bullets) && section.bullets.length ? (
        <ul>
          {section.bullets.map((item, itemIndex) => (
            <li key={`${section?.title || "section"}-${itemIndex}`}>
              <span className="research-list-index">{String(itemIndex + 1).padStart(2, "0")}</span>
              <p>{stripSourceBrackets(item)}</p>
            </li>
          ))}
        </ul>
      ) : null}
      <DeepSourceChips onOpenResource={onOpenResource} sourceKeys={section?.source_keys} sourceMap={sourceMap} />
    </section>
  ));
}

function statementTableColumns(rows) {
  return rows.slice(0, 3).map((row, index) => ({
    key: `${row.date || row.calendarYear || index}`,
    label: row.date || row.calendarYear || `Period ${index + 1}`,
    row,
  }));
}

function statementLineItems(rows) {
  const groups = [
    ["Revenue and gross profit", ["revenue", "costOfRevenue", "grossProfit", "grossProfitRatio"]],
    ["Operating expenses", ["researchAndDevelopmentExpenses", "sellingGeneralAndAdministrativeExpenses", "generalAndAdministrativeExpenses", "sellingAndMarketingExpenses", "operatingExpenses", "operatingIncome", "operatingIncomeRatio"]],
    ["Earnings", ["ebitda", "ebitdaratio", "interestExpense", "incomeBeforeTax", "incomeTaxExpense", "netIncome", "netIncomeRatio", "eps", "epsdiluted", "weightedAverageShsOut", "weightedAverageShsOutDil"]],
    ["Current assets", ["cashAndCashEquivalents", "shortTermInvestments", "cashAndShortTermInvestments", "netReceivables", "inventory", "otherCurrentAssets", "totalCurrentAssets"]],
    ["Long-term assets", ["propertyPlantEquipmentNet", "goodwill", "intangibleAssets", "longTermInvestments", "taxAssets", "totalNonCurrentAssets", "totalAssets"]],
    ["Liabilities and equity", ["accountPayables", "shortTermDebt", "deferredRevenue", "totalCurrentLiabilities", "longTermDebt", "totalDebt", "totalNonCurrentLiabilities", "totalLiabilities", "retainedEarnings", "totalStockholdersEquity", "totalEquity"]],
    ["Cash flow", ["netIncome", "depreciationAndAmortization", "stockBasedCompensation", "changeInWorkingCapital", "netCashProvidedByOperatingActivities", "operatingCashFlow", "capitalExpenditure", "freeCashFlow", "netCashUsedForInvestingActivites", "acquisitionsNet", "netCashUsedProvidedByFinancingActivities", "commonStockRepurchased", "dividendsPaid"]],
  ];
  const highlight = new Set(["revenue", "grossProfit", "operatingIncome", "ebitda", "netIncome", "totalCurrentAssets", "totalAssets", "totalCurrentLiabilities", "totalDebt", "totalLiabilities", "totalStockholdersEquity", "totalEquity", "operatingCashFlow", "netCashProvidedByOperatingActivities", "freeCashFlow"]);
  const available = new Set(rows.flatMap((row) => Object.keys(row || {})));
  const used = new Set();
  const output = [];
  groups.forEach(([title, keys]) => {
    const items = keys.filter((key) => available.has(key) && !used.has(key));
    if (!items.length) {
      return;
    }
    output.push({ type: "category", label: title });
    items.forEach((key) => {
      used.add(key);
      output.push({ type: "item", key, highlight: highlight.has(key) });
    });
  });
  return output.slice(0, 80);
}

function DeepResourceModal({ resource, onClose }) {
  if (!resource) {
    return null;
  }
  const metadata = resource.metadata || {};
  const rows = Array.isArray(metadata.rows) ? metadata.rows : [];
  const columns = statementTableColumns(rows);
  const lineItems = statementLineItems(rows);
  const transcriptBlocks = splitTranscriptBySpeaker(metadata.content || resource.excerpt || "");
  return (
    <div className="modal-backdrop report-preview-backdrop" onMouseDown={onClose}>
      <section className="modal-panel research-preview-panel long-modal-panel deep-resource-modal" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="report-modal-header">
          <div>
            <p className="eyebrow">{researchHumanLabel(resource.source_type)}</p>
            <h2>{resource.title}</h2>
          </div>
          <button className="icon-button" onClick={onClose} title="Close" type="button">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="deep-resource-content">
          {resource.source_type === "earnings_transcript" ? (
            <article className="deep-transcript-body">
              {transcriptBlocks.length ? (
                transcriptBlocks.map((block, index) => (
                  <section className="deep-transcript-speaker" key={`${block.speaker}-${index}`}>
                    <h3>{block.speaker}</h3>
                    <p>{block.text}</p>
                  </section>
                ))
              ) : (
                <p>Transcript content unavailable.</p>
              )}
            </article>
          ) : null}
          {resource.source_type === "financial_statement" ? (
            <div className="deep-statement-table-wrap">
              <table className="deep-statement-table">
                <thead>
                  <tr>
                    <th>Line item</th>
                    {columns.map((column) => <th key={column.key}>{column.label}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {lineItems.map((lineItem) => (
                    lineItem.type === "category" ? (
                      <tr className="statement-category-row" key={`category-${lineItem.label}`}>
                        <td colSpan={columns.length + 1}>{lineItem.label}</td>
                      </tr>
                    ) : (
                      <tr className={lineItem.highlight ? "statement-highlight-row" : ""} key={lineItem.key}>
                        <td>{metricLabel(lineItem.key)}</td>
                        {columns.map((column) => (
                          <td data-period={column.label} key={column.key}>{formatStatementNumber(column.row?.[lineItem.key])}</td>
                        ))}
                      </tr>
                    )
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {resource.source_type === "annual_report_json" ? (
            metadata.extract ? (
              <article className="annual-report-extract">
                {metadata.extract.summary ? <p>{metadata.extract.summary}</p> : null}
                {Array.isArray(metadata.extract.sections) ? metadata.extract.sections.map((section, index) => (
                  <section key={`${section.title || "section"}-${index}`}>
                    <h3>{section.title || `Section ${index + 1}`}</h3>
                    {Array.isArray(section.bullets) && section.bullets.length ? (
                      <ul>
                        {section.bullets.map((item, itemIndex) => <li key={`${section.title || index}-${itemIndex}`}>{item}</li>)}
                      </ul>
                    ) : null}
                  </section>
                )) : null}
              </article>
            ) : (
              <pre className="deep-json-report">{JSON.stringify(metadata.report || metadata, null, 2)}</pre>
            )
          ) : null}
        </div>
      </section>
    </div>
  );
}

function splitTranscriptBySpeaker(content) {
  const text = String(content || "").replace(/\r/g, "").trim();
  if (!text) {
    return [];
  }
  const speakerRegex = /(?:^|\n)([A-Z][A-Za-z .,'-]{1,80})(?:\s+-\s+[A-Za-z .,'-]{1,100})?:\s*/g;
  const matches = [...text.matchAll(speakerRegex)];
  if (matches.length < 2) {
    return text.split(/\n{2,}/).filter(Boolean).map((paragraph, index) => ({ speaker: index === 0 ? "Transcript" : "Continued", text: paragraph.trim() }));
  }
  return matches.map((match, index) => {
    const start = match.index + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index : text.length;
    return {
      speaker: match[1].trim(),
      text: text.slice(start, end).trim(),
    };
  }).filter((block) => block.text);
}

function stockGradeTone(item) {
  const text = `${item?.newGrade || ""} ${item?.grade || ""} ${item?.rating || ""} ${item?.action || ""}`.toLowerCase();
  if (/\b(strong buy|buy|outperform|overweight|positive|accumulate)\b/.test(text)) {
    return "buy";
  }
  if (/\b(sell|underperform|underweight|negative|reduce)\b/.test(text)) {
    return "sell";
  }
  return "hold";
}

function stockGradeLabel(item) {
  return item?.newGrade || item?.grade || item?.rating || item?.ratingRecommendation || "Hold";
}

function stockGradePrice(item) {
  const value =
    item?.price ??
    item?.priceTarget ??
    item?.targetPrice ??
    item?.newPriceTarget ??
    item?.previousPriceTarget ??
    item?.priceTargetNew ??
    item?.priceTargetCurrent ??
    item?.priceWhenPosted ??
    item?.publishedPrice ??
    item?.currentPrice;
  return value === null || value === undefined || value === "" ? "" : metricValue("price", value);
}

function DeepResearchDataLibrary({ deep, earningsReports = [], nextEarningsDate, stockGrades = [], onOpenResource }) {
  const [statementPeriod, setStatementPeriod] = useState("annual");
  const sources = Array.isArray(deep.sources) ? deep.sources : [];
  const transcripts = Array.isArray(deep.transcripts) ? deep.transcripts : [];
  const filings = Array.isArray(deep.filings) ? deep.filings : [];
  const annualReportSources = sources.filter((source) => source.source_type === "annual_report_json" && !hasAnnualReportError(source));
  const transcriptSources = transcripts.slice(0, 5).map((item, index) => sources.find((candidate) => candidate.source_key === `transcript_${index + 1}`)).filter(Boolean);
  const hasEarningsReports = Array.isArray(earningsReports) && (earningsReports.some((report) => report && report.report_type !== "fy") || nextEarningsDate);
  const statementItems = [
    { label: "Income statement", annual: "income_annual", quarter: "income_quarter" },
    { label: "Balance sheet", annual: "balance_annual", quarter: "balance_quarter" },
    { label: "Cash flow", annual: "cashflow_annual", quarter: "cashflow_quarter" },
  ];
  const activeStatementSources = statementItems
    .map((item) => ({ ...item, source: sources.find((source) => source.source_key === item[statementPeriod]) }))
    .filter((item) => item.source);
  return (
    <div className="deep-material-layout">
      <div className="deep-library-grid deep-material-row">
        <div className="deep-material-panel deep-material-statements">
          <div className="deep-material-heading">
            <strong>Financial statements</strong>
            <div className="deep-material-tabs compact" aria-label="Statement period">
              {[
                ["annual", "Annual"],
                ["quarter", "Quarterly"],
              ].map(([key, label]) => (
                <button className={statementPeriod === key ? "active" : ""} key={key} onClick={() => setStatementPeriod(key)} type="button">
                  {label}
                </button>
              ))}
            </div>
          </div>
          {activeStatementSources.length ? (
            <div className="deep-material-list">
              {activeStatementSources.map((item) => (
                <button key={item.source.source_key} onClick={() => onOpenResource(item.source)} type="button">
                  {item.label}
                </button>
              ))}
            </div>
          ) : (
            <span>No statement available for this period.</span>
          )}
          <div className="deep-material-subsection">
            <strong>SEC filings / 10-K</strong>
            <div className="deep-material-list">
              {annualReportSources.slice(0, 1).map((source) => (
                <button key={source.source_key} onClick={() => onOpenResource(source)} type="button">{source.title}</button>
              ))}
              {filings.slice(0, 6).map((item, index) => {
                const url = item.finalLink || item.link || item.url || item.filingUrl;
                const title = item.type || item.formType || item.title || `Filing ${index + 1}`;
                return url ? <a href={url} key={`${title}-${index}`} rel="noreferrer" target="_blank">{title}</a> : <span key={`${title}-${index}`}>{title}</span>;
              })}
            </div>
            {!filings.length && !annualReportSources.length ? <span>No filings available.</span> : null}
          </div>
        </div>
        <StockGradesPanel stockGrades={stockGrades} />
      </div>
      <div className="deep-library-grid deep-material-row">
        {hasEarningsReports ? (
          <div className="deep-material-panel deep-earnings-report-panel">
            <EarningsReportsPanel reports={earningsReports} nextEarningsDate={nextEarningsDate} />
          </div>
        ) : (
          <div className="deep-material-panel deep-earnings-report-panel">
            <strong>Earnings reports</strong>
            <span>No earnings reports available.</span>
          </div>
        )}
        <div className="deep-material-panel">
          <strong>Earnings transcripts</strong>
          <div className="deep-material-list deep-material-list-stacked">
            {transcriptSources.map((source) => (
              <button key={source.source_key} onClick={() => onOpenResource(source)} type="button">{source.title}</button>
            ))}
          </div>
          {!transcriptSources.length ? <span>No transcripts available.</span> : null}
        </div>
      </div>
    </div>
  );
}

function StockGradesPanel({ stockGrades = [] }) {
  const items = Array.isArray(stockGrades) ? stockGrades.slice(0, 10) : [];
  return (
    <div className="deep-material-panel deep-stock-grades-panel">
      <strong>Stock grades</strong>
      {items.length ? (
        <div className="stock-grade-list stock-grade-list-scroll">
          {items.map((item, index) => (
            <small className={`stock-grade-row stock-grade-${stockGradeTone(item)}`} key={`grade-${item.date || index}`}>
              <span>{item.date || item.publishedDate || "Date N/A"}</span>
              <b>{stockGradeLabel(item)}</b>
              <em>{item.gradingCompany || item.analystCompany || item.firm || item.action || "Analyst grade"}</em>
              {stockGradePrice(item) ? <strong>{stockGradePrice(item)}</strong> : null}
            </small>
          ))}
        </div>
      ) : (
        <span>No stock grades returned.</span>
      )}
    </div>
  );
}

function DeepResearchContent({ payload }) {
  const research = payload.research || {};
  const deep = payload.deep_research || {};
  const [resourceModal, setResourceModal] = useState(null);
  const sourceMap = useMemo(() => sourceByKeyMap(deep.sources), [deep.sources]);
  const hasStructuredSections = Array.isArray(research.sections) && research.sections.length > 0;
  const earningsReports = Array.isArray(payload.market_data?.earnings_reports) ? payload.market_data.earnings_reports : [];
  const stockGrades = Array.isArray(deep.stock_grades) ? deep.stock_grades.slice(0, 10) : [];
  return (
    <>
      <div className="research-section-grid deep-research-grid">
        <ResearchSignal label="Deep research signal" value={research.signal} />
        <ResearchMarketSnapshot marketData={payload.market_data} showEarnings={false} />
        <DeepResearchArtifacts artifacts={deep.artifacts} />
        <DeepResearchDcfCalculator dcf={deep.dcf} />
        <DeepResearchDataLibrary
          deep={deep}
          earningsReports={earningsReports}
          nextEarningsDate={payload.market_data?.next_earnings_date}
          onOpenResource={setResourceModal}
          stockGrades={stockGrades}
        />
        {hasStructuredSections ? (
          <DeepResearchSections onOpenResource={setResourceModal} sections={research.sections} sourceMap={sourceMap} />
        ) : (
          <>
            <DeepResearchList title="Business overview" items={research.business_overview} />
            <DeepResearchList title="Products and segments" items={research.products_and_segments} />
            <DeepResearchList title="Financial analysis" items={research.financial_analysis} />
            <DeepResearchList title="Valuation" items={research.valuation} />
            <DeepResearchList title="Risks" items={research.risks} />
            <DeepResearchList title="Catalysts" items={research.catalysts} />
            <DeepResearchList title="Monitoring checklist" items={research.watch_items} />
          </>
        )}
      </div>
      <DeepResourceModal onClose={() => setResourceModal(null)} resource={resourceModal} />
    </>
  );
}

function ResearchResultContent({ payload }) {
  const research = payload.research || {};
  if (payload.mode === "deep_research") {
    return <DeepResearchContent payload={payload} />;
  }
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
  return String(value || "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replaceAll("_", " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
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
        <h2>Report schedule</h2>
      </div>
      <div className="schedule-controls">
        <div className="schedule-control-row">
          <ReportTimePicker value={settings.report_scheduled_at} onChange={(value) => onChange({ report_scheduled_at: value })} />
          <TimezoneCombobox
            options={timezones}
            value={settings.timezone}
            onChange={(value) => onChange({ timezone: value })}
          />
        </div>
        <ReportFrequencyTabs value={settings.report_frequency} onChange={(value) => onChange({ report_frequency: value })} />
      </div>
      {error ? <p className="error schedule-error">{error}</p> : null}
    </section>
  );
}

function ReportFrequencyTabs({ value, onChange }) {
  return (
    <div className="report-frequency-tabs" role="tablist" aria-label="Report frequency">
      {REPORT_FREQUENCIES.map(([option, label]) => (
        <button
          aria-selected={value === option}
          className={value === option ? "active" : ""}
          key={option}
          onClick={() => onChange(option)}
          role="tab"
          type="button"
        >
          {label}
        </button>
      ))}
    </div>
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

function CompanyContextModal({ item, onClose }) {
  const [payload, setPayload] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [memoryDetail, setMemoryDetail] = useState(null);
  const [memoryStatus, setMemoryStatus] = useState("idle");
  const [memoryError, setMemoryError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const loadContext = async () => {
      setStatus("loading");
      setError("");
      try {
        const response = await requestJson(`/api/stocks/${encodeURIComponent(item.stock_id)}/context`, { method: "GET" });
        if (!cancelled) {
          setPayload(response);
          setStatus("ready");
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unable to load company context.");
          setStatus("error");
        }
      }
    };
    loadContext();
    return () => {
      cancelled = true;
    };
  }, [item.stock_id]);

  const openMemory = async (memoryId) => {
    if (!memoryId) {
      return;
    }
    setMemoryStatus("loading");
    setMemoryError("");
    setMemoryDetail(null);
    try {
      const response = await requestJson(`/api/company-memory/${encodeURIComponent(memoryId)}`, { method: "GET" });
      setMemoryDetail(response.memory);
      setMemoryStatus("ready");
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "Unable to load tracked context.");
      setMemoryStatus("error");
    }
  };

  const stock = payload?.stock ?? item;
  const notesByReport = useMemo(() => {
    const groups = new Map();
    for (const note of payload?.notes ?? []) {
      if (!note.report_id) {
        continue;
      }
      const list = groups.get(note.report_id) ?? [];
      list.push(note);
      groups.set(note.report_id, list);
    }
    return groups;
  }, [payload?.notes]);
  const timelineReportIds = useMemo(
    () => new Set((payload?.report_items ?? []).map((reportItem) => reportItem.report_id)),
    [payload?.report_items],
  );
  const otherNotes = (payload?.notes ?? []).filter((note) => note.research_item_id || !note.report_id || !timelineReportIds.has(note.report_id));
  return (
    <div className="modal-backdrop report-preview-backdrop" onMouseDown={onClose}>
      <section className="modal-panel long-modal-panel company-context-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <div className="selected-stock no-margin">
            <img className="stock-logo large" {...stockLogoProps(stock.logo_url)} alt="" />
            <div>
              <p className="eyebrow">Company context</p>
              <h2>{stock.symbol}: {stock.company_name}</h2>
            </div>
          </div>
          <button className="icon-button" onClick={onClose} title="Close context" type="button">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {status === "loading" ? <p className="muted company-context-status">Loading company context...</p> : null}
        {status === "error" ? <p className="form-error company-context-status">{error}</p> : null}

        {status === "ready" && payload ? (
          <div className="company-context-content">
            <div className="company-memory-summary company-context-summary">
              <div>
                <span>Report mentions</span>
                <strong>{payload.summary.report_item_count}</strong>
              </div>
              <div>
                <span>Tracked themes</span>
                <strong>{payload.summary.memory_count}</strong>
              </div>
              <div>
                <span>Open notes</span>
                <strong>{payload.summary.unresolved_note_count}</strong>
              </div>
              <div>
                <span>Next earnings</span>
                <strong>{payload.next_earnings_date ? formatDateOnly(payload.next_earnings_date) : "N/A"}</strong>
              </div>
            </div>

            {stock.relationship === "portfolio" ? (
              <section className="research-card company-context-section">
                <div className="research-card-header">
                  <h3>Key things to monitor</h3>
                </div>
                {payload.monitor_items.length ? (
                  <ol className="company-monitor-list">
                    {payload.monitor_items.map((monitor, index) => (
                      <li className="company-monitor-item" key={`${monitor.text}-${index}`}>
                        <span className="research-list-index">{String(index + 1).padStart(2, "0")}</span>
                        <div>
                          <p>{monitor.text}</p>
                          <small>{monitor.count}x - last {formatDateOnly(monitor.last_seen_at)}</small>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="muted">Nothing specific to monitor yet. This will fill in as future reports mention the company.</p>
                )}
              </section>
            ) : null}

            {payload.memories.length ? (
              <section className="research-card company-context-section">
                <div className="research-card-header">
                  <h3>Tracked context</h3>
                </div>
                <div className="company-context-memory-list">
                  {payload.memories.map((memory) => (
                    <button className="company-context-memory" key={memory.id} onClick={() => openMemory(memory.id)} type="button">
                      <strong>{memory.theme}</strong>
                      <span>{memory.latest_development || memory.description}</span>
                      <small>{memory.evidence_count} developments - last {formatDateOnly(memory.last_seen_at)}</small>
                    </button>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="research-card company-context-section">
              <div className="research-card-header">
                <h3>Report timeline</h3>
              </div>
              {payload.report_items.length ? (
                <div className="company-context-timeline">
                  {payload.report_items.map((reportItem) => {
                    const reportNotes = notesByReport.get(reportItem.report_id) ?? [];
                    return (
                      <article className="company-context-report" key={reportItem.id}>
                        <div className="company-context-report-date">
                          <span>{formatDateOnly(reportItem.report_date)}</span>
                          {reportItem.attention_label ? <strong>{researchHumanLabel(reportItem.attention_label)}</strong> : null}
                        </div>
                        <div className="company-context-report-body">
                          <h4>{reportItem.headline || "Report item"}</h4>
                          {reportItem.why_it_matters ? <p>{reportItem.why_it_matters}</p> : null}
                          {reportItem.article_summary?.length ? (
                            <ul>
                              {reportItem.article_summary.map((point, index) => <li key={`${reportItem.id}-point-${index}`}>{point}</li>)}
                            </ul>
                          ) : null}
                          {reportItem.thesis_summary || reportItem.monitor_next || reportItem.thesis_points_affected?.length ? (
                            <details className="company-context-thesis-impact">
                              <summary><span>Thesis impact</span><span className="company-context-chevron" aria-hidden="true">&#8250;</span></summary>
                              <div className="company-context-thesis-impact-body">
                                {reportItem.thesis_summary ? <p>{reportItem.thesis_summary}</p> : null}
                                {reportItem.thesis_points_affected?.length ? (
                                  <p><strong>Affected thesis points:</strong> {reportItem.thesis_points_affected.join(", ")}</p>
                                ) : null}
                                {reportItem.monitor_next ? <p><strong>Monitor next:</strong> {reportItem.monitor_next}</p> : null}
                              </div>
                            </details>
                          ) : null}
                          <div className="company-context-report-links">
                            {reportItem.source_url ? <a className="company-context-source-link" href={reportItem.source_url} rel="noreferrer" target="_blank">Full article{reportItem.source ? ` - ${reportItem.source}` : ""}</a> : null}
                            {reportItem.company_memory_item_id ? (
                              <button className="company-context-action-button" onClick={() => openMemory(reportItem.company_memory_item_id)} type="button">Show context</button>
                            ) : null}
                            <a className="company-context-action-button company-context-open-report" href={`/reports/${encodeURIComponent(reportItem.report_id)}`} rel="noreferrer" target="_blank">Open report</a>
                          </div>
                          {reportNotes.length ? (
                            <div className="company-context-notes">
                              {reportNotes.map((note) => (
                                <div className={note.is_resolved ? "company-context-note resolved" : "company-context-note"} key={note.id}>
                                  <p>{note.body}</p>
                                  <div className="company-context-note-footer">
                                    <small>{formatDateTime(note.created_at)}</small>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <p className="muted">No report history for this company yet. This will fill in once the company appears in your reports.</p>
              )}
            </section>

            {otherNotes.length ? (
              <section className="research-card company-context-section">
                <div className="research-card-header">
                  <h3>Notes</h3>
                </div>
                <div className="company-context-notes standalone">
                  {otherNotes.map((note) => (
                    <div className={note.is_resolved ? "company-context-note resolved" : "company-context-note"} key={note.id}>
                      <p>{note.body}</p>
                      <div className="company-context-note-footer">
                        <small>
                          {note.research_item_id ? researchTypeLabel(note.research_type) : note.report_id ? `Report ${note.report_date || ""}` : "Standalone"}
                          {" - "}
                          {formatDateTime(note.created_at)}
                        </small>
                        {note.research_item_id ? (
                          <a className="company-context-action-button small" href={`/research/${encodeURIComponent(note.research_item_id)}`} rel="noreferrer" target="_blank">Open research</a>
                        ) : note.report_id ? (
                          <a className="company-context-action-button small" href={`/reports/${encodeURIComponent(note.report_id)}`} rel="noreferrer" target="_blank">Open report</a>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        ) : null}
      </section>
      {memoryStatus !== "idle" ? (
        <CompanyMemoryModal
          error={memoryError}
          memory={memoryDetail}
          onClose={() => {
            setMemoryStatus("idle");
            setMemoryDetail(null);
            setMemoryError("");
          }}
          onChanged={(nextMemory) => {
            setMemoryDetail(nextMemory);
            setPayload((current) => {
              if (!current?.memories?.length || !nextMemory?.id) {
                return current;
              }
              return {
                ...current,
                memories: current.memories.map((memoryItem) => (
                  memoryItem.id === nextMemory.id
                    ? {
                        ...memoryItem,
                        latest_development: nextMemory.latest_development,
                        thesis_points: nextMemory.thesis_points,
                        importance: nextMemory.importance,
                        status: nextMemory.status,
                        evidence_count: nextMemory.evidence_count,
                        first_seen_at: nextMemory.first_seen_at,
                        last_seen_at: nextMemory.last_seen_at,
                      }
                    : memoryItem
                )),
              };
            });
          }}
          status={memoryStatus}
        />
      ) : null}
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
  onOpenContext,
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
                  <td data-label="Company">
                    <div className="stock-cell">
                      <img className="stock-logo" {...stockLogoProps(item.logo_url)} alt="" />
                      <div>
                        <strong>{item.symbol}</strong>
                        <span>{item.company_name}</span>
                      </div>
                    </div>
                  </td>
                  <td data-label="Position">
                    {itemType === "portfolio" ? (
                      <PositionSlider
                        item={item}
                        onChange={onPositionChange}
                        onCommit={onPositionCommit}
                        portfolioTotal={portfolioTotal}
                      />
                    ) : null}
                  </td>
                  <td data-label="Thesis">
                    <span className="status-pill">{thesisPointCount(item, itemType)} points</span>
                  </td>
                  <td data-label="In report">
                    <ReportToggle checked={item.include_in_report !== false} onChange={(next) => onReportToggle(item, next)} />
                  </td>
                  <td className="actions-cell" data-label="Actions">
                    <button className="icon-button" onClick={() => onEdit(item)} title="Edit thesis" type="button">
                      <Pencil size={17} aria-hidden="true" />
                    </button>
                    <button className="icon-button" onClick={() => onOpenContext?.(item)} title="Company context" type="button">
                      <Timeline size={17} aria-hidden="true" />
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
      } catch {
        setError("Stock search is temporarily unavailable.");
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
      <section className="modal-panel long-modal-panel" aria-modal="true" onMouseDown={(event) => event.stopPropagation()} role="dialog">
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
