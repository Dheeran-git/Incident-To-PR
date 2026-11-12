"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

type Incident = {
  id: string; service: string; summary: string; source: string; status: string; created_at: string;
  evidence: Array<Record<string, unknown>>; diagnosis?: Record<string, unknown> | null;
  decision?: Record<string, unknown> | null; proposal?: { summary?: string; rollback_plan?: string; patches?: Array<{path:string;content:string}>; repository?: string } | null;
  policy?: { allowed?: boolean; requires_approval?: boolean; reasons?: string[]; rule_version?: string } | null;
  review?: { decision?: string; reviewer?: string; comment?: string } | null;
  pull_request?: { number: number; url: string; state: string; merged?: boolean; repository: string } | null;
  verification?: Record<string, unknown> | null; failure?: string | null;
  events?: Array<{occurred_at:string; actor:string; event_type:string; details:Record<string,unknown>}>;
};
type Integrations = Record<string, {configured?:boolean; url?:string|null; application?:string; model?:string|null; mode?:string}>;
type Configuration = {code_repository:string;gitops_repository:string;github_token_configured:boolean;model_configured:boolean;namespace:string;monitoring:{enabled:boolean;auto_analyze:boolean}};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) }, cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload as T;
}

function nice(value?: string) { return (value || "unknown").replaceAll("_", " ").toLowerCase().replace(/\b\w/g, x => x.toUpperCase()); }
function shortId(value: string) { return value.slice(0, 8); }
function time(value?: string) { return value ? new Date(value).toLocaleString() : "Not recorded"; }

