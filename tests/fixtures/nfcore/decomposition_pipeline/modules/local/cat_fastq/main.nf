process CAT_FASTQ {
    input:
    path reads

    output:
    path "reads.fastq.gz"

    script:
    """
    touch reads.fastq.gz
    """
}
