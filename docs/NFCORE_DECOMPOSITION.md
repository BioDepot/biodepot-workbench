# nf-core source decomposition

The nf-core decomposer creates an auditable editing index from a local DSL2
checkout. It records source files, workflow/process/function declarations,
include aliases, statically resolvable invocation sites, component metadata,
and module revisions. It does not execute Nextflow or embed source text in the
result.

The complete artifact uses `morphic.nfcore_decomposition/v0`; its compact graph
uses `morphic.nfcore_component_graph/v0`.

```bash
python3 scripts/decompose_nfcore_pipeline.py /path/to/nf-core/pipeline \
  --strict --summary
```

Strict mode reports unresolved local includes, missing symbols, and metadata
parse errors. Invocation edges mean a statically resolved source call, not a
predicted runtime task dependency. The runnable boundary remains the complete
pipeline unless a separately maintained component contract says otherwise.