export default function Home() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [integrations, setIntegrations] = useState<Integrations>({});
  const [selected, setSelected] = useState<string>("");
  const [service, setService] = useState("shippingservice");
  const [summary, setSummary] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState<"incidents"|"setup">("incidents");
  const [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [codeRepositoryUrl, setCodeRepositoryUrl] = useState("");
  const [gitopsRepositoryUrl, setGitopsRepositoryUrl] = useState("");
  const [monitorEnabled, setMonitorEnabled] = useState(false);
  const [autoAnalyze, setAutoAnalyze] = useState(false);
  const repositoryFormInitialized = useRef(false);
  const monitorFormDirty = useRef(false);
  const active = useMemo(() => incidents.find(x => x.id === selected) || incidents[0], [incidents, selected]);

  const refresh = useCallback(async () => {
    try {
      const [rows, checks, config] = await Promise.all([api<Incident[]>("/api/v1/incidents"), api<Integrations>("/api/v1/integrations"), api<Configuration>("/api/v1/configuration")]);
      setIncidents(rows); setIntegrations(checks);
      setConfiguration(config);
      if (!monitorFormDirty.current) {
        setMonitorEnabled(config.monitoring.enabled); setAutoAnalyze(config.monitoring.auto_analyze);
      }
      if (!repositoryFormInitialized.current) {
        setCodeRepositoryUrl(config.code_repository ? `https://github.com/${config.code_repository}` : "");
        setGitopsRepositoryUrl(config.gitops_repository ? `https://github.com/${config.gitops_repository}` : "");
        repositoryFormInitialized.current = true;
      }
      setSelected(current => current || rows[0]?.id || "");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not connect to API"); }
  }, []);

  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 8000); return () => window.clearInterval(timer); }, [refresh]);

  async function act(label: string, operation: () => Promise<unknown>) {
    setBusy(true); setError(""); setNotice("");
    try { await operation(); await refresh(); setNotice(label); }
    catch (e) { setError(e instanceof Error ? e.message : "Action failed"); }
    finally { setBusy(false); }
  }

  async function createIncident(event: FormEvent) {
    event.preventDefault();
    if (!summary.trim()) { setError("Describe the observed service problem first."); return; }
    await act("Incident created.", async () => {
      const created = await api<Incident>("/api/v1/incidents", { method: "POST", body: JSON.stringify({ service, summary, source: "manual" }) });
      setSelected(created.id); setSummary("");
    });
  }

  async function saveRepositories(event: FormEvent) {
    event.preventDefault();
    await act("Repository links saved. Check the connection status for GitHub access.", () => api("/api/v1/configuration/repositories", {method:"PUT",body:JSON.stringify({code_repository_url:codeRepositoryUrl,gitops_repository_url:gitopsRepositoryUrl})}));
  }

  async function saveMonitoring(event: FormEvent) {
    event.preventDefault();
    await act(monitorEnabled ? (autoAnalyze ? "Automatic detection and analysis enabled." : "Automatic detection enabled; analysis remains manual.") : "Automatic monitoring stopped.", async () => {
      await api("/api/v1/configuration/monitoring", {method:"PUT",body:JSON.stringify({enabled:monitorEnabled,auto_analyze:autoAnalyze})});
      monitorFormDirty.current = false;
    });
  }

  const action = String(active?.decision?.action || "");
  const statusSteps = ["open", "analyzing", "awaiting_review", "ready_for_pr", "pr_open", "merged_waiting_verification", "verified"];
  const currentStep = Math.max(0, statusSteps.indexOf(active?.status || "open"));

  return <main className="shell">
    <header className="topbar">
      <a className="brand" href="#"><span className="brand-mark">IP</span><span><b>Incident-to-PR</b><small>Incident control room</small></span></a>
      <div className="top-actions"><span className="env-pill"><i /> Local lab</span><button className="icon-button" onClick={() => void refresh()} title="Refresh data" aria-label="Refresh data">↻</button></div>
    </header>

    <section className="hero">
      <div><div className="eyebrow">POLICY-GOVERNED REMEDIATION</div><h1>Incident control room</h1><p>Investigate service health, review evidence-backed proposals, and track recovery through GitOps.</p></div>
      <div className="hero-state"><span className="pulse"/><span>Connected to control plane</span></div>
    </section>

    <nav className="tabs" aria-label="Main navigation">
      <button className={tab === "incidents" ? "tab active" : "tab"} onClick={() => setTab("incidents")}>Incidents <span>{incidents.length}</span></button>
      <button className={tab === "setup" ? "tab active" : "tab"} onClick={() => setTab("setup")}>Connections & policy</button>
    </nav>

    {error && <div className="alert error"><b>Action stopped</b><span>{error}</span><button onClick={() => setError("")}>Dismiss</button></div>}
    {notice && <div className="alert success"><b>Updated</b><span>{notice}</span><button onClick={() => setNotice("")}>Dismiss</button></div>}

    {tab === "setup" ? <section className="setup-grid">
      <article className="panel"><div className="panel-head"><div><div className="eyebrow">REPOSITORY ONBOARDING</div><h2>Connect your code and GitOps repos</h2></div></div>
        <p className="muted">Paste GitHub repository links. The server uses its configured token; credentials are never sent from this form. Code and deployment manifests can live in the same repository.</p>
        <form className="repo-form" onSubmit={saveRepositories}>
          <label>Application code repository<input type="url" required value={codeRepositoryUrl} onChange={e => setCodeRepositoryUrl(e.target.value)} placeholder="https://github.com/your-team/your-service" /></label>
          <label>GitOps repository (optional; defaults to code repo)<input type="url" value={gitopsRepositoryUrl} onChange={e => setGitopsRepositoryUrl(e.target.value)} placeholder="https://github.com/your-team/your-service-gitops" /></label>
          <button className="button primary" disabled={busy}>{busy ? "Saving…" : "Save repository links"}<span>→</span></button>
        </form>
        <div className="notice-box">GitHub token: {configuration?.github_token_configured ? "configured on the server" : "not configured — add GITHUB_TOKEN to .env and restart the API"}. Model: {configuration?.model_configured ? "ready" : "not configured — add LLM_API_KEY to .env"}.</div>
      </article>
      <article className="panel"><div className="panel-head"><div><div className="eyebrow">AUTOMATIC DETECTION</div><h2>Monitor the connected runtime</h2></div><span className={monitorEnabled ? "status-chip good" : "status-chip neutral"}><i/>{monitorEnabled ? "Monitoring" : "Stopped"}</span></div>
        <p className="muted">Checks Prometheus for unavailable replicas, CrashLoopBackOff, and repeated container restarts in namespace <b>{configuration?.namespace || "online-boutique"}</b> every 30 seconds. Two consecutive unhealthy readings create one incident; recovery is recorded in its timeline. Application-level errors require matching metrics or alerts.</p>
        <form className="monitor-form" onSubmit={saveMonitoring}>
          <label className="toggle-row"><input type="checkbox" checked={monitorEnabled} onChange={e => {monitorFormDirty.current = true; setMonitorEnabled(e.target.checked);}} /><span><b>Enable automatic monitoring</b><small>Creates and deduplicates incidents from sustained runtime health signals.</small></span></label>
          <label className="toggle-row"><input type="checkbox" checked={autoAnalyze} disabled={!configuration?.model_configured} onChange={e => {monitorFormDirty.current = true; setAutoAnalyze(e.target.checked);}} /><span><b>Automatically analyze detected incidents</b><small>Requires a model key. Repository context and GitHub access are additionally needed for a patch; human approval is always required before a PR.</small></span></label>
          <button className="button primary" disabled={busy}>{busy ? "Saving…" : "Apply monitoring settings"}</button>
        </form>
        <div className="notice-box">Post-merge Argo CD sync also requires the GitOps repository configured in the local .env and the Argo application installed by the lab operator.</div>
      </article>
      <article className="panel"><div className="panel-head"><div><div className="eyebrow">INTEGRATIONS</div><h2>Connection status</h2></div><button className="button secondary small" onClick={() => void refresh()}>Refresh</button></div>
        <p className="muted">Telemetry endpoints and provider secrets are configured by the operator. Repository links are saved locally by the form above; secrets are never entered in this browser.</p>
        <div className="integration-list">{Object.entries(integrations).map(([name, item]) => <div className="integration-row" key={name}><div className="integration-icon">{name.slice(0,1).toUpperCase()}</div><div className="integration-main"><b>{nice(name)}</b><small>{item.url || item.application || item.model || item.mode || (item.configured ? "Configured" : "Not configured")}</small></div><span className={item.configured ? "status-chip good" : "status-chip neutral"}><i/>{item.configured ? "Connected" : "Not connected"}</span></div>)}</div>
      </article>
      <article className="panel policy-panel"><div className="eyebrow">SAFETY BY DEFAULT</div><h2>What this app can do</h2><ul className="policy-list"><li><span className="check">✓</span><span><b>Read telemetry</b><small>Kubernetes, Prometheus, and Loki are read-only evidence sources.</small></span></li><li><span className="check">✓</span><span><b>Propose a change</b><small>The policy gate checks the actual patch and allowed paths.</small></span></li><li><span className="check">✓</span><span><b>Open a pull request</b><small>The bot cannot merge. GitHub review and required CI checks control deployment.</small></span></li><li><span className="lock">⌑</span><span><b>No direct cluster writes</b><small>ArgoCD applies only from the protected GitOps branch.</small></span></li></ul><div className="notice-box">This prototype fails closed when a required integration, model, policy check, or verifier is unavailable.</div></article>
    </section> : <section className="workspace">
      <aside className="left-column">
        <article className="panel new-incident"><div className="panel-head"><div><div className="eyebrow">START AN INVESTIGATION</div><h2>Report an incident</h2></div><span className="manual-tag">Manual</span></div>
          <form onSubmit={createIncident}>
            <label>Service name<input value={service} onChange={e => setService(e.target.value)} maxLength={200} required /></label>
            <label>What are you seeing?<textarea value={summary} onChange={e => setSummary(e.target.value)} placeholder="Example: checkout requests are timing out after the latest deployment." maxLength={2000} rows={4} required /></label>
            <button className="button primary full" disabled={busy}>{busy ? "Working…" : "Create incident"}<span>→</span></button>
          </form>
          <p className="fineprint">Alertmanager incidents can also be sent to the configured webhook.</p>
        </article>

        <article className="panel incident-list-panel"><div className="panel-head"><div><div className="eyebrow">WORK QUEUE</div><h2>Recent incidents</h2></div><span className="count-pill">{incidents.length}</span></div>
          {incidents.length === 0 ? <div className="empty small-empty"><div className="empty-icon">↗</div><b>No incidents yet</b><span>Report a service problem to begin an investigation.</span></div> : <div className="incident-list">{incidents.map(item => <button key={item.id} onClick={() => setSelected(item.id)} className={active?.id === item.id ? "incident-item selected" : "incident-item"}><div className="incident-item-top"><span className={`dot ${item.status === "verified" ? "dot-green" : item.status === "failed" || item.status === "policy_denied" ? "dot-red" : "dot-blue"}`}/><span>{nice(item.status)}</span><time>{new Date(item.created_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}</time></div><b>{item.service}</b><span className="incident-summary">{item.summary}</span><small>#{shortId(item.id)}</small></button>)}</div>}
        </article>
      </aside>

      <section className="right-column">
        {!active ? <article className="panel empty-detail"><div className="empty-icon">⌁</div><h2>Your incident workspace</h2><p>Create an incident to see telemetry evidence, diagnosis, policy checks, pull request review, and recovery status.</p></article> : <>
          <article className="panel detail-panel">
            <div className="detail-title"><div><div className="eyebrow">INCIDENT #{shortId(active.id)} <span className="separator">/</span> {active.source.toUpperCase()}</div><h2>{active.service}</h2><p>{active.summary}</p></div><span className={`status-chip ${active.status === "verified" ? "good" : active.status.includes("denied") || active.status === "failed" ? "bad" : "neutral"}`}><i/>{nice(active.status)}</span></div>
            <div className="stepper">{["Detect", "Diagnose", "Review", "Pull request", "Verify"].map((step, index) => <div className={`step ${index <= currentStep ? "done" : ""} ${index === currentStep ? "current" : ""}`} key={step}><span>{index < currentStep ? "✓" : index + 1}</span><small>{step}</small></div>)}</div>
            {active.failure && <div className="notice-box warning">{active.failure}</div>}
            <div className="actions-row">
              {active.status === "open" || active.status === "failed" ? <button className="button primary" disabled={busy || !integrations.model?.configured} onClick={() => void act("Analysis finished. Review the evidence and policy result.", () => api(`/api/v1/incidents/${active.id}/analyze`, {method:"POST"}))}>{busy ? "Analyzing…" : "Analyze incident"}<span>✦</span></button> : null}
              {active.status === "awaiting_review" && <><input className="reviewer-input" value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="Your name" aria-label="Reviewer name"/><input className="reviewer-input comment-input" value={comment} onChange={e => setComment(e.target.value)} placeholder="Review note (optional)" aria-label="Review note"/><button className="button primary" disabled={busy || !reviewer.trim()} onClick={() => void act("Approved for pull request creation.", () => api(`/api/v1/incidents/${active.id}/review`, {method:"POST",body:JSON.stringify({decision:"approve_pr",reviewer,comment})}))}>Approve proposal</button><button className="button danger" disabled={busy || !reviewer.trim()} onClick={() => void act("Proposal rejected.", () => api(`/api/v1/incidents/${active.id}/review`, {method:"POST",body:JSON.stringify({decision:"reject",reviewer,comment})}))}>Reject</button></>}
              {active.status === "ready_for_pr" && <button className="button primary" disabled={busy} onClick={() => void act("Pull request created. Merge and deployment remain governed by GitHub and ArgoCD.", () => api(`/api/v1/incidents/${active.id}/open-pr`, {method:"POST"}))}>Open pull request <span>↗</span></button>}
              {active.pull_request && active.status !== "verified" && <><a className="button secondary" href={active.pull_request.url} target="_blank" rel="noreferrer">Open PR #{active.pull_request.number} ↗</a><button className="button secondary" disabled={busy} onClick={() => void act("Pull request and deployment status refreshed.", () => api(`/api/v1/incidents/${active.id}/refresh`, {method:"POST"}))}>Refresh status</button>{active.pull_request.merged && <button className="button secondary" disabled={busy} onClick={() => void act("Verification checked.", () => api(`/api/v1/incidents/${active.id}/verify`, {method:"POST"}))}>Check recovery</button>}</>}
            </div>
          </article>

          <div className="detail-grid">
            <article className="panel"><div className="panel-head"><div><div className="eyebrow">EVIDENCE</div><h2>What the system observed</h2></div><span className="count-pill">{active.evidence?.length || 0}</span></div>
              {!active.evidence?.length ? <p className="muted">Run analysis to gather read-only evidence from configured sources.</p> : <div className="evidence-list">{active.evidence.map((item, index) => <details className="evidence-item" key={String(item.id || index)}><summary><span className="source-icon">{String(item.source || "?").slice(0,1).toUpperCase()}</span><span><b>{nice(String(item.source || "evidence"))}</b><small>{String(item.id || "")}</small></span><span className={item.error ? "evidence-state warn" : item.configured ? "evidence-state good" : "evidence-state neutral"}>{item.error ? "Unavailable" : item.configured ? "Collected" : "Not configured"}</span></summary><pre>{JSON.stringify(item, null, 2)}</pre></details>)}</div>}
            </article>

            <article className="panel"><div className="panel-head"><div><div className="eyebrow">DIAGNOSIS & DECISION</div><h2>Agent assessment</h2></div>{active.decision?.action && <span className="action-tag">{nice(String(active.decision.action))}</span>}</div>
              {!active.diagnosis ? <p className="muted">No diagnosis yet. The agent must cite collected evidence to support its conclusion.</p> : <><div className="assessment"><small>Likely cause</small><p>{String(active.diagnosis.root_cause || "Not provided")}</p><div className="confidence-row"><span>Fault class <b>{nice(String(active.diagnosis.fault_class || "unknown"))}</b></span><span>Model confidence <b>{Math.round(Number(active.diagnosis.confidence || 0) * 100)}%</b></span></div></div><div className="assessment"><small>Decision rationale</small><p>{String(active.decision?.rationale || "No rationale provided")}</p><small>Evidence IDs: {Array.isArray(active.diagnosis.evidence_ids) ? active.diagnosis.evidence_ids.join(", ") : "None"}</small></div></>}
              {active.policy && <div className={active.policy.allowed ? "policy-result allowed" : "policy-result denied"}><b>{active.policy.allowed ? "Policy allowed proposal" : "Policy blocked proposal"}</b><small>Ruleset {active.policy.rule_version || "phase1-v1"}</small>{active.policy.reasons?.map((reason, i) => <span key={i}>{reason}</span>)}</div>}
            </article>

            {active.proposal && <article className="panel proposal-panel"><div className="panel-head"><div><div className="eyebrow">PROPOSED CHANGE</div><h2>Review the patch</h2></div><span className="status-chip neutral"><i/>PR only</span></div><p>{active.proposal.summary || "Review the proposed repository changes."}</p><p className="muted">Repository: {active.proposal.repository || "Not configured"}</p>{active.proposal.rollback_plan && <div className="rollback"><b>Rollback plan</b><span>{active.proposal.rollback_plan}</span></div>}{active.proposal.patches?.map(patch => <details className="patch-file" key={patch.path}><summary>{patch.path}</summary><pre>{patch.content}</pre></details>)}</article>}

            {active.verification && <article className="panel verification-panel"><div className="eyebrow">POST-MERGE VERIFICATION</div><h2>Deployment status</h2><pre>{JSON.stringify(active.verification, null, 2)}</pre><p className="fineprint">Verification remains pending unless ArgoCD reports Synced and Healthy and the configured Prometheus health query passes.</p></article>}

            <article className="panel timeline-panel"><div className="panel-head"><div><div className="eyebrow">AUDIT TRAIL</div><h2>Incident timeline</h2></div></div>{!active.events?.length ? <p className="muted">Events appear here as the incident moves through the workflow.</p> : <div className="timeline">{active.events.map((event, index) => <div className="timeline-event" key={`${event.occurred_at}-${index}`}><span className="timeline-dot"/><div><b>{nice(event.event_type)}</b><small>{event.actor} · {time(event.occurred_at)}</small></div></div>)}</div>}</article>
          </div>
        </>}
      </section>
    </section>}

    <footer><span>Incident-to-PR · Phase I research prototype</span><span>Agents propose. Policy decides. GitOps applies.</span></footer>
  </main>;
}
