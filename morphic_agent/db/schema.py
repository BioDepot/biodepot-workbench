"""Canonical Workbench kernel schema used by migrations and SQLite tests."""

WORKBENCH_KERNEL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_threads (
    thread_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL,
    goal TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES agent_threads(thread_id)
);
CREATE TABLE IF NOT EXISTS planner_states (
    thread_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES agent_threads(thread_id)
);
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL UNIQUE,
    owner_user TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    origin_session_id TEXT,
    last_session_id TEXT,
    parent_conversation_id TEXT,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    FOREIGN KEY(thread_id) REFERENCES agent_threads(thread_id),
    FOREIGN KEY(parent_conversation_id) REFERENCES conversations(conversation_id)
);
CREATE TABLE IF NOT EXISTS source_files (
    source_file_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL,
    extracted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS modules (
    module_id TEXT PRIMARY KEY,
    current_version_id TEXT NOT NULL,
    title TEXT NOT NULL,
    confidence_tier TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS module_versions (
    version_id TEXT PRIMARY KEY,
    module_id TEXT NOT NULL,
    version TEXT NOT NULL,
    title TEXT NOT NULL,
    runtime_kind TEXT,
    contract_json TEXT NOT NULL,
    confidence_tier TEXT,
    provenance_json TEXT NOT NULL,
    source_file_id TEXT,
    source_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS module_inputs (
    module_version_id TEXT NOT NULL,
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    required INTEGER NOT NULL,
    constraints_json TEXT NOT NULL,
    PRIMARY KEY(module_version_id, name)
);
CREATE TABLE IF NOT EXISTS module_outputs (
    module_version_id TEXT NOT NULL,
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    optional INTEGER NOT NULL,
    constraints_json TEXT NOT NULL,
    PRIMARY KEY(module_version_id, name)
);
CREATE TABLE IF NOT EXISTS artifact_contracts (
    artifact_type TEXT PRIMARY KEY,
    schema_json TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    version TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parameter_schemas (
    schema_id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS compatibility_edges (
    edge_id TEXT PRIMARY KEY,
    source_module_id TEXT NOT NULL,
    source_output TEXT NOT NULL,
    target_module_id TEXT NOT NULL,
    target_input TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    confidence_tier TEXT,
    evidence_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subgraph_versions (
    version_id TEXT PRIMARY KEY,
    subgraph_id TEXT NOT NULL,
    version TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    input_signature_json TEXT NOT NULL,
    output_signature_json TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    confidence_tier TEXT,
    lifecycle_state TEXT NOT NULL,
    canonical_graph_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_graphs (
    graph_id TEXT PRIMARY KEY,
    current_version_id TEXT NOT NULL,
    title TEXT NOT NULL,
    suite TEXT,
    recipe_family TEXT,
    assay_profile TEXT,
    lifecycle_state TEXT NOT NULL,
    materialization_status TEXT,
    confidence_tier TEXT,
    runnable INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_graph_versions (
    version_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    version TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    canonical_graph_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    suite TEXT,
    recipe_family TEXT,
    assay_profile TEXT,
    lifecycle_state TEXT NOT NULL,
    materialization_status TEXT,
    confidence_tier TEXT,
    runnable INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    runtime_json TEXT NOT NULL,
    execution_json TEXT NOT NULL,
    search_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(graph_id, canonical_graph_hash)
);
CREATE TABLE IF NOT EXISTS workflow_graph_nodes (
    version_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    module_id TEXT,
    label TEXT,
    kind TEXT,
    node_json TEXT NOT NULL,
    PRIMARY KEY(version_id, node_id)
);
CREATE TABLE IF NOT EXISTS workflow_graph_edges (
    version_id TEXT NOT NULL,
    edge_index INTEGER NOT NULL,
    source TEXT,
    target TEXT,
    edge_type TEXT,
    artifact_type TEXT,
    edge_json TEXT NOT NULL,
    PRIMARY KEY(version_id, edge_index)
);
CREATE TABLE IF NOT EXISTS workflow_graph_inputs (
    version_id TEXT NOT NULL,
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    required INTEGER NOT NULL,
    input_json TEXT NOT NULL,
    PRIMARY KEY(version_id, name, artifact_type)
);
CREATE TABLE IF NOT EXISTS workflow_graph_outputs (
    version_id TEXT NOT NULL,
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    output_json TEXT NOT NULL,
    PRIMARY KEY(version_id, name, artifact_type)
);
CREATE TABLE IF NOT EXISTS workflow_graph_capabilities (
    version_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    PRIMARY KEY(version_id, capability)
);
CREATE TABLE IF NOT EXISTS workflow_graph_modalities (
    version_id TEXT NOT NULL,
    modality TEXT NOT NULL,
    PRIMARY KEY(version_id, modality)
);
CREATE TABLE IF NOT EXISTS workflow_graph_execution_locations (
    version_id TEXT NOT NULL,
    execution_location TEXT NOT NULL,
    PRIMARY KEY(version_id, execution_location)
);
CREATE TABLE IF NOT EXISTS graph_projection_vertices (
    vertex_id TEXT NOT NULL,
    projection_version TEXT NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    properties_json TEXT NOT NULL,
    PRIMARY KEY(vertex_id, projection_version)
);
CREATE TABLE IF NOT EXISTS graph_projection_edges (
    edge_id TEXT NOT NULL,
    projection_version TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    label TEXT NOT NULL,
    artifact_type TEXT,
    properties_json TEXT NOT NULL,
    PRIMARY KEY(edge_id, projection_version)
);
CREATE TABLE IF NOT EXISTS graph_projection_manifests (
    projection_version TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    adapter TEXT NOT NULL,
    vertex_count INTEGER NOT NULL,
    edge_count INTEGER NOT NULL,
    manifest_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generated_bundles (
    bundle_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    bundle_path TEXT NOT NULL,
    bundle_hash TEXT,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_review_approvals (
    token TEXT PRIMARY KEY,
    approval_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workbench_runs (
    run_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step TEXT NOT NULL,
    execution_location TEXT,
    bundle_id TEXT,
    bundle_path TEXT,
    preflight_id TEXT,
    execution_id TEXT,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_run_links (
    conversation_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY(conversation_id, run_id),
    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id),
    FOREIGN KEY(run_id) REFERENCES workbench_runs(run_id)
);
CREATE TABLE IF NOT EXISTS preflight_runs (
    preflight_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_runs (
    execution_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    params_hash TEXT,
    result_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verified_recipes (
    verified_recipe_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    execution_manifest_json TEXT NOT NULL,
    canonical_graph_hash TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_validation_records (
    validation_id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    canonical_graph_hash TEXT,
    source_manifest_hash TEXT,
    validation_kind TEXT NOT NULL,
    comparator_kind TEXT NOT NULL,
    executor TEXT,
    profile TEXT,
    fixture_id TEXT,
    status TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_versions_graph_id ON workflow_graph_versions(graph_id);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_versions_hash ON workflow_graph_versions(canonical_graph_hash);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_inputs_artifact ON workflow_graph_inputs(artifact_type);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_outputs_artifact ON workflow_graph_outputs(artifact_type);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_capabilities_capability ON workflow_graph_capabilities(capability);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_modalities_modality ON workflow_graph_modalities(modality);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_execution_locations_location ON workflow_graph_execution_locations(execution_location);
CREATE INDEX IF NOT EXISTS idx_workbench_runs_graph_id ON workbench_runs(graph_id);
CREATE INDEX IF NOT EXISTS idx_conversations_owner_updated ON conversations(owner_user, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_conversation_run_links_run ON conversation_run_links(run_id);
CREATE INDEX IF NOT EXISTS idx_preflight_runs_graph_id ON preflight_runs(graph_id);
CREATE INDEX IF NOT EXISTS idx_execution_runs_graph_id ON execution_runs(graph_id);
CREATE INDEX IF NOT EXISTS idx_workflow_validation_records_graph_id ON workflow_validation_records(graph_id);
CREATE INDEX IF NOT EXISTS idx_workflow_validation_records_status ON workflow_validation_records(status);
CREATE INDEX IF NOT EXISTS idx_workflow_validation_records_facets ON workflow_validation_records(validation_kind, comparator_kind, executor, fixture_id);
"""


EXPECTED_WORKBENCH_TABLES = {
    "agent_threads",
    "agent_turns",
    "planner_states",
    "conversations",
    "source_files",
    "modules",
    "module_versions",
    "module_inputs",
    "module_outputs",
    "artifact_contracts",
    "parameter_schemas",
    "compatibility_edges",
    "subgraph_versions",
    "workflow_graphs",
    "workflow_graph_versions",
    "workflow_graph_nodes",
    "workflow_graph_edges",
    "workflow_graph_inputs",
    "workflow_graph_outputs",
    "workflow_graph_capabilities",
    "workflow_graph_modalities",
    "workflow_graph_execution_locations",
    "graph_projection_vertices",
    "graph_projection_edges",
    "graph_projection_manifests",
    "generated_bundles",
    "execution_review_approvals",
    "workbench_runs",
    "conversation_run_links",
    "preflight_runs",
    "execution_runs",
    "verified_recipes",
    "workflow_validation_records",
}
