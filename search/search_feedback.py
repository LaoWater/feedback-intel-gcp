"""
Sprint 07 — Vertex AI Search setup and query.

Two modes:
  1. Setup (run once):  Create data store, import BigQuery data, create search engine
  2. Query (run anytime): Semantic search over classified feedback

Vertex AI Search is RAG-as-a-service — it handles embeddings, indexing,
semantic matching, and AI-generated summaries behind one API. We point it
at our enriched_feedback table and get natural language search over all
feedback (text tickets, reviews, surveys, call transcripts).

Setup:
    python search_feedback.py --setup

Query:
    python search_feedback.py "what are customers saying about login problems"
    python search_feedback.py "app crashes" --department Engineering
    python search_feedback.py "billing complaints" --source call
"""

import argparse
import sys
import time

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import AlreadyExists
from google.cloud import discoveryengine

# ─── Config ─────────────────────────────────────────────────────────

PROJECT_ID = "feedback-intel-demo"
LOCATION = "global"                  # Vertex AI Search uses global endpoint
COLLECTION = "default_collection"
DATA_STORE_ID = "feedback-store"
ENGINE_ID = "feedback-search-app"

# BigQuery source
# Vertex AI Search requires an '_id' field for custom schema.
# Our table uses 'id', so we created a view that renames it.
BQ_DATASET = "feedback"
BQ_TABLE = "enriched_feedback_search"   # View: renames id → _id

# Client options (global doesn't need a regional endpoint)
CLIENT_OPTIONS = (
    ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
    if LOCATION != "global"
    else None
)


# ═══════════════════════════════════════════════════════════════════
#  SETUP (run once)
# ═══════════════════════════════════════════════════════════════════

def create_data_store():
    """
    Create a Vertex AI Search data store for structured BigQuery data.

    The data store is a container that holds indexed documents.
    We use NO_CONTENT because our data is structured fields from BigQuery
    (not document content like PDFs). CONTENT_REQUIRED is for unstructured
    document stores — using it with structured data causes import failures.
    """
    client = discoveryengine.DataStoreServiceClient(client_options=CLIENT_OPTIONS)

    parent = client.collection_path(
        project=PROJECT_ID,
        location=LOCATION,
        collection=COLLECTION,
    )

    data_store = discoveryengine.DataStore(
        display_name="Customer Feedback",
        industry_vertical=discoveryengine.IndustryVertical.GENERIC,
        solution_types=[discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH],
        # NO_CONTENT for structured BigQuery data (fields ARE the data).
        # CONTENT_REQUIRED is for document stores (PDFs, HTML, etc.)
        content_config=discoveryengine.DataStore.ContentConfig.NO_CONTENT,
    )

    request = discoveryengine.CreateDataStoreRequest(
        parent=parent,
        data_store_id=DATA_STORE_ID,
        data_store=data_store,
    )

    print(f"Creating data store '{DATA_STORE_ID}'...")
    operation = client.create_data_store(request=request)
    result = operation.result()
    print(f"  Created: {result.name}")
    return result


def import_bigquery_data():
    """
    Import data from BigQuery enriched_feedback into the data store.

    Uses 'custom' data_schema — Vertex AI Search auto-detects fields
    from our BigQuery schema. The 'text' field becomes searchable content,
    'department', 'source', 'sentiment' become filterable facets.

    INCREMENTAL mode: upserts documents. Safe to re-run if we add new data.
    """
    client = discoveryengine.DocumentServiceClient(client_options=CLIENT_OPTIONS)

    parent = client.branch_path(
        project=PROJECT_ID,
        location=LOCATION,
        data_store=DATA_STORE_ID,
        branch="default_branch",
    )

    request = discoveryengine.ImportDocumentsRequest(
        parent=parent,
        bigquery_source=discoveryengine.BigQuerySource(
            project_id=PROJECT_ID,
            dataset_id=BQ_DATASET,
            table_id=BQ_TABLE,
            data_schema="custom",
        ),
        reconciliation_mode=discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
    )

    print(f"Importing data from {BQ_DATASET}.{BQ_TABLE}...")
    print(f"  (this may take a few minutes for indexing)")
    operation = client.import_documents(request=request)
    result = operation.result()

    # The result contains error samples if any docs failed
    if hasattr(result, 'error_samples') and result.error_samples:
        print(f"  WARNING: {len(result.error_samples)} documents had import errors:")
        for err in result.error_samples[:3]:
            print(f"    - {err.message}")
    else:
        print(f"  Import complete.")

    if hasattr(result, 'error_config') and result.error_config:
        print(f"  Error log: {result.error_config.gcs_prefix}")

    return result


