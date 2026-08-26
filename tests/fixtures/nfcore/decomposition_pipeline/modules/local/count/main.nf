process COUNTS {
    input:
    path reads

    output:
    path "counts.tsv"

    script:
    """
    touch counts.tsv
    """
}
