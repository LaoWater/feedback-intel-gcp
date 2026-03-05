import { useState, useEffect, useRef } from "react";

const SECTIONS = [
  {
    id: "overview",
    icon: "◎",
    title: "The Big Picture",
    subtitle: "What this job actually is",
  },
  {
    id: "architecture",
    icon: "△",
    title: "System Architecture",
    subtitle: "The GCP machine you'd operate",
  },
  {
    id: "pipeline",
    icon: "⟿",
    title: "Data → Intelligence Pipeline",
    subtitle: "End-to-end flow, step by step",
  },
  {
    id: "stack",
    icon: "⬡",
    title: "The GCP Stack Deep Dive",
    subtitle: "Every tool & what it does",
  },
  {
    id: "daily",
    icon: "☰",
    title: "Your Day-to-Day",
    subtitle: "What you'd actually do each week",
  },
  {
    id: "fit",
    icon: "⚡",
    title: "Your Edge & Gaps",
    subtitle: "Honest mapping of your profile",
  },
  {
    id: "prep",
    icon: "◈",
    title: "Interview Prep Map",
    subtitle: "What to study & practice",
  },
];

const ACCENT = "#E8FF47";
const BG_DARK = "#0A0A0F";
const BG_CARD = "#12121A";
const BG_CARD_HOVER = "#1A1A25";
const TEXT_PRIMARY = "#E8E8EF";
const TEXT_SECONDARY = "#8888A0";
const BORDER = "#2A2A3A";

const ExpandableBlock = ({ title, icon, children, defaultOpen = false, accent = ACCENT }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div
      style={{
        border: `1px solid ${open ? accent + "40" : BORDER}`,
        borderRadius: 12,
        marginBottom: 12,
        background: open ? BG_CARD_HOVER : BG_CARD,
        transition: "all 0.3s ease",
        overflow: "hidden",
      }}
    >
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%",
          padding: "16px 20px",
          background: "transparent",
          border: "none",
          color: TEXT_PRIMARY,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 12,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 14,
          textAlign: "left",
        }}
      >
        <span style={{ color: accent, fontSize: 18, minWidth: 24, textAlign: "center" }}>{icon || "▸"}</span>
        <span style={{ flex: 1, fontWeight: 600 }}>{title}</span>
        <span
          style={{
            color: TEXT_SECONDARY,
            transform: open ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 0.2s ease",
            fontSize: 16,
          }}
        >
          ▸
        </span>
      </button>
      {open && (
        <div
          style={{
            padding: "0 20px 20px 56px",
            fontFamily: "'IBM Plex Sans', sans-serif",
            fontSize: 14,
            lineHeight: 1.75,
            color: TEXT_SECONDARY,
          }}
        >
          {children}
        </div>
      )}
    </div>
  );
};

const Tag = ({ children, color = ACCENT }) => (
  <span
    style={{
      display: "inline-block",
      padding: "2px 10px",
      borderRadius: 100,
      fontSize: 11,
      fontFamily: "'JetBrains Mono', monospace",
      fontWeight: 600,
      background: color + "18",
      color: color,
      border: `1px solid ${color}30`,
      marginRight: 6,
      marginBottom: 4,
    }}
  >
    {children}
  </span>
);

const FlowStep = ({ num, title, desc, tools }) => (
  <div style={{ display: "flex", gap: 16, marginBottom: 20 }}>
    <div
      style={{
        minWidth: 36,
        height: 36,
        borderRadius: "50%",
        background: `${ACCENT}15`,
        border: `2px solid ${ACCENT}40`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 13,
        fontWeight: 700,
        color: ACCENT,
      }}
    >
      {num}
    </div>
    <div style={{ flex: 1 }}>
      <div style={{ color: TEXT_PRIMARY, fontWeight: 600, marginBottom: 4, fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}>{title}</div>
      <div style={{ color: TEXT_SECONDARY, fontSize: 13, lineHeight: 1.6, marginBottom: 8 }}>{desc}</div>
      {tools && <div>{tools.map((t) => <Tag key={t}>{t}</Tag>)}</div>}
    </div>
  </div>
);

const SkillBar = ({ label, level, max = 5, color = ACCENT }) => (
  <div style={{ marginBottom: 12 }}>
    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
      <span style={{ fontSize: 12, fontFamily: "'JetBrains Mono', monospace", color: TEXT_PRIMARY }}>{label}</span>
      <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: TEXT_SECONDARY }}>
        {level}/{max}
      </span>
    </div>
    <div style={{ height: 6, background: BORDER, borderRadius: 3, overflow: "hidden" }}>
      <div
        style={{
          width: `${(level / max) * 100}%`,
          height: "100%",
          background: `linear-gradient(90deg, ${color}, ${color}90)`,
          borderRadius: 3,
          transition: "width 0.8s ease",
        }}
      />
    </div>
  </div>
);

