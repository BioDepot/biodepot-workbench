process FASTQC {
    input:
    path reads

    output:
    path "fastqc.html"

    script:
    """
    touch fastqc.html
    """
}