def update_schema():
    """
    Update the data store schema to make fields filterable and searchable.

    By default, Vertex AI Search auto-detects the schema from BigQuery but
    doesn't know which fields should be filterable (for query filters) vs
    searchable (for full-text matching). We set annotations:

    - text:       searchable (main content for semantic search)
    - department:  indexable + retrievable (filter + return in results)
    - source:      indexable + retrievable
    - sentiment:   indexable + retrievable
    - tone:        indexable + retrievable
    - id:          retrievable
    - confidence:  retrievable

    'indexable' = can be filtered, faceted, boosted, or sorted
    'searchable' = can be reverse-indexed for text matching
    'retrievable' = can be returned in search results
    """
    client = discoveryengine.SchemaServiceClient(client_options=CLIENT_OPTIONS)

    schema_name = (
        f"projects/{PROJECT_ID}/locations/{LOCATION}"
        f"/collections/{COLLECTION}"
        f"/dataStores/{DATA_STORE_ID}"
        f"/schemas/default_schema"
    )

    schema = discoveryengine.Schema(
        name=schema_name,
        struct_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "searchable": True,
                    "retrievable": True,
                },
                "department": {
                    "type": "string",
                    "indexable": True,
                    "retrievable": True,
                    "dynamicFacetable": True,
                },
                "source": {
                    "type": "string",
                    "indexable": True,
                    "retrievable": True,
                    "dynamicFacetable": True,
                },
                "sentiment": {
                    "type": "string",
                    "indexable": True,
                    "retrievable": True,
                    "dynamicFacetable": True,
                },
                "tone": {
                    "type": "string",
                    "indexable": True,
                    "retrievable": True,
                },
                "id": {
                    "type": "string",
                    "retrievable": True,
                },
                "confidence": {
                    "type": "number",
                    "retrievable": True,
                },
                "customer_id": {
                    "type": "string",
                    "retrievable": True,
                },
                "model_version": {
                    "type": "string",
                    "retrievable": True,
                },
            },
        },
    )

    request = discoveryengine.UpdateSchemaRequest(schema=schema)

    print(f"Updating schema (marking fields as filterable/searchable)...")
    operation = client.update_schema(request=request)
    result = operation.result()
    print(f"  Schema updated. Re-indexing triggered (may take a few minutes).")
    return result


def create_search_engine():
    """
    Create a search engine (app) on top of the data store.

    The engine is the query interface — it handles embedding queries,
    matching against indexed documents, ranking results, and generating
    AI summaries.

    Enterprise tier: includes generative answers (AI summaries with citations).
    SEARCH_ADD_ON_LLM: enables the AI summary feature.
    """
    client = discoveryengine.EngineServiceClient(client_options=CLIENT_OPTIONS)

    parent = client.collection_path(
        project=PROJECT_ID,
        location=LOCATION,
        collection=COLLECTION,
    )

    engine = discoveryengine.Engine(
        display_name="Feedback Search",
        industry_vertical=discoveryengine.IndustryVertical.GENERIC,
        solution_type=discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH,
        search_engine_config=discoveryengine.Engine.SearchEngineConfig(
            search_tier=discoveryengine.SearchTier.SEARCH_TIER_ENTERPRISE,
            search_add_ons=[discoveryengine.SearchAddOn.SEARCH_ADD_ON_LLM],
        ),
        data_store_ids=[DATA_STORE_ID],
    )

    request = discoveryengine.CreateEngineRequest(
        parent=parent,
        engine=engine,
        engine_id=ENGINE_ID,
    )

    print(f"Creating search engine '{ENGINE_ID}'...")
    operation = client.create_engine(request=request)
    result = operation.result()
    print(f"  Created: {result.name}")
    return result


def run_setup():
    """Full setup: data store → import → search engine."""
    print("=" * 60)
    print("  VERTEX AI SEARCH — SETUP")
    print("=" * 60)
    print()

    # Step 1: Create data store
    try:
        create_data_store()
    except AlreadyExists:
        print(f"  Data store '{DATA_STORE_ID}' already exists — skipping.")
    print()

    # Step 2: Import BigQuery data
    import_bigquery_data()
    print()

    # Step 3: Update schema (mark fields as filterable/searchable)
    try:
        update_schema()
    except Exception as e:
        print(f"  Schema update warning: {e}")
        print(f"  (Schema may already be configured — continuing.)")
    print()

    # Step 4: Create search engine
    try:
        create_search_engine()
    except AlreadyExists:
        print(f"  Search engine '{ENGINE_ID}' already exists — skipping.")
    print()

    print("=" * 60)
    print("  Setup complete!")
    print("  Data store and search engine are being indexed.")
    print("  Indexing may take 5-10 minutes before queries work.")
    print("=" * 60)


# ═══════════════════════════════════════════════════════════════════
#  QUERY
# ═══════════════════════════════════════════════════════════════════

