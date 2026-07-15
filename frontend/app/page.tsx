"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  createProductLine,
  listLeads,
  listProductLines,
  startDiscovery,
  type Lead,
  type ProductLine,
} from "../lib/api";
import { clearSession, readSession, type Session } from "../lib/auth";

const metrics = [
  { label: "New leads", value: "36", note: "API-backed discovery ready", tone: "blue" },
  { label: "Priority leads", value: "18", note: "Evidence gate enabled", tone: "cyan" },
  { label: "Drafts to review", value: "8", note: "Email approval stays human-led", tone: "orange" },
  { label: "Positive replies", value: "6", note: "Reply loop coming next", tone: "green" },
];

const navItems = ["Overview", "Customer Agent", "CRM", "Email review", "Inbox", "Knowledge base"];

const bucketLabel = {
  priority_recommendation: "Priority",
  needs_enrichment: "Needs enrichment",
  not_qualified: "Not qualified",
} as const;

function parseCsv(value: FormDataEntryValue | null) {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function scoreClass(score: number) {
  if (score >= 90) return "score scoreHigh";
  if (score >= 70) return "score scoreMedium";
  return "score scoreLow";
}

function bucketClass(bucket: Lead["bucket"]) {
  if (bucket === "priority_recommendation") return "status statusPriority";
  if (bucket === "needs_enrichment") return "status statusResearch";
  return "status statusQualified";
}

function MetricTile({ label, value, note, tone }: (typeof metrics)[number]) {
  return (
    <article className="metricTile">
      <span className={`metricRail ${tone}`} aria-hidden="true" />
      <p>{label}</p>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}

function ProductLineSetup({
  productLines,
  loading,
  creating,
  onCreate,
}: {
  productLines: ProductLine[];
  loading: boolean;
  creating: boolean;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <section className="productPanel" aria-labelledby="product-lines-title">
      <div className="sectionHeader">
        <div>
          <p className="sectionLabel">Product intelligence</p>
          <h2 id="product-lines-title">Product lines</h2>
        </div>
        <span className="countBadge">{loading ? "Loading" : `${productLines.length} configured`}</span>
      </div>
      <div className="productContent">
        <form className="productForm" onSubmit={onCreate}>
          <label>
            Product line name
            <input name="name" required placeholder="Industrial LED lighting" />
          </label>
          <label>
            Product keywords
            <input name="keywords" required placeholder="LED floodlight, warehouse lighting" />
          </label>
          <label>
            Buyer profiles
            <input name="buyer_profiles" required placeholder="Distributor, Project buyer" />
          </label>
          <label>
            Target regions
            <input name="target_regions" required placeholder="Europe, North America" />
          </label>
          <label className="wideField">
            Description
            <input name="description" placeholder="Commercial and industrial retrofit lighting" />
          </label>
          <button className="primaryButton" type="submit" disabled={creating}>
            {creating ? "Creating..." : "Create product line"}
          </button>
        </form>
        <div className="productList" aria-label="Configured product lines">
          {productLines.length === 0 ? (
            <div className="emptyState">Create the first product line before starting discovery.</div>
          ) : (
            productLines.map((productLine) => (
              <article className="productItem" key={productLine.id}>
                <strong>{productLine.name}</strong>
                <span>{productLine.product_keywords.join(", ") || "No keywords"}</span>
                <small>
                  {productLine.buyer_profiles.join(", ") || "No buyer profiles"} /{" "}
                  {productLine.target_regions.join(", ") || "No target regions"}
                </small>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

function CustomerAgent({
  productLines,
  selectedProductLineId,
  targetMarket,
  buyerProfile,
  running,
  runMessage,
  onProductLineChange,
  onTargetMarketChange,
  onBuyerProfileChange,
  onRun,
}: {
  productLines: ProductLine[];
  selectedProductLineId: string;
  targetMarket: string;
  buyerProfile: string;
  running: boolean;
  runMessage: string;
  onProductLineChange: (value: string) => void;
  onTargetMarketChange: (value: string) => void;
  onBuyerProfileChange: (value: string) => void;
  onRun: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const selectedProductLine = productLines.find((item) => item.id === selectedProductLineId);
  const buyerProfiles = selectedProductLine?.buyer_profiles ?? [];

  return (
    <section className="agentPanel" aria-labelledby="customer-agent-title">
      <div className="agentIntro">
        <p className="sectionLabel">Agent 01</p>
        <h2 id="customer-agent-title">Customer Agent</h2>
        <p>Search, verify, score and prepare a focused set of companies for sales outreach.</p>
        <div className="agentChecks" aria-label="Discovery checks">
          <span>Website verified</span><span>Business evidence</span><span>Contact attempt</span>
        </div>
      </div>
      <form className="agentForm" onSubmit={onRun}>
        <label>
          Product line
          <select
            aria-label="Discovery product line"
            name="product_line_id"
            required
            value={selectedProductLineId}
            onChange={(event) => onProductLineChange(event.target.value)}
          >
            <option value="">Select product line</option>
            {productLines.map((productLine) => (
              <option key={productLine.id} value={productLine.id}>{productLine.name}</option>
            ))}
          </select>
        </label>
        <label>
          Target market
          <input
            aria-label="Discovery target market"
            name="target_market"
            required
            value={targetMarket}
            onChange={(event) => onTargetMarketChange(event.target.value)}
          />
        </label>
        <label>
          Buyer profile
          <select
            aria-label="Discovery buyer profile"
            name="buyer_profile"
            value={buyerProfile}
            onChange={(event) => onBuyerProfileChange(event.target.value)}
          >
            <option value="">Any buyer profile</option>
            {buyerProfiles.map((profile) => (
              <option key={profile} value={profile}>{profile}</option>
            ))}
          </select>
        </label>
        <button className="primaryButton" type="submit" disabled={running || !selectedProductLineId}>
          {running ? "Building lead list..." : "Start discovery"}
        </button>
        <div className={`runStatus ${runMessage.includes("complete") ? "runComplete" : ""}`} aria-live="polite">
          <span className="statusDot" aria-hidden="true" />
          {runMessage}
        </div>
      </form>
    </section>
  );
}

function LeadTable({ leads, priorityOnly, onPriorityToggle }: { leads: Lead[]; priorityOnly: boolean; onPriorityToggle: () => void }) {
  const displayedLeads = priorityOnly
    ? leads.filter((lead) => lead.bucket === "priority_recommendation")
    : leads;

  return (
    <section className="dataSection" aria-labelledby="lead-results-title">
      <div className="sectionHeader">
        <div>
          <p className="sectionLabel">Customer Agent output</p>
          <h2 id="lead-results-title">Discovered companies</h2>
        </div>
        <div className="tableActions">
          <button className="textButton" type="button" onClick={onPriorityToggle}>
            {priorityOnly ? "Show all leads" : "Show priority leads"}
          </button>
          <button className="outlineButton" type="button" disabled>Save to CRM</button>
        </div>
      </div>
      <div className="tableWrap">
        {leads.length === 0 ? (
          <div className="emptyState tableEmpty">Run discovery to populate evidence-backed leads.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Market / profile</th>
                <th scope="col">Evidence</th>
                <th scope="col">Reasons</th>
                <th scope="col">Score</th>
                <th scope="col">Bucket</th>
              </tr>
            </thead>
            <tbody>
              {displayedLeads.map((lead) => (
                <tr key={lead.id}>
                  <td><strong>{lead.company_name}</strong><span>{lead.website}</span></td>
                  <td><strong className="contactName">{lead.target_market}</strong><span>{lead.buyer_profile ?? "Any profile"}</span></td>
                  <td className="evidence">
                    {lead.evidence.length > 0 ? lead.evidence[0].source_excerpt : "No source excerpt recorded"}
                  </td>
                  <td className="evidence">
                    {lead.reasons.join("; ") || lead.missing_signals.join("; ") || "No scoring details"}
                  </td>
                  <td><span className={scoreClass(lead.score)}>{lead.score}</span></td>
                  <td><span className={bucketClass(lead.bucket)}>{bucketLabel[lead.bucket]}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

function ReviewQueue({ onOpen }: { onOpen: () => void }) {
  return (
    <section className="reviewPanel" aria-labelledby="review-title">
      <div className="sectionHeader compact">
        <div>
          <p className="sectionLabel">Human approval</p>
          <h2 id="review-title">Outbound review</h2>
        </div>
        <button className="textButton" type="button" onClick={onOpen}>Review 8 drafts</button>
      </div>
      <div className="reviewItem">
        <div className="avatar blueAvatar">LW</div>
        <div><strong>LumenHaus GmbH</strong><span>Personalized in German</span></div>
        <span className="qualityMark">96</span>
      </div>
      <div className="reviewItem">
        <div className="avatar cyanAvatar">RI</div>
        <div><strong>Rheinland Industriebedarf</strong><span>Product evidence cited</span></div>
        <span className="qualityMark">93</span>
      </div>
      <div className="reviewFooter"><span>Quality gate enabled</span><strong>8 drafts ready</strong></div>
    </section>
  );
}

function FollowUpTimeline() {
  return (
    <section className="timelinePanel" aria-labelledby="followup-title">
      <div className="sectionHeader compact">
        <div>
          <p className="sectionLabel">Sales execution</p>
          <h2 id="followup-title">Follow-up control</h2>
        </div>
        <button className="iconTextButton" type="button">View CRM</button>
      </div>
      <ol className="timeline">
        <li><time>09:30</time><span className="timelineDot blueDot" /><div><strong>Reply needs review</strong><p>HelioTech AG asked for the 2026 catalog.</p></div></li>
        <li><time>11:00</time><span className="timelineDot cyanDot" /><div><strong>Send approved introduction</strong><p>LumenHaus GmbH / owner: Mia Chen</p></div></li>
        <li><time>Tomorrow</time><span className="timelineDot orangeDot" /><div><strong>Follow up on quotation</strong><p>Rheinland Industriebedarf / no reply in 4 days</p></div></li>
      </ol>
    </section>
  );
}

function ReviewDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;

  return (
    <div className="drawerBackdrop" role="presentation" onMouseDown={onClose}>
      <aside className="reviewDrawer" aria-label="Email review queue" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawerHeader">
          <div><p className="sectionLabel">Email Agent</p><h2>Email review queue</h2></div>
          <button className="closeButton" type="button" aria-label="Close review queue" onClick={onClose}>x</button>
        </div>
        <p className="drawerCopy">Every draft passed language, product evidence, personalization and call-to-action checks before review.</p>
        <article className="draftCard">
          <span className="status statusPriority">Priority lead</span>
          <h3>Lighting solutions for commercial retrofit projects</h3>
          <p>To: Anna Weber / LumenHaus GmbH</p>
          <div className="draftEvidence"><span>Product catalog cited</span><span>Project evidence cited</span></div>
          <div className="drawerActions"><button className="outlineButton" type="button">Edit draft</button><button className="primaryButton" type="button">Approve to send</button></div>
        </article>
        <button className="queueNext" type="button">Next draft <span>2 of 8</span></button>
      </aside>
    </div>
  );
}

export default function HomePage() {
  const [activeNav, setActiveNav] = useState("Overview");
  const [session, setSession] = useState<Session | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [loadingProductLines, setLoadingProductLines] = useState(false);
  const [creatingProductLine, setCreatingProductLine] = useState(false);
  const [productLines, setProductLines] = useState<ProductLine[]>([]);
  const [selectedProductLineId, setSelectedProductLineId] = useState("");
  const [targetMarket, setTargetMarket] = useState("Germany");
  const [buyerProfile, setBuyerProfile] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [running, setRunning] = useState(false);
  const [runMessage, setRunMessage] = useState("Create or select a product line to start discovery");
  const [priorityOnly, setPriorityOnly] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [error, setError] = useState("");

  const selectedProductLine = useMemo(
    () => productLines.find((productLine) => productLine.id === selectedProductLineId),
    [productLines, selectedProductLineId]
  );

  useEffect(() => {
    const currentSession = readSession();
    if (!currentSession) {
      window.location.assign("/login");
      return;
    }
    setSession(currentSession);
    setCheckingSession(false);
    setLoadingProductLines(true);
    listProductLines(currentSession)
      .then((items) => {
        setProductLines(items);
        if (items.length > 0) {
          setSelectedProductLineId(items[0].id);
          setBuyerProfile(items[0].buyer_profiles[0] ?? "");
          setRunMessage("Ready for a targeted discovery run");
        }
      })
      .catch((caught: unknown) => handleApiFailure(caught, "Could not load product lines"))
      .finally(() => setLoadingProductLines(false));
  }, []);

  function handleApiFailure(caught: unknown, fallback: string) {
    if (caught instanceof ApiError && caught.status === 401) {
      clearSession();
      window.location.assign("/login");
      return;
    }
    setError(caught instanceof Error ? caught.message : fallback);
  }

  function logout() {
    clearSession();
    window.location.assign("/login");
  }

  function selectProductLine(productLineId: string) {
    setSelectedProductLineId(productLineId);
    const productLine = productLines.find((item) => item.id === productLineId);
    setBuyerProfile(productLine?.buyer_profiles[0] ?? "");
  }

  async function createProductLineFromForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setCreatingProductLine(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const created = await createProductLine(session, {
        name: String(form.get("name") ?? "").trim(),
        description: String(form.get("description") ?? "").trim(),
        product_keywords: parseCsv(form.get("keywords")),
        buyer_profiles: parseCsv(form.get("buyer_profiles")),
        target_regions: parseCsv(form.get("target_regions")),
      });
      setProductLines((current) => [...current, created]);
      setSelectedProductLineId(created.id);
      setBuyerProfile(created.buyer_profiles[0] ?? "");
      setRunMessage("Ready for a targeted discovery run");
      event.currentTarget.reset();
    } catch (caught) {
      handleApiFailure(caught, "Could not create product line");
    } finally {
      setCreatingProductLine(false);
    }
  }

  async function runDiscovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedProductLineId) return;
    setRunning(true);
    setError("");
    setRunMessage("Discovery running");
    try {
      const run = await startDiscovery(session, {
        product_line_id: selectedProductLineId,
        target_market: targetMarket.trim(),
        buyer_profile: buyerProfile || undefined,
        limit: 20,
      });
      const nextLeads = await listLeads(session, run.workflow_run_id);
      setLeads(nextLeads);
      setRunMessage(`Discovery complete / ${run.lead_count} companies screened / ${run.query}`);
    } catch (caught) {
      handleApiFailure(caught, "Customer discovery failed");
      setRunMessage("Discovery failed");
    } finally {
      setRunning(false);
    }
  }

  if (checkingSession || !session) {
    return (
      <main className="authCheck">
        <span className="statusDot" aria-hidden="true" />
        Loading workspace...
      </main>
    );
  }

  return (
    <main className="appShell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="Trade Axis home"><span>TA</span><strong>TRADE<br />AXIS</strong></a>
        <nav aria-label="Primary navigation">
          {navItems.map((item) => (
            <button className={activeNav === item ? "navItem active" : "navItem"} key={item} type="button" onClick={() => setActiveNav(item)}>
              <span className="navMarker" aria-hidden="true" />{item}
            </button>
          ))}
        </nav>
        <div className="sidebarFooter"><span className="connectionDot" />System operational<span className="tenant">{session.organization_role ?? "MEMBER"}</span></div>
      </aside>
      <section className="workspace" id="top">
        <header className="topbar">
          <div className="crumbs"><span>Sales workspace</span><strong>{activeNav}</strong></div>
          <div className="topbarActions"><button className="utilityButton" type="button">EN</button><button className="utilityButton logoutButton" type="button" onClick={logout}>Logout</button><button className="profileButton" type="button" aria-label="Open Mia Chen profile">MC</button></div>
        </header>
        <div className="content">
          <section className="pageHeading">
            <div><p className="sectionLabel">Customer development</p><h1>Sales command center</h1><p>Configure product lines, launch evidence-backed customer discovery, and move qualified leads toward CRM and outreach.</p></div>
            <button className="outlineButton exportButton" type="button">Export activity</button>
          </section>
          {error && <div className="errorBanner" role="alert">{error}</div>}
          <section className="metricGrid" aria-label="Sales metrics">{metrics.map((metric) => <MetricTile key={metric.label} {...metric} />)}</section>
          <ProductLineSetup productLines={productLines} loading={loadingProductLines} creating={creatingProductLine} onCreate={createProductLineFromForm} />
          <CustomerAgent
            productLines={productLines}
            selectedProductLineId={selectedProductLineId}
            targetMarket={targetMarket}
            buyerProfile={buyerProfile}
            running={running}
            runMessage={selectedProductLine ? runMessage : "Create the first product line before discovery"}
            onProductLineChange={selectProductLine}
            onTargetMarketChange={setTargetMarket}
            onBuyerProfileChange={setBuyerProfile}
            onRun={runDiscovery}
          />
          <div className="secondaryGrid"><ReviewQueue onOpen={() => setReviewOpen(true)} /><FollowUpTimeline /></div>
          <LeadTable leads={leads} priorityOnly={priorityOnly} onPriorityToggle={() => setPriorityOnly((current) => !current)} />
        </div>
      </section>
      <ReviewDrawer open={reviewOpen} onClose={() => setReviewOpen(false)} />
    </main>
  );
}