const Callout = ({ children, type = "info" }) => {
  const colors = {
    info: "#47A0FF",
    warn: "#FFB347",
    success: "#47FF8A",
    key: ACCENT,
  };
  const c = colors[type];
  return (
    <div
      style={{
        padding: "14px 18px",
        borderLeft: `3px solid ${c}`,
        background: `${c}08`,
        borderRadius: "0 8px 8px 0",
        marginBottom: 14,
        fontSize: 13,
        lineHeight: 1.65,
        color: TEXT_SECONDARY,
      }}
    >
      {children}
    </div>
  );
};

const SectionOverview = () => (
  <div>
    <Callout type="key">
      <span style={{ color: TEXT_PRIMARY, fontWeight: 600 }}>TL;DR — </span>
      You'd be the <strong style={{ color: ACCENT }}>core engineer</strong> on a small team building a customer-feedback intelligence system on GCP. Think: raw calls & tickets → transcription → AI classification → business dashboards. The system already exists. You'd maintain, extend, and improve it.
    </Callout>

    <p style={{ color: TEXT_PRIMARY, fontWeight: 600, marginBottom: 8 }}>What the company has built (or is building):</p>
    <p>
      An <strong style={{ color: TEXT_PRIMARY }}>end-to-end feedback intelligence platform</strong>. Customers call support, write tickets on Zendesk, fill surveys. All of that raw data gets piped through a GCP-based system that:
    </p>
    <ol style={{ paddingLeft: 20, marginTop: 10 }}>
      <li style={{ marginBottom: 8 }}>Transcribes calls (speech → text via Google Chirp)</li>
      <li style={{ marginBottom: 8 }}>Classifies feedback by business unit (Logistics, Tech, UX, Support)</li>
      <li style={{ marginBottom: 8 }}>Extracts sentiment, tone, product category</li>
      <li style={{ marginBottom: 8 }}>Feeds everything into Looker dashboards for stakeholders</li>
      <li style={{ marginBottom: 8 }}>Provides intelligent search over all this data (Vertex AI Search, AgentSpace)</li>
    </ol>

    <Callout type="info">
      <strong style={{ color: "#47A0FF" }}>HR context decoded:</strong> "GCP implementation of existing system" means the logic/pipeline already works conceptually (maybe on another cloud or as a prototype). Your job is to make it production-grade on Google Cloud. Small team = you'll own major chunks of the codebase.
    </Callout>

    <p style={{ color: TEXT_PRIMARY, fontWeight: 600, marginBottom: 8, marginTop: 20 }}>The team structure (as she described):</p>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 8 }}>
      {[
        { role: "You (Engineer)", desc: "Builds and maintains the system. Writes the code, integrates services, debugs production." },
        { role: "Tech Lead", desc: "Architectural decisions, code review, technical direction. Your direct collaborator." },
        { role: "MLOps", desc: "Handles model deployment, monitoring, CI/CD for ML pipelines. Keeps models running." },
        { role: "PM", desc: "Prioritizes features, interfaces with business stakeholders, manages roadmap." },
      ].map((m) => (
        <div key={m.role} style={{ padding: 14, background: BG_CARD, border: `1px solid ${BORDER}`, borderRadius: 10 }}>
          <div style={{ fontSize: 12, fontFamily: "'JetBrains Mono', monospace", color: ACCENT, marginBottom: 6, fontWeight: 700 }}>{m.role}</div>
          <div style={{ fontSize: 12, lineHeight: 1.5 }}>{m.desc}</div>
        </div>
      ))}
    </div>

    <Callout type="warn">
      <strong style={{ color: "#FFB347" }}>What "small team" really means:</strong> You won't have the luxury of specialization. You'll touch everything — from data ingestion scripts to Looker dashboard configs to prompt engineering for Gemini. This is both a risk (lots to learn fast) and an opportunity (massive ownership and growth).
    </Callout>
  </div>
);

