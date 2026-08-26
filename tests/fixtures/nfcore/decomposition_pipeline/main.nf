nextflow.enable.dsl = 2

include { DEMO } from './workflows/demo'
include { paramsHelp } from 'plugin/nf-schema'

workflow {
    paramsHelp()
    DEMO()
}
