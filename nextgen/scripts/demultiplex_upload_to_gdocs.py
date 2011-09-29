#!/usr/bin/env python
"""Upload the information on the number of reads per barcode after demultiplex generated by the analysis pipeline to a spreadsheet on Google docs.

Given the name of a sequencing run (including date, machine id and flowcell id), the title of a (pre-existing) spreadsheet on a GoogleDocs account 
and a base64-encoded string of the concatenated username and password (separated by a ':') for a google account  with write access to the spreadsheet, 
will create a new worksheet in the spreadsheet and enter the data into it. In addition, a run_info.yaml configuration file (or the directory where it 
can be found) must be specified. Optionally, the name of the worksheet where data will be written can be specified, by default a new worksheet on the 
form [date]_[flowcell_id] is created. Alternatively, one worksheet can be created for each project included in the run. In addition, the total read 
counts for each sample will be summarized across lanes and written to a spreadsheet named [project name]_sequencing_results that will be placed under
a [project_name] folder. If a parent folder is specified, the project folder will be placed here.
"""
import os
import sys
import yaml
from optparse import OptionParser
from bcbio.pipeline import log
from bcbio.solexa.flowcell import get_flowcell_info
from bcbio.google.bc_metrics import (get_bc_stats,write_run_report_to_gdocs,write_project_report_to_gdocs)

def main(run_name, gdocs_spreadsheet, gdocs_credentials, run_info_yaml, analysis_dir, archive_dir, gdocs_worksheet, gdocs_projects_folder, append, split_on_project):

    log.info("Processing run: %s" % run_name)
    
    # If not supplied, assume that the configuration file is named run_info.yaml and resides in the archive dir
    if not run_info_yaml:
        run_info_yaml = os.path.join(archive_dir,"run_info.yaml")
        log.info("No configuration file supplied, assuming it is '%s'" % run_info_yaml)
        
    if not os.path.exists(run_info_yaml):
        log.warn("Could not find required run_info.yaml configuration file at '%s'" % run_info_yaml)
        return
    with open(run_info_yaml) as in_handle:
        run_info = yaml.load(in_handle)

    fc_name, fc_date = get_flowcell_info(run_name)
    
    # Get the barcode statistics
    bc_metrics = get_bc_stats(fc_date,fc_name,analysis_dir,run_info)
    
    # Write the report
    write_run_report_to_gdocs(fc_date,fc_name,bc_metrics,gdocs_spreadsheet,gdocs_credentials,gdocs_worksheet,append,split_on_project)
    
    # Write the bc project summary report
    write_project_report_to_gdocs(fc_date,fc_name,bc_metrics,gdocs_credentials,gdocs_projects_folder)
    
if __name__ == "__main__":
    usage = """
    demultiplex_upload_to_gdocs.py <run name> <gdocs_spreadsheet> <gdocs_credentials>
                           [--config=<run configuration file>
                            --analysis_dir=<analysis directory>
                            --archive_dir=<archive directory>
                            --gdocs_worksheet=<worksheet title>
                            --gdocs_projects_folder=<projects folder on gdocs>
                            --append
                            --split_on_project]
"""

    parser = OptionParser(usage=usage)
    parser.add_option("-c", "--config", dest="run_info_yaml", default=None)
    parser.add_option("-d", "--analysis_dir", dest="analysis_dir", default=os.getcwd())
    parser.add_option("-r", "--archive_dir", dest="archive_dir", default=os.getcwd())
    parser.add_option("-w", "--gdocs_worksheet", dest="gdocs_worksheet", default=None)
    parser.add_option("-p", "--gdocs_projects_folder", dest="gdocs_projects_folder", default="")
    parser.add_option("-a", "--append", action="store_true", dest="append", default=False)
    parser.add_option("-s", "--split_on_project", action="store_true", dest="split_on_project", default=False)
    (options, args) = parser.parse_args()
    if len(args) < 1:
        print parser.usage
        print __doc__
        sys.exit()
    kwargs = dict(
        run_info_yaml = options.run_info_yaml,
        analysis_dir = os.path.normpath(options.analysis_dir),
        archive_dir = os.path.normpath(options.archive_dir),
        gdocs_worksheet = options.gdocs_worksheet,
        gdocs_projects_folder = options.gdocs_projects_folder,
        append = options.append,
        split_on_project = options.split_on_project
        )
    main(*args, **kwargs)