def search_feedback(query: str, department: str = None, source: str = None,
                    page_size: int = 10) -> dict:
    """
    Semantic search over all classified feedback.

    Args:
        query:      Natural language search query
        department: Filter by department (Engineering, Product, UX, Support)
        source:     Filter by source (ticket, review, survey, call)
        page_size:  Max results to return (default 10)

    Returns:
        dict with 'summary' (AI-generated text) and 'results' (list of matches)
    """
    client = discoveryengine.SearchServiceClient(client_options=CLIENT_OPTIONS)

    serving_config = (
        f"projects/{PROJECT_ID}/locations/{LOCATION}"
        f"/collections/{COLLECTION}"
        f"/engines/{ENGINE_ID}"
        f"/servingConfigs/default_config"
    )

    # Build filter string for structured fields
    # Vertex AI Search filter syntax: field: ANY("value")
    filters = []
    if department:
        filters.append(f'department: ANY("{department}")')
    if source:
        filters.append(f'source: ANY("{source}")')
    filter_str = " AND ".join(filters) if filters else None

    # Content search spec — controls what comes back
    content_search_spec = discoveryengine.SearchRequest.ContentSearchSpec(
        # Snippets: highlighted text excerpts from matching documents
        snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
            return_snippet=True,
        ),
        # Summary: AI-generated answer synthesized from top results
        summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
            summary_result_count=5,       # Summarize top 5 results
            include_citations=True,        # [1], [2] references in summary
            ignore_adversarial_query=True, # Skip prompt injection attempts
            ignore_non_summary_seeking_query=True,  # Skip queries that don't need summaries
            model_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelSpec(
                version="stable",
            ),
        ),
    )

    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=query,
        page_size=page_size,
        filter=filter_str,
        content_search_spec=content_search_spec,
        # Auto query expansion: "login" also matches "sign in", "authentication"
        query_expansion_spec=discoveryengine.SearchRequest.QueryExpansionSpec(
            condition=discoveryengine.SearchRequest.QueryExpansionSpec.Condition.AUTO,
        ),
        # Auto spell correction
        spell_correction_spec=discoveryengine.SearchRequest.SpellCorrectionSpec(
            mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO,
        ),
    )

    response = client.search(request)

    # Parse results into clean dict
    results = []
    for result in response.results:
        doc_data = dict(result.document.struct_data)

        results.append({
            "id": doc_data.get("id", ""),
            "text": doc_data.get("text", "")[:300],
            "source": doc_data.get("source", ""),
            "department": doc_data.get("department", ""),
            "sentiment": doc_data.get("sentiment", ""),
            "tone": doc_data.get("tone", ""),
            "confidence": doc_data.get("confidence", 0),
        })

    # Extract summary
    summary_text = ""
    if hasattr(response, 'summary') and response.summary:
        summary_text = response.summary.summary_text

    return {
        "query": query,
        "filters": {"department": department, "source": source},
        "summary": summary_text,
        "total_results": len(results),
        "results": results,
    }


def print_search_results(result: dict):
    """Pretty-print search results."""
    print(f"\n{'=' * 70}")
    print(f"  SEARCH: \"{result['query']}\"")

    active_filters = {k: v for k, v in result["filters"].items() if v}
    if active_filters:
        print(f"  Filters: {active_filters}")

    print(f"{'=' * 70}")

    # AI Summary
    if result["summary"]:
        print(f"\n  AI SUMMARY:")
        print(f"  {'─' * 50}")
        # Wrap summary text
        summary = result["summary"]
        for line in [summary[i:i+65] for i in range(0, len(summary), 65)]:
            print(f"  {line}")

    # Individual results
    print(f"\n  RESULTS ({result['total_results']} matches)")
    print(f"  {'─' * 50}")

    for i, r in enumerate(result["results"], 1):
        sentiment_icon = {"positive": "+", "negative": "-", "neutral": "~"}.get(r["sentiment"], "?")
        print(f"\n  [{i}] [{sentiment_icon}] {r['department']} / {r['source']}")
        # Show first 150 chars of text
        text_preview = r["text"][:150].replace("\n", " ")
        print(f"      {text_preview}...")

    if not result["results"]:
        print(f"  No results found.")

    print()


# ─── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Vertex AI Search — semantic search over customer feedback"
    )
    parser.add_argument("query", nargs="?", help="Search query (natural language)")
    parser.add_argument("--setup", action="store_true",
                        help="Run one-time setup (create data store + engine)")
    parser.add_argument("--department", type=str, default=None,
                        help="Filter by department (Engineering, Product, UX, Support)")
    parser.add_argument("--source", type=str, default=None,
                        help="Filter by source (ticket, review, survey, call)")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max results (default 10)")
    args = parser.parse_args()

    if args.setup:
        run_setup()
        return

    if not args.query:
        parser.print_help()
        print("\nExamples:")
        print('  python search_feedback.py "app crashes on mobile"')
        print('  python search_feedback.py "billing issues" --source call')
        print('  python search_feedback.py "slow performance" --department Engineering')
        return

    result = search_feedback(
        query=args.query,
        department=args.department,
        source=args.source,
        page_size=args.limit,
    )
    print_search_results(result)


if __name__ == "__main__":
    main()
