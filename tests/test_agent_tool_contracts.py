"""Tool contract tests ported from prototype workbench behavior."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from starlette.testclient import TestClient

from morphic_agent.api.app import create_app
from morphic_agent.bundle.star_workflow import (
    assess_star_render_readiness,
    build_star_argv_preview,
    build_star_bulk_pe_workflow_params,
)
from morphic_agent.planner.intent import (
    assay_catalog_modules,
    downstream_catalog_modules,
    module_matches_for_request,
    planning_state_for_rnaseq,
    requests_assay_catalog,
    requests_visualization_catalog,
    requests_volcano_plot,
    visualization_catalog_modules,
)
from morphic_agent.registry.catalog import ModuleCatalog
from morphic_agent.tools.bundle import BundleTools
from morphic_agent.tools.graph import GraphTools
from morphic_agent.tools.registry import RegistryTools


def _client() -> TestClient:
    db = tempfile.mktemp(suffix=".sqlite3")
    return TestClient(create_app(db_path=db))


def test_list_modules_returns_catalog_entries():
    response = RegistryTools().list_modules()
    module_ids = {item["module_id"] for item in response.payload["modules"]}
    assert "star_bulk_pe_counts" in module_ids
    assert "deseq2_differential_expression" in module_ids
    assert "volcano_plot" in module_ids


def test_get_module_contract_includes_evidence_and_confidence():
    response = RegistryTools().get_module_contract("star_bulk_pe_counts")
    assert response.status == "ok"
    module = response.payload["module"]
    assert module["confidence_tier"] == "curated_profile"
    assert module["evidence"]


def test_draft_graph_bulk_deg_has_nodes_and_blocker():
    response = GraphTools().draft_graph("Create a bulk paired-end RNA-seq DEG analysis with DESeq2", include_launchpad=False)
    assert response.status == "graph_draft"
    graph = response.payload["workflow_graph"]
    assert graph["graph_id"] == "bulk_pe_deseq2_v0"
    assert [node["module_id"] for node in graph["nodes"]] == ["star_bulk_pe_counts", "deseq2_differential_expression"]
    assert graph["materialization_status"] == "runnable_bundle"


def test_validate_parameters_reports_missing_fields():
    response = BundleTools().validate_parameters("bulk_pe_deseq2_v0", {"design": "~ condition"})
    assert response.status == "invalid"
    assert set(response.payload["missing_required_inputs"]) >= {"reads", "genome_dir", "genome_fasta", "gtf", "coldata"}


def test_render_bundle_materializes_review_bundle_without_executable_command(tmp_path):
    genome_dir = tmp_path / "star_index"
    genome_dir.mkdir()
    (genome_dir / "SA").write_text("fixture\n")
    params = {
        "reads": [{"sample": "A", "r1": str(tmp_path / "r1.fastq.gz"), "r2": str(tmp_path / "r2.fastq.gz")}],
        "genome_dir": str(genome_dir),
        "genome_fasta": str(tmp_path / "genome.fa"),
        "gtf": str(tmp_path / "genes.gtf"),
        "coldata": str(tmp_path / "coldata.tsv"),
        "design": "~ condition",
    }
    for path in (tmp_path / "r1.fastq.gz", tmp_path / "r2.fastq.gz", tmp_path / "genome.fa", tmp_path / "genes.gtf", tmp_path / "coldata.tsv"):
        path.write_text("fixture\n")
    response = BundleTools().render_bundle("bulk_pe_deseq2_v0", params, out_root=tmp_path)
    assert response.status == "materialized"
    bundle = Path(response.payload["bundle_path"])
    assert (bundle / "helpers" / "run_deseq2.R").is_file()
    if response.payload.get("execution_readiness") == "executable_ready":
        assert response.payload["headless"]["script"]
    else:
        assert response.payload["headless"]["script"] is None
        assert response.payload.get("run_blocker")


def test_star_workflow_params_use_suite_schema_thread_key_and_safe_raw_preview(tmp_path):
    genome_dir = tmp_path / "star_index"
    genome_dir.mkdir()
    r1 = tmp_path / "A_R1.fastq.gz"
    r2 = tmp_path / "A_R2.fastq.gz"
    r1.write_text("fixture\n")
    r2.write_text("fixture\n")
    params = {
        "reads": [{"sample": "A", "r1": str(r1), "r2": str(r2)}],
        "genome_dir": str(genome_dir),
        "out_file_name_prefix": str(tmp_path / "star_out") + "/",
        "threads": 4,
        "bam_sort": "sorted",
    }

    workflow_params = build_star_bulk_pe_workflow_params(params)
    argv_preview = build_star_argv_preview(workflow_params)

    assert workflow_params["run_thread_n"] == 4
    assert "threads" not in workflow_params
    assert "--runThreadN" in argv_preview
    assert argv_preview[argv_preview.index("--runThreadN") + 1] == "4"
    assert "--batchMode" not in argv_preview
    assert "--outFileNamePrefixAuto" not in argv_preview


def test_star_suite_render_failure_is_not_treated_as_executable_render(tmp_path):
    genome_dir = tmp_path / "star_index"
    genome_dir.mkdir()
    r1 = tmp_path / "A_R1.fastq.gz"
    r2 = tmp_path / "A_R2.fastq.gz"
    r1.write_text("fixture\n")
    r2.write_text("fixture\n")
    params = {
        "reads": [{"sample": "A", "r1": str(r1), "r2": str(r2)}],
        "genome_dir": str(genome_dir),
        "out_file_name_prefix": str(tmp_path / "star_out") + "/",
        "threads": 4,
        "bam_sort": "sorted",
    }

    readiness = assess_star_render_readiness(params, star_root=tmp_path / "missing-suite", check_paths=True)

    assert readiness["preview_ok"] is True
    assert readiness["render_mode"] == "raw_preview_only"
    assert readiness["render_ok"] is False
    assert readiness["suite_render_ok"] is False
    assert "workflows module not found" in readiness["suite_error"]


def test_plots_graph_render_is_blocked():
    from morphic_agent.graph.drafts import build_bulk_deseq_graph
    from morphic_agent.registry.catalog import ModuleCatalog

    graph = build_bulk_deseq_graph(ModuleCatalog(), include_plots=True)
    response = BundleTools().render_bundle(
        graph["graph_id"],
        {
            "reads": [{"sample": "A", "r1": "/tmp/r1.fastq.gz", "r2": "/tmp/r2.fastq.gz"}],
            "genome_dir": "/tmp/star_index",
            "genome_fasta": "/tmp/genome.fa",
            "gtf": "/tmp/genes.gtf",
            "coldata": "/tmp/coldata.tsv",
            "design": "~ condition",
        },
    )
    assert response.status == "blocked"
    assert "volcano" in response.summary.lower() or "plot" in response.summary.lower()
    assert response.payload["headless"]["script"] is None


def test_invalid_paired_reads_fail_validation():
    response = BundleTools().validate_parameters(
        "bulk_pe_deseq2_v0",
        {
            "reads": [{"sample": "A", "r1": "/tmp/r1.fastq.gz"}],
            "genome_fasta": "/tmp/genome.fa",
            "gtf": "/tmp/genes.gtf",
            "coldata": "/tmp/coldata.tsv",
            "design": "~ condition",
        },
    )
    assert response.status == "invalid"
    assert "reads" in response.payload["field_errors"]


def test_materialize_draft_bundle_run_sh_fails_without_star(tmp_path, monkeypatch):
    monkeypatch.setenv("STAR_SUITE_ROOT", str(tmp_path / "missing-star-suite"))
    tools = BundleTools()
    genome_dir = tmp_path / "star_index"
    genome_dir.mkdir()
    (genome_dir / "SA").write_text("fixture\n")
    params = {
        "reads": [{"sample": "A", "r1": str(tmp_path / "r1.fastq.gz"), "r2": str(tmp_path / "r2.fastq.gz")}],
        "genome_dir": str(genome_dir),
        "genome_fasta": str(tmp_path / "genome.fa"),
        "gtf": str(tmp_path / "genes.gtf"),
        "coldata": str(tmp_path / "coldata.tsv"),
        "design": "~ condition",
    }
    for path in (tmp_path / "r1.fastq.gz", tmp_path / "r2.fastq.gz", tmp_path / "genome.fa", tmp_path / "genes.gtf", tmp_path / "coldata.tsv"):
        path.write_text("fixture\n")
    bundle = tools.materialize_draft_bundle("bulk_pe_deseq2_v0", params, tmp_path / "bundle")
    import subprocess

    proc = subprocess.run(["bash", str(bundle / "run.sh")], cwd=str(bundle), capture_output=True, text=True)
    assert proc.returncode != 0
    preflight = json.loads((bundle / "manifests" / "preflight_result.json").read_text())
    assert preflight["executable_ready"] is False
    assert any("STAR" in str(check.get("check", "")) for check in preflight["checks"])


def test_materialize_draft_bundle_writes_editable_helper_files(tmp_path):
    tools = BundleTools()
    genome_dir = tmp_path / "star_index"
    genome_dir.mkdir()
    (genome_dir / "SA").write_text("fixture\n")
    params = {
        "reads": [{"sample": "A", "r1": str(tmp_path / "r1.fastq.gz"), "r2": str(tmp_path / "r2.fastq.gz")}],
        "genome_dir": str(genome_dir),
        "genome_fasta": str(tmp_path / "genome.fa"),
        "gtf": str(tmp_path / "genes.gtf"),
        "coldata": str(tmp_path / "coldata.tsv"),
        "design": "~ condition",
    }
    for path in (tmp_path / "r1.fastq.gz", tmp_path / "r2.fastq.gz", tmp_path / "genome.fa", tmp_path / "genes.gtf", tmp_path / "coldata.tsv"):
        path.write_text("fixture\n")
    bundle = tools.materialize_draft_bundle("bulk_pe_deseq2_v0", params, tmp_path)
    assert (bundle / "helpers" / "star_workflow.py").is_file()
    assert (bundle / "helpers" / "preflight.py").is_file()
    assert (bundle / "workflow_graph.json").is_file()
    assert (bundle / "run.sh").is_file()
    assert "preflight.py" in (bundle / "run.sh").read_text()


def test_module_matcher_recognizes_degs_and_volcano_plot():
    catalog = ModuleCatalog()
    matches = module_matches_for_request("Add DEGs and volcano plots after bulk RNA-seq", catalog)
    module_ids = {item["module_id"] for item in matches}
    assert "deseq2_differential_expression" in module_ids
    assert "volcano_plot" in module_ids
    assert requests_volcano_plot("Add volcano plots after DEGs")


def test_downstream_catalog_lists_volcano_plot():
    catalog = ModuleCatalog()
    module_ids = {module["module_id"] for module in downstream_catalog_modules(catalog)}
    assert "volcano_plot" in module_ids
    assert "deseq2_differential_expression" in module_ids


def test_assay_catalog_intent_lists_relevant_modules():
    catalog = ModuleCatalog()
    module_ids = {module["module_id"] for module in assay_catalog_modules(catalog)}
    assert requests_assay_catalog("Tell me what assays are available. I have paired end fastq files")
    assert "star_bulk_pe_counts" in module_ids
    assert "mex_to_anndata" in module_ids


def test_visualization_catalog_lists_plot_modules():
    catalog = ModuleCatalog()
    module_ids = {module["module_id"] for module in visualization_catalog_modules(catalog)}
    assert requests_visualization_catalog("What other visualizations are available?")
    assert "volcano_plot" in module_ids
    assert "heatmap_plot" in module_ids
    assert "embedding_scatter_plot" in module_ids


def test_agent_api_graph_draft_endpoint_matches_tool_contract():
    client = _client()
    response = client.post(
        "/api/graphs/draft",
        json={"goal": "Create a bulk paired-end RNA-seq DEG analysis with DESeq2", "include_launchpad": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "graph_draft"
    assert body["graph_id"] == "bulk_pe_deseq2_v0"


def test_agent_api_suites_bootstrap_and_healthz_alias():
    client = _client()
    index = client.get("/")
    assert index.status_code == 200
    assert "BioDepot Workbench" in index.text
    assert 'requestJson("/v1/agent/chat"' in index.text
    assert "Review Plan" in index.text
    assert "Parameter Form" in index.text
    assert "Details" in index.text
    assert "planValidation" in index.text
    assert "function validationLabel" in index.text
    assert "Walkthroughs" in index.text
    assert "Describe the analysis you want to plan, review, and run on the Workbench server." in index.text
    assert "Compose bulk paired-end RNA-seq with DEGs and volcano plots" not in index.text
    assert "Load Quick Demo" in index.text
    assert "STAR MVP Smoke" not in index.text
    assert "starMvpBtn" not in index.text
    assert "planStarMvp" not in index.text
    assert "/api/star-mvp/plan" not in index.text
    assert "Execute Smoke" not in index.text
    assert "executeBtn" not in index.text
    assert "Run Preflight" in index.text
    assert "Run on Workbench Server" in index.text
    assert "Production execution runs on the selected API-managed location" in index.text
    assert "Run Directory" in index.text
    assert "Generate Run Directory" in index.text
    assert "Execution Locale For Generated Run Directory" in index.text
    assert "scriptExecutionLocationLocalBtn" in index.text
    assert "scriptExecutionLocationServerBtn" in index.text
    assert "scriptExecutionLocationRemoteSshBtn" in index.text
    assert "Download Helper Sources" in index.text
    assert "Clear Workbench" in index.text
    assert "clearWorkbenchBtn" in index.text
    assert "function clearWorkbenchCanvas" in index.text
    assert "End Session" in index.text
    assert "THINKING_PHRASES" in index.text
    assert "Reticulating" in index.text
    assert "Run Demo/Smoke" not in index.text
    assert "preflightBtn" in index.text
    assert "executionDiagnosticBtn" in index.text
    assert "Diagnose Location" in index.text
    assert "diagnosticModal" in index.text
    assert "localRunBtn" in index.text
    assert "Run Locally" in index.text
    assert "Remote SSH" in index.text
    assert "executionReviewRemoteHost" in index.text
    assert "executionReviewRemoteWorkdir" in index.text
    assert "executionReviewRemotePathOverrides" in index.text
    assert "remote_path_overrides" in index.text
    assert "localRunModal" in index.text
    assert "serverRunModal" in index.text
    assert "Run on Workbench Server Now" in index.text
    assert "Run on Remote SSH Now" in index.text
    assert "openServerRunOffer" in index.text
    assert "run.docker.sh" in index.text
    assert "run.apptainer.sh" in index.text
    assert "browser cannot automatically start the final script" in index.text
    assert "browser cannot start run.sh, Docker, or Apptainer" in index.text
    assert "/execution-diagnostic" in index.text
    assert "executionReviewModal" in index.text
    assert "executionReviewApproveBtn" in index.text
    assert "Approve & Generate Run Directory" in index.text
    assert "renderBundleAfterApprovedReview" in index.text
    assert "Selected locale:" in index.text
    assert "approved: true" in index.text
    assert "verified_paths: true" in index.text
    assert "executionReviewApproved" not in index.text
    assert "executionReviewPaths" not in index.text
    assert "/execution-review" in index.text
    assert "runProductionBtn" in index.text
    assert "runGateHint" in index.text
    assert "executionLog" in index.text
    assert "artifactManifest" in index.text
    assert "panelWorkspace" in index.text
    assert "Expanded Panels" in index.text
    assert 'data-expand-id="script"' in index.text
    assert "Open Window" in index.text
    assert "initPanelExpansion" in index.text
    assert "/execute-production/stream" in index.text
    assert "executeSmokeBtn" not in index.text
    assert "/api/star-mvp/preflight" in index.text
    assert "/execute-production" in index.text
    assert "function runProduction" in index.text
    assert "/api/star-mvp/execute" not in index.text
    assert "quickDemoBtn" in index.text
    assert "walkthroughSelect" in index.text
    assert "walkthroughActionMode" in index.text
    assert "Starting prompt only" in index.text
    assert "Prompt guidance only" in index.text
    assert "walkthroughRequireLlm" in index.text
    assert "Require LLM input" in index.text
    assert "walkthroughModeStatus" in index.text
    assert ">Start</button>" in index.text
    assert "modelWalkthroughStatus" in index.text
    assert "/api/model/status?probe=1" in index.text
    assert "require_model" in index.text
    assert "Model-backed walkthroughs are disabled" in index.text
    assert "Start Here: quick run + orientation" in index.text
    assert "Bulk RNA-seq: simple to extended" in index.text
    assert "Single-cell and perturbation" in index.text
    assert "Chromap chromatin workflows" in index.text
    assert "Multiomics suite surfaces" in index.text
    assert "nf-core workflow wrappers" in index.text
    assert "Full load" not in index.text
    assert "Complete walkthrough" not in index.text
    assert "function detectAppBasePath" in index.text
    assert "function workbenchHandoffFromLocation" in index.text
    assert "function applyWorkbenchHandoffFromLocation" in index.text
    assert "function clearWorkbenchHandoffFromLocation" in index.text
    assert "window.location.search" in index.text
    assert 'searchParams.get("workbench")' in index.text
    assert 'hashParams.get("workbench")' in index.text
    assert "Server-provided fixes" in index.text
    assert '"/workbench-dev"' in index.text
    assert '"/workbench-test"' in index.text
    assert '"/tutorials-test"' in index.text
    assert index.text.count("<option value=") == 34
    for walkthrough_id in (
        "00_assay_catalog",
        "01_trimodal_quick_demo",
        "02_bulk_pe_deseq2",
        "03_bulk_plots",
        "04_slam_seq",
        "05_post_mex",
        "06_example_perturb_visualization",
        "07_chromap_atac",
        "08_chromap_chip",
        "09_chromap_hic",
        "10_multiomics",
        "11_visualization_catalog",
        "12_chromap_evidence_compose",
        "13_chromap_hic_pairs_compose",
        "14_multiomics_mudata_builder_compose",
        "15_multiomics_trimodal_report_compose",
        "16_nfcore_da_bulk_counts",
        "17_nfcore_da_chromap_peak_counts",
        "18_nfcore_atacseq_chromap_handoff",
    ):
        assert f'value="{walkthrough_id}"' in index.text
    assert "loadCompositionWalkthrough" in index.text
    assert "loadNfcoreWalkthrough" in index.text
    assert "/api/nfcore/harvest" in index.text
    assert "runLlmTurn" in index.text
    assert "options.clearGoal" in index.text
    assert 'switchPane(loadedGraph ? "plan" : "chat")' in index.text
    assert "sent_to_llm" in index.text
    assert "seedWalkthroughPrompt" in index.text
    assert "starting_prompt_only" in index.text
    assert "prompt_guidance_only" in index.text
    assert "direct_workbench_load" in index.text
    assert "local_registry_composition" in index.text
    assert "local_nfcore_schema_harvest" in index.text
    assert "walkthrough_provenance" in index.text
    assert "model_used: false" in index.text
    assert "require_llm_input" in index.text
    assert "preserveGraph" in index.text
    assert "multiomics_trimodal_report" in index.text
    assert "data/demo_trimodal_small.h5mu" in index.text
    assert "Raw data and helper sources" in index.text
    assert "Workflow Graph JSON" in index.text
    assert '<div class="panel-head">Workflow Graph</div>' not in index.text
    assert '<div class="panel-head">Raw</div>' not in index.text
    assert 'if (payload.workflow_graph) switchPane("params")' not in index.text
    assert 'switchPane("chat");' in index.text
    assert "function renderMarkdown" in index.text
    assert "node.innerHTML = renderMarkdown(messageText)" in index.text
    assert "thinking-copy" in index.text

    assert "addThinkingMessage()" in index.text
    assert "function blockedScript" in index.text
    assert '$("scriptEditor").value = state.script || blockedScript(payload);' in index.text
    assert '$("scriptEditor").value = JSON.stringify(payload.recipe_draft' not in index.text
    assert 'state.recipeDraft = payload.recipe_draft || payload;' in index.text
    assert "Conversation Log" in index.text
    assert "loadThreadLogBtn" in index.text
    assert "/api/threads/" in index.text
    assert "log_interaction: true" in index.text
    assert "Server File Browser" in index.text
    assert "fileBrowserModal" in index.text
    assert "/api/files/browse" in index.text
    assert "Browse Server" in index.text
    assert "Choose Local File" in index.text
    assert "Choose Local Folder" in index.text
    assert "Insert Server Path" in index.text
    assert "Insert Local Folder" in index.text
    assert "function paramGroups" in index.text
    assert "function createParamInput" in index.text
    assert 'document.createElement("select")' in index.text
    assert 'input.type = "checkbox"' in index.text
    assert 'localDirectoryPicker.webkitdirectory = true' in index.text
    assert 'details.className = group.advanced ? "param-group param-group-advanced" : "param-group"' in index.text
    assert "Samplesheet input" in index.text
    assert "Server paths must be readable from the Workbench server" in index.text

    healthz = client.get("/healthz")
    assert healthz.status_code == 200
    assert healthz.json()["service"] == "morphic-agent"

    suites = client.get("/api/suites")
    assert suites.status_code == 200
    body = suites.json()
    assert body["status"] == "ok"
    assert body["suites"][0]["id"] == "star"
    assert body["suites"][0]["default_workflow"] == "star_bulk_pe_batch"


def test_model_status_and_required_chat_fail_when_model_is_unavailable(monkeypatch):
    for key in (
        "MODEL_BASE_URL",
        "MODEL_API_KEY",
        "MODEL_NAME",
        "MORPHIC_AGENT_MODEL_BASE_URL",
        "MORPHIC_AGENT_MODEL_API_KEY",
        "MORPHIC_AGENT_MODEL_NAME",
        "MORPHIC_AGENT_ENABLE_CONFIG_LLM",
        "MORPHIC_AGENT_LLM_PROFILE",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MORPHIC_AGENT_DISABLE_CONFIG_LLM", "1")

    client = _client()

    status = client.get("/api/model/status?probe=1")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["status"] == "unavailable"
    assert status_body["available"] is False

    response = client.post(
        "/v1/agent/chat",
        json={
            "goal": "Can the workbench help with ATAC-seq or single-cell ATAC using Chromap?",
            "require_model": True,
        },
    )
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "model_unavailable"
    assert "requires the configured model" in body["assistant_message"]
    assert body["model_status"]["available"] is False


def test_agent_api_file_browser_is_limited_to_configured_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("MORPHIC_AGENT_FILE_BROWSER_ROOTS", str(tmp_path))
    data_dir = tmp_path / "inputs"
    data_dir.mkdir()
    sample = data_dir / "sample.fastq.gz"
    sample.write_text("fixture\n", encoding="utf-8")
    hidden = data_dir / ".secret"
    hidden.write_text("hidden\n", encoding="utf-8")
    outside_link = data_dir / "outside"
    outside_link.symlink_to("/etc")

    client = _client()
    roots = client.get("/api/files/browse")
    assert roots.status_code == 200
    assert any(root["path"] == str(tmp_path) for root in roots.json()["roots"])

    listing = client.get("/api/files/browse", params={"path": str(data_dir)})
    assert listing.status_code == 200
    body = listing.json()
    assert body["path"] == str(data_dir)
    names = {entry["name"] for entry in body["entries"]}
    assert "sample.fastq.gz" in names
    assert ".secret" not in names
    assert "outside" not in names

    selected_file = client.get("/api/files/browse", params={"path": str(sample)})
    assert selected_file.status_code == 200
    assert selected_file.json()["selected_path"] == str(sample)

    hidden_blocked = client.get("/api/files/browse", params={"path": str(hidden)})
    assert hidden_blocked.status_code == 403
    assert hidden_blocked.json()["error"] == "hidden paths are not browsable"

    blocked = client.get("/api/files/browse", params={"path": "/etc"})
    assert blocked.status_code == 403
    assert blocked.json()["status"] == "blocked"


def test_agent_api_graph_draft_can_log_prompt_response_turns():
    client = _client()
    draft = client.post(
        "/api/graphs/draft",
        json={
            "goal": "QC report for the trimodal MuData at data/demo_trimodal_small.h5mu",
            "include_launchpad": False,
            "log_interaction": True,
        },
    )
    assert draft.status_code == 200
    draft_body = draft.json()
    thread_id = draft_body["thread_id"]
    assert draft_body["graph_id"] == "trimodal_qc_report_v0"

    log = client.get(f"/api/threads/{thread_id}/turns?limit=10")
    assert log.status_code == 200
    turns = log.json()["turns"]
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert turns[0]["goal"] == "QC report for the trimodal MuData at data/demo_trimodal_small.h5mu"
    assert turns[1]["payload"]["graph_id"] == "trimodal_qc_report_v0"
    assert turns[1]["payload"]["surface"] == "graph_draft"
    assert "trimodal MuData" in turns[1]["payload"]["assistant_message"]
    assert "MVP DEG composability" not in turns[1]["payload"]["assistant_message"]


def test_agent_api_projection_and_verified_recipe_endpoints():
    client = _client()
    projection = client.post("/api/graphs/projection/rebuild", json={"projection_version": "api-test-v0"})
    assert projection.status_code == 200
    assert projection.json()["status"] == "ok"
    assert projection.json()["graph_index"] == "arcadedb"

    graph = client.get("/api/graphs/bulk_pe_deseq2_v0").json()["workflow_graph"]
    store = client.post(
        "/api/graphs/bulk_pe_deseq2_v0/verified-recipes",
        json={
            "execution_manifest": {
                "schema": "morphic.local_execution_result/v0",
                "status": "verified",
                "graph_id": "bulk_pe_deseq2_v0",
                "verified_recipe": True,
                "canonical_graph_hash": graph.get("canonical_graph_hash") or "api-test-hash",
            }
        },
    )
    assert store.status_code == 200
    assert store.json()["status"] == "verified"

    search = client.post(
        "/api/graphs/verified/search",
        json={"requested_outputs": ["differential_expression_table"], "capabilities": ["deg"]},
    )
    assert search.status_code == 200
    assert [item["graph_id"] for item in search.json()["verified_subgraphs"]] == ["bulk_pe_deseq2_v0"]


def test_agent_api_star_mvp_plan_materialize_execute_verify_only_bundle(tmp_path, monkeypatch):
    client = _client()
    plan = client.post("/api/star-mvp/plan", json={"goal": "post MEX h5ad QC and plots"})
    assert plan.status_code == 200
    assert plan.json()["graph_id"] == "star_post_mex_h5ad_qc_v0"

    paths = {
        "mex_dir": tmp_path / "mex",
        "downstream_dir": tmp_path / "downstream",
        "counts_h5ad": tmp_path / "downstream" / "counts.h5ad",
        "filtered_counts_h5ad": tmp_path / "downstream" / "filtered_counts.h5ad",
        "gene_quantile_histogram_html": tmp_path / "downstream" / "gene_quantile_histogram.html",
        "gene_quantile_histogram_png": tmp_path / "downstream" / "gene_quantile_histogram.png",
    }
    paths["mex_dir"].mkdir()
    paths["downstream_dir"].mkdir()
    for key, path in paths.items():
        if key.endswith("_dir"):
            continue
        path.write_text(f"{key}\n", encoding="utf-8")
    params = {key: str(path) for key, path in paths.items()}

    materialized = client.post(
        "/api/star-mvp/materialize",
        json={"graph_id": "star_post_mex_h5ad_qc_v0", "params": params, "out_root": str(tmp_path / "bundles")},
    )
    assert materialized.status_code == 200
    materialized_body = materialized.json()
    assert materialized_body["status"] == "materialized"
    bundle = Path(materialized_body["bundle_path"])
    assert (bundle / "run.sh").is_file()
    assert (bundle / "helpers" / "verify_artifacts.py").is_file()
    assert materialized_body["headless"]["script_filename"] == "run.sh"

    preflight = client.post(
        "/api/star-mvp/preflight",
        json={"graph_id": "star_post_mex_h5ad_qc_v0", "params": params},
    )
    assert preflight.status_code == 200
    preflight_body = preflight.json()
    assert preflight_body["status"] == "preflight_passed"
    assert preflight_body["execution_profile"] == "production"
    assert preflight_body["executable_ready"] is True
    assert all(check["status"] == "pass" for check in preflight_body["checks"])

    production = client.post(
        "/api/graphs/star_post_mex_h5ad_qc_v0/execute-production",
        json={"params": params, "bundle_path": str(bundle), "timeout": 30},
    )
    assert production.status_code == 200
    production_body = production.json()
    assert production_body["status"] == "verified"
    assert production_body["execution_result"]["verified_recipe"] is True
    assert production_body["verified_recipe"]["lifecycle_state"] == "verified"

    blocked = client.post(
        "/api/star-mvp/execute",
        json={"graph_id": "star_post_mex_h5ad_qc_v0", "bundle_path": str(bundle), "timeout": 30},
    )
    assert blocked.status_code == 403

    monkeypatch.setenv("MORPHIC_AGENT_ENABLE_LOCAL_SMOKE_EXECUTION", "1")
    executed = client.post(
        "/api/star-mvp/execute",
        json={"graph_id": "star_post_mex_h5ad_qc_v0", "bundle_path": str(bundle), "timeout": 30},
    )
    assert executed.status_code == 200
    executed_body = executed.json()
    assert executed_body["status"] == "verified"
    assert executed_body["execution_result"]["verified_recipe"] is True
    assert executed_body["verified_recipe"]["lifecycle_state"] == "verified"


def test_agent_api_trimodal_qc_render_materializes_reviewable_script(tmp_path):
    client = _client()
    params = {
        "mudata": "data/demo_trimodal_small.h5mu",
        "output_prefix": str(tmp_path / "qc" / "demo_trimodal_qc"),
        "title": "Demo trimodal QC",
    }
    rendered = client.post(
        "/api/graphs/trimodal_qc_report_v0/render",
        json={"params": params},
    )
    assert rendered.status_code == 200
    body = rendered.json()
    assert body["status"] == "materialized"
    assert body["headless"]["script_filename"] == "run.sh"
    assert body["headless"]["script"].startswith("#!/usr/bin/env bash")
    assert not body["headless"]["script"].lstrip().startswith("{")
    assert "generate_trimodal_qc.py" in body["headless"]["script"]
    assert "--mudata" in body["headless"]["script"]
    assert "manifests/path_bindings.json" in body["headless"]["script"]
    assert "data/demo_trimodal_small.h5mu" not in body["headless"]["script"]
    assert "renderer" not in str(body.get("run_blocker") or "").lower()
    bundle = Path(body["bundle_path"])
    assert (bundle / "run.sh").is_file()
    assert (bundle / "run.docker.sh").is_file()
    assert (bundle / "run.apptainer.sh").is_file()
    assert body["container_manifest_path"] == "manifests/container.json"
    assert (bundle / "helpers" / "generate_trimodal_qc.py").is_file()
    assert (bundle / "helpers" / "preflight_trimodal_qc.py").is_file()
    path_bindings = json.loads((bundle / "manifests" / "path_bindings.json").read_text())
    assert any(binding["binding_id"] == "mudata" and binding["path"] == "data/demo_trimodal_small.h5mu" for binding in path_bindings["bindings"])


def test_agent_api_star_render_uses_suite_renderer_for_real_script():
    client = _client()
    params = {
        "run_mode": "alignReads",
        "genome_dir": "/tmp/star_index",
        "read_files_mate1": "/tmp/A_R1.fastq.gz",
        "read_files_mate2": "/tmp/A_R2.fastq.gz",
        "out_file_name_prefix": "/tmp/star_out/",
        "out_file_name_prefix_auto": 1,
        "batch_mode": 1,
        "out_sam_kind": "BAM",
        "out_sam_sort": "SortedByCoordinate",
        "run_thread_n": 2,
    }
    rendered = client.post(
        "/api/suites/star/render",
        json={"workflow_id": "star_bulk_pe_batch", "params": params, "check_paths": False},
    )
    assert rendered.status_code == 200
    body = rendered.json()
    assert body["validation"]["valid"] is True
    assert body["render"]["argv"][0].endswith("/core/legacy/source/STAR")
    assert body["render"]["run_script_filename"] == "run-star_bulk_pe_batch.sh"
    assert "Generated by STAR Launchpad" in body["render"]["run_script"]


def test_agent_api_compose_and_draft_are_review_only():
    client = _client()
    compose = client.post(
        "/api/compose",
        json={"goal": "Compose bulk paired-end RNA-seq with DEGs and volcano plots"},
    )
    assert compose.status_code == 200
    body = compose.json()
    assert body["status"] == "composition"
    assert body["workflow_graph"]["graph_id"] == "bulk_pe_deseq2_plots_v0"
    assert body["headless"]["script"] is None
    assert "Approve or edit" in body["assistant_message"]

    draft = client.post(
        "/api/compose/draft",
        json={"graph_id": "bulk_pe_deseq2_plots_v0", "params": {}},
    )
    assert draft.status_code == 200
    draft_body = draft.json()
    assert draft_body["status"] == "composition_recipe_draft"
    assert draft_body["recipe_draft"]["workflow_graph"]["graph_id"] == "bulk_pe_deseq2_plots_v0"
    assert draft_body["headless"]["script"] is None
    assert draft_body["run_blocker"]
