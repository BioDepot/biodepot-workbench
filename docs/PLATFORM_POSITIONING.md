# Platform positioning

BioDepot Workbench is not a new workflow language and is not intended to
replace established workflow engines. It is a human-agent interface to the
bioinformatics software ecosystem.

The platform contribution is a shared, inspectable contract through which
scientists and agents can:

1. discover modules, recipes, and external workflow metadata;
2. search typed workflow graphs by inputs, outputs, capabilities, confidence,
   and validation evidence;
3. compose or retrieve a candidate analysis and explain why it fits;
4. review parameters, paths, containers, and execution location;
5. render a reproducible bundle and run preflight checks;
6. execute only through an explicitly approved adapter; and
7. preserve the conversation, graph, validation, and run provenance.

## Why the shared surface matters

Traditional graphical workflow tools primarily mediate between a person and a
workflow engine. Chat interfaces often generate code without a durable catalog
or a review boundary. BioDepot Workbench makes the catalog, graph, review, and
execution contracts available to browser users and MCP clients alike.

The browser remains important: it gives scientists a visual place to inspect
the proposed graph and edit parameters. MCP makes the same operations available
to coding agents without teaching each client a private API. The service layer
keeps both surfaces behaviorally aligned.

## Knowledge and execution are separate

Graph search operates on artifact types, schemas, capabilities, runtime
requirements, and evidence rather than graph shape alone. A graph can be useful
for planning before it is executable. Lifecycle and confidence fields make that
distinction explicit.

Similarly, choosing a workflow is not choosing a compute destination. Execution
locations describe authority and path visibility; adapters describe how work is
dispatched. Human review and preflight bind the selected graph and parameters to
the selected location.

## Interoperability

The public nf-core integration demonstrates the boundary: metadata and DSL2
source can be harvested into the catalog, mapped to a typed graph, reviewed,
and rendered as a Nextflow bundle while nf-core/Nextflow remains the execution
authority. The same architecture can support other maintained ecosystems
without inventing a new workflow language.

## Evaluation dimensions

Useful evaluation should measure more than whether a model produced runnable
code. Relevant dimensions include retrieval accuracy, parameter-validation
coverage, graph explanation quality, review-gate enforcement, reproducibility
of rendered bundles, provenance completeness, and agreement between API, MCP,
and browser behavior.
