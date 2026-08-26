nextflow.enable.dsl = 2

params.message = params.message ?: 'hello from workbench'
params.outdir = params.outdir ?: 'results'

process WRITE_MESSAGE {
    publishDir params.outdir, mode: 'copy'

    output:
    path 'message.txt'

    script:
    """
    printf '%s\n' '${params.message}' > message.txt
    """
}

workflow {
    WRITE_MESSAGE()
}