const SectionArchitecture = () => (
  <div>
    <p style={{ marginBottom: 16 }}>Here's the mental model of the entire system. Think of it as 5 layers, bottom to top:</p>

    <div style={{ background: "#0D0D14", border: `1px solid ${BORDER}`, borderRadius: 12, padding: 20, marginBottom: 20, fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>
      {[
        { layer: "5 · PRESENTATION", color: "#47A0FF", items: "Looker Studio · Dashboards · Drill-downs · Alerts", desc: "What stakeholders see" },
        { layer: "4 · SEARCH & RETRIEVAL", color: "#A347FF", items: "Vertex AI Search · BigQuery Search · AgentSpace · NotebookLM", desc: "How people query the data" },
        { layer: "3 · AI / ML LAYER", color: ACCENT, items: "Vertex AI · Gemini · Fine-tuned classifiers · Prompt pipelines", desc: "Where intelligence happens" },
        { layer: "2 · DATA PROCESSING", color: "#FF8C47", items: "Dataflow · Cloud Functions · Chirp STT · ETL jobs", desc: "Transform & enrich raw data" },
        { layer: "1 · DATA INGESTION", color: "#FF4770", items: "BigQuery · Zendesk API · Cloud Storage · Pub/Sub", desc: "Where data enters the system" },
      ].map((l, i) => (
        <div key={l.layer} style={{ marginBottom: i < 4 ? 2 : 0 }}>
          <div
            style={{
              padding: "12px 16px",
              background: `${l.color}10`,
              borderLeft: `3px solid ${l.color}`,
              borderRadius: 4,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            <div>
              <span style={{ color: l.color, fontWeight: 700, marginRight: 12 }}>{l.layer}</span>
              <span style={{ color: TEXT_SECONDARY, fontSize: 11 }}>{l.items}</span>
            </div>
            <span style={{ color: TEXT_SECONDARY, fontSize: 10, fontStyle: "italic" }}>{l.desc}</span>
          </div>
        </div>
      ))}
    </div>

    <ExpandableBlock title="Layer 1 — Data Ingestion (deep dive)" icon="①">
      <p>This is where raw customer data enters the system. You'd be writing and maintaining the connectors that pull data from multiple sources into GCP.</p>
      <FlowStep num="→" title="BigQuery as the data lake" desc="BigQuery isn't just for analytics here — it's the central storage layer. All customer feedback eventually lands in BigQuery tables. You'd design the table schemas (partitioning by date, clustering by BU), manage data lifecycle, and write SQL transforms." tools={["BigQuery", "SQL", "Schema Design"]} />
      <FlowStep num="→" title="Zendesk Integration" desc="Customer tickets live in Zendesk. You'd build a pipeline (likely Cloud Functions or a scheduled Dataflow job) that hits the Zendesk REST API, extracts ticket data, normalizes it, and loads it into BigQuery. Think: pagination handling, rate limiting, incremental loads (only new tickets since last sync)." tools={["Zendesk API", "Cloud Functions", "REST"]} />
      <FlowStep num="→" title="Audio Files → Cloud Storage" desc="Support calls are recorded and dropped into Cloud Storage buckets. You'd set up bucket notifications (via Pub/Sub) so that when a new audio file lands, it automatically triggers the transcription pipeline." tools={["Cloud Storage", "Pub/Sub", "Event-driven"]} />
    </ExpandableBlock>

    <ExpandableBlock title="Layer 2 — Data Processing (deep dive)" icon="②">
      <p>Raw data is messy. This layer cleans, transforms, and enriches it.</p>
      <FlowStep num="→" title="Google Chirp (Speech-to-Text)" desc="Chirp is Google's latest STT model — multilingual, high accuracy. You'd build the pipeline that takes audio from Cloud Storage, sends it to Chirp, gets back transcripts, and stores them in BigQuery. Key challenges: handling long calls (chunking), speaker diarization (who said what), dealing with accents/noise, and managing costs (STT is priced per minute of audio)." tools={["Chirp", "Cloud Storage", "Async Processing"]} />
      <FlowStep num="→" title="Dataflow (Apache Beam)" desc="Dataflow is GCP's managed data processing service (based on Apache Beam). You'd use it for batch and streaming ETL — cleaning text, normalizing formats, deduplication, joining data from different sources. Think of it as the 'plumbing' between raw data and the AI layer." tools={["Dataflow", "Apache Beam", "Python/Java"]} />
      <FlowStep num="→" title="Cloud Functions for glue logic" desc="Lightweight serverless functions that handle events — a new file uploaded, a webhook from Zendesk, a scheduled cleanup job. You'd write these in Python or Node.js." tools={["Cloud Functions", "Python", "Serverless"]} />
    </ExpandableBlock>

    <ExpandableBlock title="Layer 3 — AI / ML Layer (deep dive)" icon="③">
      <p>This is the heart of the system and where it gets really interesting.</p>
      <FlowStep num="→" title="Vertex AI — The ML Platform" desc="Vertex AI is GCP's unified ML platform. It's where you'd manage model training, tuning, deployment, and prediction. You wouldn't build models from scratch — you'd leverage Gemini and fine-tune it for specific classification tasks. Vertex AI provides: Model Registry (track versions), Endpoints (serve predictions), Pipelines (automate training workflows), Feature Store (manage ML features)." tools={["Vertex AI", "Model Management", "Pipelines"]} />
      <FlowStep num="→" title="Gemini — The LLM" desc="Gemini is Google's flagship LLM. You'd use it in two modes: (1) Zero-shot / few-shot classification via prompts — send customer feedback + a structured prompt, get back classification, sentiment, and extracted entities. (2) Fine-tuned models — take a base Gemini model, fine-tune it on labeled customer feedback to get higher accuracy for your specific categories. This is where your local synthetic training experience is directly relevant." tools={["Gemini API", "Prompt Engineering", "Fine-tuning"]} />
      <FlowStep num="→" title="Classification Pipeline" desc="The core loop: feedback text comes in → sent to Gemini with a classification prompt → model returns: Business Unit (Logistics/Tech/UX/Support), Sentiment (positive/negative/neutral), Tone (frustrated/satisfied/confused), Product Category, Confidence score. You'd need to handle low-confidence cases (human review queue), track accuracy metrics, and iterate on prompts." tools={["Classification", "Prompt Design", "Evaluation"]} />
    </ExpandableBlock>

    <ExpandableBlock title="Layer 4 — Search & Retrieval (deep dive)" icon="④">
      <p>Once data is classified and enriched, people need to find and explore it.</p>
      <FlowStep num="→" title="Vertex AI Search" desc="Think of this as building a 'Google Search' but for internal customer feedback. You'd index all classified feedback, transcripts, and reports. Supports semantic search (meaning-based, not just keyword matching), faceted filtering (by BU, sentiment, date range), and summarization. You'd configure the search app, manage the data store, and tune relevance." tools={["Vertex AI Search", "Semantic Search", "RAG"]} />
      <FlowStep num="→" title="AgentSpace / NotebookLM" desc="AgentSpace (Gemini Enterprise) is like giving stakeholders a ChatGPT-style interface over your company data. NotebookLM lets users upload documents and have AI-powered conversations. You'd set up the data connectors, configure access controls, and ensure the AI has the right context. This is cutting-edge stuff — very new Google products." tools={["AgentSpace", "NotebookLM", "Enterprise AI"]} />
    </ExpandableBlock>

    <ExpandableBlock title="Layer 5 — Presentation (deep dive)" icon="⑤">
      <FlowStep num="→" title="Looker Studio Dashboards" desc="The final output that stakeholders actually see. You'd build and maintain dashboards that connect to BigQuery, showing: feedback volume by BU over time, sentiment distribution, top issues per category, confidence score distributions. Key skill: making BigQuery → Looker connections efficient (materialized views, pre-aggregated tables). You'd also build drill-down capabilities — click a BU → see individual tickets → see the original transcript." tools={["Looker Studio", "BigQuery Views", "Data Viz"]} />
    </ExpandableBlock>
  </div>
);

const SectionPipeline = () => (
  <div>
    <p style={{ marginBottom: 16 }}>Let's trace a single customer call from start to finish to see how every piece connects:</p>

    <div style={{ position: "relative", paddingLeft: 20 }}>
      <div style={{ position: "absolute", left: 17, top: 0, bottom: 0, width: 2, background: `linear-gradient(to bottom, ${ACCENT}, #47A0FF, #A347FF, #FF4770)` }} />

      <FlowStep num="1" title="Customer calls support" desc="A frustrated customer calls about a late delivery. The call is recorded by the phone system and the audio file (.wav/.mp3) is uploaded to a Cloud Storage bucket — e.g., gs://company-calls/2025/03/02/call-18923.wav" tools={["Cloud Storage"]} />
      <FlowStep num="2" title="Event triggers pipeline" desc="Cloud Storage sends a Pub/Sub notification → A Cloud Function picks it up → Initiates the transcription job. This is event-driven architecture — no polling, no cron jobs, things happen automatically when data arrives." tools={["Pub/Sub", "Cloud Functions"]} />
      <FlowStep num="3" title="Speech-to-Text via Chirp" desc='Chirp processes the audio and returns a transcript with timestamps and speaker labels. For example: the agent greeting, the customer explaining their package was supposed to arrive days ago, expressing frustration. The transcript is stored in BigQuery alongside metadata (call ID, duration, agent ID, timestamp).' tools={["Chirp", "BigQuery"]} />
      <FlowStep num="4" title="AI Classification via Gemini" desc='The transcript is sent to Gemini (via Vertex AI endpoint) with a classification prompt. The model returns structured JSON with fields like: bu → "Logistics", sentiment → "negative", tone → "frustrated", category → "delivery_delay", confidence → 0.94, key_issues → ["late_delivery", "no_tracking_update"]. This structured output is stored back in BigQuery as enriched data.' tools={["Vertex AI", "Gemini", "Prompt Engineering"]} />
      <FlowStep num="5" title="Data lands in analytics tables" desc="The enriched record joins millions of others in BigQuery analytical tables. Materialized views pre-aggregate common queries (e.g., daily sentiment by BU). These power the Looker dashboards in near-real-time." tools={["BigQuery", "Materialized Views"]} />
      <FlowStep num="6" title="Stakeholder opens dashboard" desc="The Head of Logistics opens Looker Studio, sees a spike in negative sentiment for 'delivery_delay' this week, drills down to individual transcripts, reads the AI-extracted key issues, and takes action — maybe escalates to the courier partner." tools={["Looker Studio"]} />
      <FlowStep num="7" title="Someone searches for deeper context" desc='An analyst uses Vertex AI Search or AgentSpace to ask: "What are the main complaints about delivery delays in the last month?" — and gets a semantic, AI-generated summary across hundreds of calls.' tools={["Vertex AI Search", "AgentSpace"]} />
    </div>
  </div>
);

const SectionStack = () => (
  <div>
    <p style={{ marginBottom: 16 }}>Every GCP service mentioned in the JD, explained as if you need to work with it tomorrow:</p>

    {[
      {
        name: "BigQuery",
        what: "Google's serverless data warehouse. Think PostgreSQL but it can scan terabytes in seconds. No indexes needed — it uses columnar storage and auto-scales.",
        you: "You'd write SQL daily. Design table schemas, create views, optimize queries, manage partitioning (by date) and clustering (by BU). Also BigQuery ML for simple in-database model training.",
        analogy: "If Supabase is a house, BigQuery is a skyscraper. Same SQL language, wildly different scale.",
        tags: ["SQL", "Columnar", "Serverless", "Petabyte-scale"],
      },
      {
        name: "Vertex AI",
        what: "GCP's unified ML platform. Model training, tuning, deployment, monitoring — all in one place. Not a single tool but an ecosystem.",
        you: "You'd use Vertex AI Pipelines to orchestrate training runs, deploy models to endpoints, manage A/B testing of different model versions, and monitor prediction quality over time.",
        analogy: "Think of it as the 'IDE' for ML. Just like VS Code is where you write code, Vertex AI is where you manage the entire ML lifecycle.",
        tags: ["Model Registry", "Endpoints", "Pipelines", "AutoML"],
      },
      {
        name: "Gemini",
        what: "Google's multimodal LLM (text, image, audio, video). Competes with GPT-4, Claude. Available through Vertex AI or direct API.",
        you: "Prompt engineering is your primary tool. You'd craft system prompts that instruct Gemini to classify feedback, extract entities, and return structured JSON. Also fine-tuning for domain-specific accuracy.",
        analogy: "You've worked with Claude's API. Gemini's API is structurally identical — messages array, system prompt, temperature control, structured output. The concepts transfer 1:1.",
        tags: ["LLM", "Multimodal", "Classification", "Structured Output"],
      },
      {
        name: "Google Chirp",
        what: "Google's latest speech-to-text model. Supports 100+ languages, handles accents well, includes punctuation and speaker diarization.",
        you: "Build transcription pipelines — submit audio, handle async responses, parse results, manage errors (corrupted audio, silence, background noise).",
        analogy: "Like Whisper (OpenAI) but as a managed GCP service. No GPU management, just API calls.",
        tags: ["Speech-to-Text", "Diarization", "Multilingual"],
      },
      {
        name: "Dataflow",
        what: "Managed service for running Apache Beam pipelines. Handles both batch (process all data at once) and streaming (process data as it arrives) processing.",
        you: "Write Python/Java Apache Beam pipelines for ETL — extract from sources, transform (clean, normalize, dedupe), load into BigQuery. Dataflow auto-scales workers based on load.",
        analogy: "If Cloud Functions are individual workers doing one task, Dataflow is a factory assembly line processing data at scale.",
        tags: ["Apache Beam", "ETL", "Batch", "Streaming"],
      },
      {
        name: "Looker Studio",
        what: "Google's free dashboard/reporting tool. Connects directly to BigQuery. Drag-and-drop chart builder with filters, drill-downs, and sharing.",
        you: "Build dashboards stakeholders love. Key: make BigQuery efficient underneath — slow queries = slow dashboards. Create materialized views and summary tables specifically for Looker.",
        analogy: "Like a more business-focused, Google-native version of Grafana or Metabase. Less code, more drag-and-drop.",
        tags: ["Dashboards", "Data Viz", "BigQuery Integration"],
      },
      {
        name: "Vertex AI Search",
        what: "Managed semantic search over your data. You provide documents/data, it builds the search index, handles embeddings, and provides a search API. Basically RAG-as-a-service.",
        you: "Configure data stores (connect to BigQuery tables, Cloud Storage buckets), tune relevance, build search applications. This is where RAG concepts you know become GCP infrastructure.",
        analogy: "Instead of manually building a vector DB + embedding pipeline + retrieval logic, Vertex AI Search does it all as a managed service.",
        tags: ["Semantic Search", "RAG", "Embeddings", "Managed"],
      },
      {
        name: "AgentSpace",
        what: "New Google enterprise product (previously 'Gemini for Google Cloud'). Lets employees chat with company data using AI — like having an internal ChatGPT that knows your business.",
        you: "Set up data connectors, configure access controls, ensure the AI gives accurate answers grounded in your data. Very new product — you'd be learning alongside everyone else.",
        analogy: "Imagine if you could give Claude access to all your company's BigQuery data and Zendesk tickets and let anyone in the company chat with it. That's AgentSpace.",
        tags: ["Enterprise AI", "Conversational", "Cutting-edge"],
      },
    ].map((tool) => (
      <ExpandableBlock key={tool.name} title={tool.name} icon="⬡">
        <p style={{ color: TEXT_PRIMARY, fontWeight: 600, fontSize: 12, marginBottom: 4 }}>WHAT IT IS</p>
        <p style={{ marginBottom: 14 }}>{tool.what}</p>
        <p style={{ color: TEXT_PRIMARY, fontWeight: 600, fontSize: 12, marginBottom: 4 }}>WHAT YOU'D DO WITH IT</p>
        <p style={{ marginBottom: 14 }}>{tool.you}</p>
        <Callout type="info">
          <strong style={{ color: "#47A0FF" }}>Your mental model: </strong>{tool.analogy}
        </Callout>
        <div>{tool.tags.map((t) => <Tag key={t}>{t}</Tag>)}</div>
      </ExpandableBlock>
    ))}
  </div>
);

const SectionDaily = () => (
  <div>
    <Callout type="key">
      <span style={{ color: TEXT_PRIMARY, fontWeight: 600 }}>Context: </span>
      Small team, you're the engineer. This means you don't just write code — you're the person who makes things work end-to-end. Here's what a realistic week looks like:
    </Callout>

    {[
      {
        category: "Building & Maintaining Pipelines",
        pct: "~35%",
        color: ACCENT,
        tasks: [
          "Writing and debugging Dataflow jobs (Python/Beam) that process customer data",
          "Maintaining Zendesk → BigQuery sync (handling API changes, new fields, edge cases)",
          "Building/updating the Chirp transcription pipeline when new call formats appear",
          "Writing Cloud Functions for event-driven glue logic",
          "Managing BigQuery tables — schema migrations, partition management, cost optimization",
        ],
      },
      {
        category: "AI/ML Integration",
        pct: "~25%",
        color: "#A347FF",
        tasks: [
          "Iterating on Gemini prompts for feedback classification (this is creative, iterative work)",
          "Evaluating classification accuracy — building eval datasets, computing precision/recall",
          "Fine-tuning models on new labeled data when prompt engineering isn't enough",
          "Setting up Vertex AI Search data stores and tuning retrieval quality",
          "Working with the MLOps person on model versioning and A/B testing",
        ],
      },
      {
        category: "Dashboards & Visualization",
        pct: "~15%",
        color: "#47A0FF",
        tasks: [
          "Building Looker Studio dashboards with the right drill-down capabilities",
          "Creating BigQuery views/materialized views that make dashboards fast",
          "Working with PM and stakeholders to understand what metrics they need",
          "Debugging 'why does this chart show weird numbers' — usually a data quality issue",
        ],
      },
      {
        category: "Collaboration & Planning",
        pct: "~15%",
        color: "#FF8C47",
        tasks: [
          "Sprint planning with PM (agile methodology — mentioned in JD)",
          "Architecture discussions with Tech Lead",
          "Reviewing deployments with MLOps",
          "Stakeholder meetings to understand new requirements",
          "Code reviews (mostly with TL, maybe the MLOps person)",
        ],
      },
      {
        category: "Exploration & Learning",
        pct: "~10%",
        color: "#FF4770",
        tasks: [
          "Evaluating new GCP tools (they explicitly mention this in the JD)",
          "Trying new Gemini model versions when Google releases them",
          "Prototyping AgentSpace/NotebookLM features (these are very new products)",
          "Reading docs, taking GCP training, keeping up with rapid changes",
        ],
      },
    ].map((block) => (
      <ExpandableBlock key={block.category} title={`${block.category}  ·  ${block.pct}`} icon="◆" accent={block.color}>
        {block.tasks.map((t, i) => (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "flex-start" }}>
            <span style={{ color: block.color, fontSize: 8, marginTop: 6 }}>●</span>
            <span>{t}</span>
          </div>
        ))}
      </ExpandableBlock>
    ))}
  </div>
);

const SectionFit = () => (
  <div>
    <Callout type="key">
      <span style={{ color: TEXT_PRIMARY, fontWeight: 600 }}>Honest assessment — </span>
      based on what I know about your work with BodyOS, TerapieAcasa, computer vision, Supabase, and your teaching.
    </Callout>

    <p style={{ color: TEXT_PRIMARY, fontWeight: 600, marginBottom: 12, marginTop: 16 }}>Where you're strong:</p>

    <SkillBar label="Python / Software Engineering" level={4} color="#47FF8A" />
    <SkillBar label="LLM Integration (Claude API, prompts, structured output)" level={4} color="#47FF8A" />
    <SkillBar label="System Architecture Thinking" level={3.5} color="#47FF8A" />
    <SkillBar label="REST API Design & Integration" level={4} color="#47FF8A" />
    <SkillBar label="Teaching / Communication" level={4.5} color="#47FF8A" />
    <SkillBar label="AI/ML Concepts (CNNs, YOLO, training pipelines)" level={3.5} color="#47FF8A" />
    <SkillBar label="Fast Learner / Builder Mentality" level={5} color="#47FF8A" />

    <p style={{ color: TEXT_PRIMARY, fontWeight: 600, marginBottom: 12, marginTop: 24 }}>Where you need to grow (and it's all learnable):</p>

    <SkillBar label="GCP Services (BigQuery, Vertex AI, Dataflow)" level={1.5} color="#FFB347" />
    <SkillBar label="Production ML Pipelines" level={1.5} color="#FFB347" />
    <SkillBar label="Data Engineering at Scale" level={2} color="#FFB347" />
    <SkillBar label="Looker Studio / Data Viz" level={1} color="#FF4770" />
    <SkillBar label="Apache Beam / Dataflow" level={1} color="#FF4770" />
    <SkillBar label="Speech-to-Text Systems" level={1} color="#FF4770" />

    <div style={{ marginTop: 24 }}>
      <ExpandableBlock title="Your killer angles for the interview" icon="✦" accent="#47FF8A">
        <p style={{ marginBottom: 12 }}><strong style={{ color: TEXT_PRIMARY }}>1. You've built real AI products end-to-end.</strong> BodyOS (CV + AI coaching), TerapieAcasa (Stripe + Supabase + real users), therapy chatbots — you're not a theoretician. You ship.</p>
        <p style={{ marginBottom: 12 }}><strong style={{ color: TEXT_PRIMARY }}>2. You understand the full stack.</strong> From React Native frontends to Supabase Edge Functions to AI model integration. This role needs someone who can connect all the pieces, not just one layer.</p>
        <p style={{ marginBottom: 12 }}><strong style={{ color: TEXT_PRIMARY }}>3. You've done the ML fundamentals.</strong> YOLO, CNNs, MediaPipe, synthetic data training — you understand what's happening under the hood when a model classifies feedback. Most "GenAI engineers" only know API calls.</p>
        <p style={{ marginBottom: 12 }}><strong style={{ color: TEXT_PRIMARY }}>4. You teach.</strong> The Art of Programming course proves you can explain complex concepts. In a small team, this matters — you'll be the person explaining technical decisions to the PM and stakeholders.</p>
        <p><strong style={{ color: TEXT_PRIMARY }}>5. Small-team mentality.</strong> You're an entrepreneur. You're used to wearing many hats. A 4-person team needs exactly this kind of person.</p>
      </ExpandableBlock>

      <ExpandableBlock title="How to frame the gaps" icon="◇" accent="#FFB347">
        <p style={{ marginBottom: 12 }}><strong style={{ color: TEXT_PRIMARY }}>GCP-specific experience: </strong> "I've built production systems on Supabase/Vercel/other cloud — the architectural patterns (event-driven, serverless, managed services) are the same. GCP is a different dialect, not a different language. I've already started hands-on with [Vertex AI / BigQuery] and I learn fast."</p>
        <p style={{ marginBottom: 12 }}><strong style={{ color: TEXT_PRIMARY }}>Production ML: </strong> "I've trained models locally (CV, synthetic data) and understand the ML lifecycle. I haven't done production ML deployment at scale, but I understand model versioning, evaluation metrics, and the MLOps person on the team covers the deployment infrastructure."</p>
        <p><strong style={{ color: TEXT_PRIMARY }}>Data Engineering: </strong> "My data experience is at application scale (Supabase, PostgreSQL). I'm transparent that BigQuery-scale data processing is new, but I've worked with SQL extensively and Apache Beam's programming model is conceptually similar to the data transformation work I've done."</p>
      </ExpandableBlock>
    </div>
  </div>
);

const SectionPrep = () => (
  <div>
    <Callout type="key">Prioritized by impact. Focus on the top sections first — they cover 80% of what you'd be asked.</Callout>

    {[
      {
        priority: "P0 — Must know cold",
        color: "#FF4770",
        items: [
          { topic: "BigQuery fundamentals", action: "Complete the BigQuery quickstart. Write 10 queries involving JOINs, window functions, partitioning, and creating views. Understand cost model (per-byte scanned).", time: "~4h" },
          { topic: "Vertex AI + Gemini API", action: "Set up a GCP project, call Gemini via Vertex AI SDK in Python. Build a simple text classification pipeline: input text → structured JSON output. Practice prompt engineering for classification tasks.", time: "~6h" },
          { topic: "System Design — Customer Feedback Pipeline", action: "Be ready to whiteboard the end-to-end architecture from this artifact. They WILL ask you to design something like this. Practice explaining data flow, trade-offs, and failure handling.", time: "~3h" },
          { topic: "GCP core services overview", action: "Know what Cloud Storage, Pub/Sub, Cloud Functions, Dataflow, and IAM do at a conceptual level. Don't need deep expertise, but need to speak fluently about when to use what.", time: "~3h" },
        ],
      },
      {
        priority: "P1 — Should understand well",
        color: "#FFB347",
        items: [
          { topic: "Dataflow / Apache Beam", action: "Read the Apache Beam programming guide. Understand PCollections, transforms (Map, Filter, GroupByKey), and the concept of windowing. Write a simple pipeline locally.", time: "~4h" },
          { topic: "Vertex AI Search", action: "Understand RAG architecture. Know how Vertex AI Search works: data stores, search apps, grounding. Be ready to explain how you'd make customer feedback searchable.", time: "~3h" },
          { topic: "ML Evaluation Metrics", action: "Precision, recall, F1, confusion matrices. Be able to discuss: 'How would you measure if the Gemini classifier is working well? What do you do when confidence is low?'", time: "~2h" },
          { topic: "Looker Studio basics", action: "Connect Looker Studio to a BigQuery dataset. Build a simple dashboard with filters. Understand calculated fields and data blending.", time: "~2h" },
        ],
      },
      {
        priority: "P2 — Nice to know / differentiators",
        color: "#47A0FF",
        items: [
          { topic: "Google Chirp STT", action: "Read the Cloud Speech-to-Text V2 docs (Chirp is the model, STT V2 is the API). Understand async recognition, speaker diarization, and word-level timestamps.", time: "~2h" },
          { topic: "AgentSpace & NotebookLM", action: "These are brand new. Read the product pages, watch demo videos. Having opinions on these shows you're tracking Google's AI roadmap.", time: "~1h" },
          { topic: "GCP Certifications (know the scope)", action: "You don't need certs for the interview, but know what Professional ML Engineer and Data Engineer certs cover. Shows you understand the skill domains.", time: "~1h" },
        ],
      },
    ].map((group) => (
      <div key={group.priority} style={{ marginBottom: 20 }}>
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 700, color: group.color, marginBottom: 12, padding: "8px 14px", background: `${group.color}10`, borderRadius: 8, display: "inline-block" }}>
          {group.priority}
        </div>
        {group.items.map((item) => (
          <ExpandableBlock key={item.topic} title={item.topic} icon="→" accent={group.color}>
            <p style={{ marginBottom: 8 }}>{item.action}</p>
            <Tag color={group.color}>⏱ {item.time}</Tag>
          </ExpandableBlock>
        ))}
      </div>
    ))}

    <Callout type="success">
      <strong style={{ color: "#47FF8A" }}>Total estimated prep time: </strong>~31 hours. Spread over 2 weeks = very doable. The P0 items (~16h) are the critical path.
    </Callout>
  </div>
);

const sectionComponents = {
  overview: SectionOverview,
  architecture: SectionArchitecture,
  pipeline: SectionPipeline,
  stack: SectionStack,
  daily: SectionDaily,
  fit: SectionFit,
  prep: SectionPrep,
};

export default function GenAIRoleExplorer() {
  const [activeSection, setActiveSection] = useState("overview");
  const [scrolled, setScrolled] = useState(false);
  const contentRef = useRef(null);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const handler = () => setScrolled(el.scrollTop > 10);
    el.addEventListener("scroll", handler);
    return () => el.removeEventListener("scroll", handler);
  }, []);

  const ActiveComponent = sectionComponents[activeSection];
  const activeMeta = SECTIONS.find((s) => s.id === activeSection);

  return (
    <div
      style={{
        width: "100%",
        height: "100vh",
        background: BG_DARK,
        color: TEXT_PRIMARY,
        display: "flex",
        fontFamily: "'IBM Plex Sans', sans-serif",
        overflow: "hidden",
      }}
    >
      <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=Instrument+Serif&display=swap" rel="stylesheet" />

      {/* Sidebar */}
      <nav
        style={{
          width: 280,
          minWidth: 280,
          borderRight: `1px solid ${BORDER}`,
          display: "flex",
          flexDirection: "column",
          background: "#08080D",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: "24px 20px 16px" }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: 3, color: TEXT_SECONDARY, textTransform: "uppercase", marginBottom: 8 }}>
            Role Deep Dive
          </div>
          <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: 22, lineHeight: 1.2, color: TEXT_PRIMARY }}>
            Senior Engineer
          </div>
          <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: 22, lineHeight: 1.2, color: ACCENT }}>
            GenAI · GCP
          </div>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "8px 12px" }}>
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              onClick={() => {
                setActiveSection(s.id);
                contentRef.current?.scrollTo(0, 0);
              }}
              style={{
                width: "100%",
                padding: "12px 14px",
                background: activeSection === s.id ? `${ACCENT}10` : "transparent",
                border: activeSection === s.id ? `1px solid ${ACCENT}25` : "1px solid transparent",
                borderRadius: 10,
                cursor: "pointer",
                textAlign: "left",
                marginBottom: 4,
                transition: "all 0.2s ease",
                display: "flex",
                alignItems: "center",
                gap: 12,
              }}
            >
              <span style={{ fontSize: 18, color: activeSection === s.id ? ACCENT : TEXT_SECONDARY, minWidth: 24, textAlign: "center" }}>
                {s.icon}
              </span>
              <div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, fontWeight: 600, color: activeSection === s.id ? TEXT_PRIMARY : TEXT_SECONDARY, marginBottom: 2 }}>
                  {s.title}
                </div>
                <div style={{ fontSize: 11, color: TEXT_SECONDARY, opacity: 0.7 }}>
                  {s.subtitle}
                </div>
              </div>
            </button>
          ))}
        </div>

        <div style={{ padding: "16px 20px", borderTop: `1px solid ${BORDER}`, fontSize: 10, fontFamily: "'JetBrains Mono', monospace", color: TEXT_SECONDARY }}>
          <span style={{ color: ACCENT }}>4</span> person team · <span style={{ color: ACCENT }}>GCP</span> native
        </div>
      </nav>

      {/* Main Content */}
      <main ref={contentRef} style={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}>
        <div
          style={{
            padding: "32px 40px 20px",
            borderBottom: scrolled ? `1px solid ${BORDER}` : "1px solid transparent",
            transition: "border-color 0.2s ease",
            position: "sticky",
            top: 0,
            background: BG_DARK,
            zIndex: 10,
          }}
        >
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: 2, color: ACCENT, textTransform: "uppercase", marginBottom: 6 }}>
            {activeMeta?.subtitle}
          </div>
          <h1 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 32, fontWeight: 400, margin: 0, color: TEXT_PRIMARY }}>
            {activeMeta?.title}
          </h1>
        </div>

        <div style={{ padding: "24px 40px 80px", maxWidth: 800 }}>
          <ActiveComponent />
        </div>
      </main>
    </div>
  );
}
