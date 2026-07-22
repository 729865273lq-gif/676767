"use client";

import { FormEvent, useState } from "react";

type Lead = {
  company: string;
  country: string;
  category: string;
  contact: string;
  email: string;
  score: number;
  status: "Priority" | "Qualified" | "Research";
  evidence: string;
};

const leadSeed: Lead[] = [
  {
    company: "LumenHaus GmbH",
    country: "Germany",
    category: "Lighting distributor",
    contact: "Anna Weber, Procurement",
    email: "procurement@lumenhaus.de",
    score: 94,
    status: "Priority",
    evidence: "Commercial lighting portfolio and active project tender page",
  },
  {
    company: "Rheinland Industriebedarf",
    country: "Germany",
    category: "Industrial supply",
    contact: "Markus Klein, Category Lead",
    email: "m.klein@rheinland-ib.de",
    score: 88,
    status: "Priority",
    evidence: "Lists LED floodlight and warehouse refurbishment projects",
  },
  {
    company: "Nordlicht Handel",
    country: "Germany",
    category: "Electrical wholesaler",
    contact: "Contact research pending",
    email: "sales@nordlicht-handel.de",
    score: 72,
    status: "Qualified",
    evidence: "Business category and corporate contact channel verified",
  },
  {
    company: "Bauwerk Lichtsysteme",
    country: "Germany",
    category: "Project integrator",
    contact: "Sophie Hartmann, Project buyer",
    email: "s.hartmann@bauwerk-licht.de",
    score: 81,
    status: "Qualified",
    evidence: "Recent commercial retrofit case studies match target segment",
  },
];

const metrics = [
  { label: "New leads", value: "36", note: "+12 vs. yesterday", tone: "blue" },
  { label: "Priority leads", value: "18", note: "50% evidence complete", tone: "cyan" },
  { label: "Drafts to review", value: "8", note: "3 need approval today", tone: "orange" },
  { label: "Positive replies", value: "6", note: "Reply rate 12.5%", tone: "green" },
];

const navItems = ["Overview", "Customer Agent", "CRM", "Email review", "Inbox", "Knowledge base"];

function scoreClass(score: number) {
  if (score >= 90) return "score scoreHigh";
  if (score >= 80) return "score scoreMedium";
  return "score scoreLow";
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

function LeadTable({ leads, priorityOnly, onPriorityToggle }: { leads: Lead[]; priorityOnly: boolean; onPriorityToggle: () => void }) {
  const displayedLeads = priorityOnly ? leads.filter((lead) => lead.status === "Priority") : leads;

  return (
    <section className="dataSection" aria-labelledby="lead-results-title">
      <div className="sectionHeader">
        <div>
          <p className="sectionLabel">Customer Agent output</p>
          <h2 id="lead-results-title">Recommended companies</h2>
        </div>
        <div className="tableActions">
          <button className="textButton" type="button" onClick={onPriorityToggle}>
            {priorityOnly ? "Show all leads" : "Show priority leads"}
          </button>
          <button className="outlineButton" type="button">Save selected</button>
        </div>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Company</th>
              <th scope="col">Profile</th>
              <th scope="col">Contact channel</th>
              <th scope="col">Evidence</th>
              <th scope="col">Fit score</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {displayedLeads.map((lead) => (
              <tr key={lead.company}>
                <td><strong>{lead.company}</strong><span>{lead.country}</span></td>
                <td>{lead.category}</td>
                <td><strong className="contactName">{lead.contact}</strong><span>{lead.email}</span></td>
                <td className="evidence">{lead.evidence}</td>
                <td><span className={scoreClass(lead.score)}>{lead.score}</span></td>
                <td><span className={`status status${lead.status}`}>{lead.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CustomerAgent({ onRun, running, complete }: { onRun: (event: FormEvent<HTMLFormElement>) => void; running: boolean; complete: boolean }) {
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
          Product
          <input aria-label="Product" defaultValue="Industrial LED lighting" name="product" required />
        </label>
        <label>
          Target country
          <select aria-label="Target country" defaultValue="Germany" name="country">
            <option>Germany</option>
            <option>France</option>
            <option>United Kingdom</option>
            <option>United States</option>
          </select>
        </label>
        <label>
          Buyer profile
          <select defaultValue="Distributor / project buyer" name="buyer">
            <option>Distributor / project buyer</option>
            <option>Manufacturer</option>
            <option>Importer</option>
            <option>Retail chain</option>
          </select>
        </label>
        <button className="primaryButton" type="submit" disabled={running}>
          {running ? "Building lead list..." : "Start discovery"}
        </button>
        <div className={`runStatus ${complete ? "runComplete" : ""}`} aria-live="polite">
          <span className="statusDot" aria-hidden="true" />
          {complete ? "Discovery complete · 36 companies screened" : "Ready for a targeted discovery run"}
        </div>
      </form>
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
        <li><time>11:00</time><span className="timelineDot cyanDot" /><div><strong>Send approved introduction</strong><p>LumenHaus GmbH · owner: Mia Chen</p></div></li>
        <li><time>Tomorrow</time><span className="timelineDot orangeDot" /><div><strong>Follow up on quotation</strong><p>Rheinland Industriebedarf · no reply in 4 days</p></div></li>
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
          <button className="closeButton" type="button" aria-label="Close review queue" onClick={onClose}>×</button>
        </div>
        <p className="drawerCopy">Every draft passed language, product evidence, personalization and call-to-action checks before review.</p>
        <article className="draftCard">
          <span className="status statusPriority">Priority lead</span>
          <h3>Lighting solutions for commercial retrofit projects</h3>
          <p>To: Anna Weber · LumenHaus GmbH</p>
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
  const [running, setRunning] = useState(false);
  const [complete, setComplete] = useState(false);
  const [priorityOnly, setPriorityOnly] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);

  function runDiscovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRunning(true);
    setComplete(false);
    window.setTimeout(() => {
      setRunning(false);
      setComplete(true);
    }, 700);
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
        <div className="sidebarFooter"><span className="connectionDot" />System operational<span className="tenant">NOVA EXPORT</span></div>
      </aside>
      <section className="workspace" id="top">
        <header className="topbar">
          <div className="crumbs"><span>Sales workspace</span><strong>{activeNav}</strong></div>
          <div className="topbarActions"><button className="utilityButton" type="button">EN</button><button className="profileButton" type="button" aria-label="Open Mia Chen profile">MC</button></div>
        </header>
        <div className="content">
          <section className="pageHeading">
            <div><p className="sectionLabel">Monday, 14 July</p><h1>Sales command center</h1><p>Prioritize verified buyers, approve strong outreach, and keep every next step moving.</p></div>
            <button className="outlineButton exportButton" type="button">Export activity</button>
          </section>
          <section className="metricGrid" aria-label="Sales metrics">{metrics.map((metric) => <MetricTile key={metric.label} {...metric} />)}</section>
          <CustomerAgent onRun={runDiscovery} running={running} complete={complete} />
          <div className="secondaryGrid"><ReviewQueue onOpen={() => setReviewOpen(true)} /><FollowUpTimeline /></div>
          <LeadTable leads={leadSeed} priorityOnly={priorityOnly} onPriorityToggle={() => setPriorityOnly((current) => !current)} />
        </div>
      </section>
      <ReviewDrawer open={reviewOpen} onClose={() => setReviewOpen(false)} />
    </main>
  );
}
