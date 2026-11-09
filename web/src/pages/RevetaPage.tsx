/**
 * Reveta's bounded ecosystem view. Hermes remains the chat/tool runtime.
 * This page never performs writes or treats model output as an approval.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import {
  ArrowUpRight, BookOpen, BrainCircuit, CheckCircle2, ExternalLink,
  GitBranch, RefreshCw, Search, ShieldCheck, Terminal, Workflow, XCircle,
} from "lucide-react";
import { fetchJSON } from "@/lib/api";

type SourceConnection = "observed" | "unknown";
type SystemRow = {
  id: string;
  name: string;
  repository: string;
  portfolio_status: string;
  connection: SourceConnection;
  revision: string | null;
  checked_at: string | null;
  deployment: "unknown";
  governance_gate: "not_evaluated";
};
type Overview = {
  schema_version: 1;
  mode: "read_only";
  registry_state: "configured" | "invalid_registry" | "not_configured";
  source_of_truth: string;
  brain: {
    state: "not_connected";
    authority: "advisory_only";
    hosted_ingestion: false;
    automatic_writeback: false;
  };
  systems: SystemRow[];
  action_policy: {
    default: string;
    production: string;
    external_actions: string;
  };
  limitations: string[];
};
type Section = "systems" | "brain" | "governance";

const sections: { id: Section; label: string; icon: typeof GitBranch }[] = [
  { id: "systems", label: "Ecosystem", icon: GitBranch },
  { id: "brain", label: "Aura Brain", icon: BrainCircuit },
  { id: "governance", label: "Governance", icon: ShieldCheck },
];

function Revision({ system }: { system: SystemRow }) {
  if (system.connection !== "observed" || !system.revision) {
    return <span className="text-text-secondary">Not verified</span>;
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-midground">
      <CheckCircle2 className="size-3.5" aria-hidden="true" />
      Revision observed: <code>{system.revision.slice(0, 7)}</code>
    </span>
  );
}

export default function RevetaPage() {
  const [section, setSection] = useState<Section>("systems");
  const [data, setData] = useState<Overview | null>(null);
  const [search, setSearch] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setRefreshing(true);
    setError(null);
    try {
      const url = signal ? "/api/reveta/overview" : "/api/reveta/overview?refresh=1";
      const response = await fetchJSON<Overview>(url, { signal });
      if (!signal?.aborted) {
        setData(response);
      }
    } catch {
      if (!signal?.aborted) {
        setError("The authenticated Reveta metadata adapter is unavailable. The Hermes frontend may still be running without its backend.");
        setData(null);
      }
    } finally {
      if (!signal?.aborted) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const systems = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data?.systems ?? []).filter(
      (system) => system.name.toLowerCase().includes(q) || system.repository.toLowerCase().includes(q),
    );
  }, [data?.systems, search]);

  const configured = data?.registry_state === "configured";
  const observed = data?.systems.filter((item) => item.connection === "observed").length ?? 0;

  return (
    <main className="mx-auto w-full max-w-5xl space-y-6 pb-8" aria-label="Reveta ecosystem control tower">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-current/20 pb-5">
        <div className="flex min-w-0 items-center gap-4">
          <img
            src="/brand/aura-mark.svg"
            alt=""
            className="h-14 w-14 shrink-0 object-contain motion-safe:transition-transform motion-safe:duration-300 hover:scale-105"
          />
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-text-secondary">Reveta ecosystem</p>
            <h1 className="text-2xl font-semibold leading-tight text-midground">Aura</h1>
            <p className="mt-1 max-w-xl text-sm text-text-secondary">
              One conversational work surface, with evidence and decisions governed at their sources.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
          className="inline-flex min-h-10 items-center gap-2 rounded-md border border-current/25 px-3 py-2 text-xs font-semibold text-midground transition-colors hover:bg-current/10 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 motion-reduce:transition-none"
          aria-label="Refresh Reveta source metadata"
        >
          <RefreshCw className={refreshing ? "size-4 animate-spin motion-reduce:animate-none" : "size-4"} aria-hidden="true" />
          {refreshing ? "Checking…" : "Refresh sources"}
        </button>
      </header>

      <div className="flex flex-wrap gap-2 text-xs" aria-live="polite">
        <span className="rounded-full border border-current/25 px-3 py-1.5 text-midground">
          <ShieldCheck className="mr-1.5 inline size-3.5" aria-hidden="true" /> Read-only
        </span>
        <span className="rounded-full border border-current/25 px-3 py-1.5 text-text-secondary">
          Registry: {configured ? "configured" : "not connected"}
        </span>
        <span className="rounded-full border border-current/25 px-3 py-1.5 text-text-secondary">
          {observed} repository revision{observed === 1 ? "" : "s"} observed
        </span>
        <span className="rounded-full border border-current/25 px-3 py-1.5 text-text-secondary">
          Deployment health: unknown
        </span>
      </div>

      {error && (
        <div role="alert" className="flex items-start gap-3 border-l-2 border-current/50 px-4 py-3 text-sm text-text-secondary">
          <XCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <div>
            <p>{error}</p>
            <p className="mt-1">No systems or approvals have been inferred from this failure.</p>
          </div>
        </div>
      )}

      <nav aria-label="Reveta workspace sections" className="flex gap-1 overflow-x-auto border-b border-current/20">
        {sections.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setSection(id)}
            aria-current={section === id ? "page" : undefined}
            className={[
              "inline-flex min-h-11 shrink-0 items-center gap-2 px-4 py-2 text-sm",
              "border-b-2 focus-visible:outline-2 focus-visible:outline-offset-[-2px]",
              "transition-colors duration-150 motion-reduce:transition-none",
              section === id
                ? "border-midground text-midground"
                : "border-transparent text-text-secondary hover:text-midground",
            ].join(" ")}
          >
            <Icon aria-hidden="true" className="size-4" /> {label}
          </button>
        ))}
      </nav>

      {section === "systems" && (
        <section aria-label="Registered systems" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-midground">Systems and source evidence</h2>
              <p className="text-sm text-text-secondary">Code revision checks are not deployment, quality or governance approvals.</p>
            </div>
            <label className="flex min-h-10 items-center gap-2 rounded-md border border-current/25 px-3 text-text-secondary">
              <Search className="size-4" aria-hidden="true" />
              <span className="sr-only">Search registered systems</span>
              <input
                className="w-44 max-w-[45vw] bg-transparent text-sm text-midground outline-none placeholder:text-text-secondary"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Find a system"
                type="search"
              />
            </label>
          </div>
          {!data && !error && refreshing && <p className="text-sm text-text-secondary" aria-live="polite">Loading source evidence…</p>}
          {!configured && !refreshing && (
            <div className="border-l-2 border-current/30 px-4 py-3">
              <p className="font-medium text-midground">No operator-approved registry connected</p>
              <p className="mt-1 text-sm text-text-secondary">
                Configure <code>$HERMES_HOME/reveta/registry.json</code> on the backend. Private Reveta OS documents are never bundled into this public repository.
              </p>
            </div>
          )}
          {configured && systems.length === 0 && (
            <p className="text-sm text-text-secondary">No matching registered systems.</p>
          )}
          <ul className="divide-y divide-current/15">
            {systems.map((system) => (
              <li key={system.id} className="group py-4 motion-safe:transition-colors hover:bg-current/5">
                <div className="flex flex-wrap items-start justify-between gap-3 px-2">
                  <div className="min-w-0 space-y-1">
                    <h3 className="font-semibold text-midground">{system.name}</h3>
                    <p className="break-all font-mono text-xs text-text-secondary">{system.repository}</p>
                    <p className="text-xs text-text-secondary">
                      Portfolio label: {system.portfolio_status} (operator-supplied, unverified)
                    </p>
                  </div>
                  <a
                    href={"https://github.com/" + system.repository}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex min-h-10 items-center gap-1 text-xs text-midground underline-offset-4 hover:underline focus-visible:outline-2"
                  >
                    Open source <ArrowUpRight className="size-4" aria-hidden="true" />
                    <span className="sr-only">for {system.name}</span>
                  </a>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-4 px-2 text-xs">
                  <Revision system={system} />
                  <span className="text-text-secondary">CI: unverified</span>
                  <span className="text-text-secondary">Deployment: unknown</span>
                  <span className="text-text-secondary">Release gate: not evaluated</span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {section === "brain" && (
        <section className="space-y-4" aria-label="Aura Brain status">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-midground">
            <BrainCircuit className="size-5" aria-hidden="true" /> Aura Brain
          </h2>
          <p className="max-w-2xl text-sm text-text-secondary">
            Context and retrieval must remain scoped to the authorised source, with provenance, correction and withdrawal. A model summary is not a decision record.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2 border-t border-current/25 pt-4">
              <h3 className="font-semibold text-midground">Built-in memory</h3>
              <p className="text-sm text-text-secondary">Managed by the Aura engine. Inspect its actual status in the existing memory and settings surfaces.</p>
              <Link to="/config" className="inline-flex items-center gap-1 text-sm text-midground underline-offset-4 hover:underline">
                Open configuration <ExternalLink className="size-3.5" aria-hidden="true" />
              </Link>
            </div>
            <div className="space-y-2 border-t border-current/25 pt-4">
              <h3 className="font-semibold text-midground">Aura / RIII / GBrain</h3>
              <p className="text-sm text-text-secondary">Not connected. No hosted ingestion, model training or automatic writeback has been activated.</p>
              <span className="inline-block rounded-full border border-current/25 px-2 py-1 text-xs text-text-secondary">Source-scoped integration required</span>
            </div>
          </div>
          <p className="text-sm text-text-secondary">Next interface: approve individual sources, test retrieval permissions, then show cited answers with explicit review receipts.</p>
        </section>
      )}

      {section === "governance" && (
        <section className="space-y-5" aria-label="Governance and action boundaries">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-midground">
            <ShieldCheck className="size-5" aria-hidden="true" /> Human-governed execution
          </h2>
          <p className="max-w-2xl text-sm text-text-secondary">
            Reveta OS owns policies and decisions. The portfolio tracker and product repositories retain their authority. This view is not an approval service.
          </p>
          <div className="grid gap-4 md:grid-cols-3">
            {[
              { title: "Discover", subtitle: "Read, investigate, draft", Icon: BookOpen },
              { title: "Prepare", subtitle: "Scoped branch, tests, PR", Icon: Workflow },
              { title: "Authorize", subtitle: "Founder review before external or production actions", Icon: ShieldCheck },
            ].map(({ title, subtitle, Icon }) => (
              <div key={title} className="border-t border-current/25 pt-4">
                <Icon className="mb-3 size-5 text-midground" aria-hidden="true" />
                <h3 className="font-semibold text-midground">{title}</h3>
                <p className="mt-1 text-sm text-text-secondary">{subtitle}</p>
              </div>
            ))}
          </div>
          <div className="border-l-2 border-current/30 px-4 py-3 text-sm text-text-secondary">
            Production deployment, publishing, spending, sending communications, migrations, deletion and access changes remain approval-gated. No tool-execution enforcement hook is installed yet; the current API provides read-only advisory metadata only.
          </div>
          <Link to="/chat" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-midground underline-offset-4 hover:underline">
            <Terminal className="size-4" aria-hidden="true" /> Return to Hermes chat
          </Link>
        </section>
      )}

      <footer className="border-t border-current/20 pt-4 text-xs text-text-secondary">
        <p>Reveta OS governs. The engine executes. Aura advises. No status is marked healthy without current evidence.</p>
        <p className="mt-1">Feature foundation · no automatic cross-product writes · no production changes.</p>
      </footer>
    </main>
  );
}
