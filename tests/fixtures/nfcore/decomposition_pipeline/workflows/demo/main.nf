include { PREPARE } from '../../subworkflows/local/prepare'
include { COUNTS as COUNT_SAMPLE } from '../../modules/local/count'
include { FASTQC } from '../../modules/nf-core/fastqc'

workflow DEMO {
    PREPARE()
    COUNT_SAMPLE()
    FASTQC()
}
