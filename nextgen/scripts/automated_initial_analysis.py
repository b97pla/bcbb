#!/usr/bin/env python
"""Perform an automated analysis on a sequencing run using Galaxy information.

Given a directory of solexa output, this retrieves details about the sequencing
run from the Galaxy description, and uses this to perform an initial alignment
and analysis.

Usage:
    automated_initial_analysis.py <YAML config file> <flow cell dir>
                                  [<YAML run information>]

The optional <YAML run information> file specifies details about the
flowcell lanes, instead of retrieving it from Galaxy. An example
configuration file is located in 'config/run_info.yaml'

Workflow:
    - Retrieve details on a run.
    - Align fastq files to reference genome.
    - Perform secondary analyses like SNP calling.
    - Generate summary report.
"""
import os
import sys
import subprocess
from optparse import OptionParser

import yaml

from bcbio.solexa.flowcell import (get_flowcell_info, get_fastq_dir)
from bcbio.galaxy.api import GalaxyApiAccess
from bcbio import utils
from bcbio.log import create_log_handler
from bcbio.distributed import messaging
from bcbio.pipeline import log
from bcbio.pipeline.demultiplex import add_multiplex_across_lanes
from bcbio.pipeline.merge import organize_samples
from bcbio.pipeline.qcsummary import write_metrics
from bcbio.pipeline import sample
from bcbio.pipeline import lane
from bcbio.pipeline.config_loader import load_config

def main(config_file, fc_dir, run_info_yaml=None):
    config = load_config(config_file)
    log_handler = create_log_handler(config, log.name)
    with log_handler.applicationbound():
        run_main(config, config_file, fc_dir, run_info_yaml)

def run_main(config, config_file, fc_dir, run_info_yaml):
    work_dir = os.getcwd()
    align_dir = os.path.join(work_dir, "alignments")

    fc_name, fc_date = get_flowcell_info(fc_dir)
    run_info = _get_run_info(fc_name, fc_date, config, run_info_yaml)
    fastq_dir, galaxy_dir, config_dir = _get_full_paths(get_fastq_dir(fc_dir),
                                                        config, config_file)
    config_file = os.path.join(config_dir, os.path.basename(config_file))
    dirs = {"fastq": fastq_dir, "galaxy": galaxy_dir, "align": align_dir,
            "work": work_dir, "flowcell": fc_dir, "config": config_dir}
    run_items = add_multiplex_across_lanes(run_info["details"], dirs["fastq"], fc_name)

    # process each flowcell lane
    lanes = ((info, fc_name, fc_date, dirs, config) for info in run_items)
    lane_items = _run_parallel("process_lane", lanes, dirs, config)
    
    # Upload the demultiplex counts to Google Docs
    _upload_to_gdocs(config,fc_dir,run_info_yaml)
    
    _run_parallel("process_alignment", lane_items, dirs, config)
    # process samples, potentially multiplexed across multiple lanes
    sample_files, sample_fastq, sample_info = \
                  organize_samples(dirs, fc_name, fc_date, run_items)
    samples = ((n, sample_fastq[n], sample_info[n], bam_files, dirs, config, config_file)
               for n, bam_files in sample_files)
    _run_parallel("process_sample", samples, dirs, config)

    write_metrics(run_info, fc_name, fc_date, dirs)

def _run_parallel(fn_name, items, dirs, config):
    """Process a supplied function: single, multi-processor or distributed.
    """
    parallel = config["algorithm"]["num_cores"]
    if str(parallel).lower() == "messaging":
        runner = messaging.runner(dirs, config)
        return runner(fn_name, items)
    else:
        out = []
        fn = globals()[fn_name]
        with utils.cpmap(int(parallel)) as cpmap:
            for data in cpmap(fn, items):
                if data:
                    out.extend(data)
        return out

# ## multiprocessing ready entry points

@utils.map_wrap
def process_lane(*args):
    return lane.process_lane(*args)

@utils.map_wrap
def process_alignment(*args):
    return lane.process_alignment(*args)

@utils.map_wrap
def process_sample(*args):
    return sample.process_sample(*args)

# ## Utility functions

def _get_run_info(fc_name, fc_date, config, run_info_yaml):
    """Retrieve run information from a passed YAML file or the Galaxy API.
    """
    if run_info_yaml and os.path.exists(run_info_yaml):
        log.info("Found YAML samplesheet, using %s instead of Galaxy API" % run_info_yaml)
        with open(run_info_yaml) as in_handle:
            run_details = yaml.load(in_handle)
        return dict(details=run_details, run_id="")
    else:
        log.info("Fetching run details from Galaxy instance")
        galaxy_api = GalaxyApiAccess(config['galaxy_url'], config['galaxy_api_key'])
        return galaxy_api.run_details(fc_name, fc_date)

def _get_full_paths(fastq_dir, config, config_file):
    """Retrieve full paths for directories in the case of relative locations.
    """
    fastq_dir = utils.add_full_path(fastq_dir)
    config_dir = utils.add_full_path(os.path.dirname(config_file))
    galaxy_config_file = utils.add_full_path(config["galaxy_config"], config_dir)
    return fastq_dir, os.path.dirname(galaxy_config_file), config_dir

def _upload_to_gdocs(config,fc_dir,run_info_yaml):
    """Upload the barcode demultiplex counts to spreadsheet on Google Docs
    """
    
    # The run_name corresponds to the last part of the fc_dir
    run_name = os.path.basename(fc_dir.rstrip('/'))
    
    # Get the required parameters from the post_process.yaml configuration file
    gdocs = config.get("gdocs_upload",None)
    if not gdocs:
        log.info("No GDocs upload section specified in config file, will not upload demultiplex data")
        return
    
    # Get the store dir and base dir from the configuration file
    analysis = config.get("analysis",{})
    base_dir = analysis.get("base_dir",None)
    if not base_dir:
        log.warn("Could not get base_dir from configuration file, will not upload barcode statistics to google docs")
        return
    
    upload_script = gdocs.get("gdocs_upload_script",None)
    destination_file = gdocs.get("gdocs_dmplx_file",None)
    credentials = gdocs.get("gdocs_credentials",None)
    cl = [upload_script, run_name, destination_file, credentials, "--config=%s" %  run_info_yaml, "--analysis_dir=%s" % base_dir]
    try:
        subprocess.check_call(cl)
    except Exception, e:
        log.warn("The script %s generated an exception: %s. Resuming pipeline...\n" % (upload_script,e))

if __name__ == "__main__":
    parser = OptionParser()
    (options, args) = parser.parse_args()
    if len(args) < 2:
        print "Incorrect arguments"
        print __doc__
        sys.exit()
    kwargs = dict()
    main(*args, **kwargs)
