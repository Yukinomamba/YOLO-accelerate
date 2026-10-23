#!/usr/bin/env python3
"""Summarize the complete original core without borrowing the 128-MAC report."""
import argparse
import json
from pathlib import Path
from collect_report import ROOT, digest, table


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    m = json.loads((a.project/'manifest.json').read_text())
    g = json.loads((a.project/'guard.json').read_text())
    assert m['schema']=='adam-upstream-pango-v1'
    for name, expected in m['files'].items():
        assert digest(a.project/name)==expected, name
    for name in m['rtl']:
        assert digest(ROOT/name)==m['files'][name], name
    g['command']='pds_shell.exe -work_dir "$PROJECT" -project_name adam_upstream -file "$PROJECT/synthesize.tcl"'
    report = dict(schema='adam-upstream-synthesis-v1', project=m['project'],
                  source_branch=m['source_branch'], source_base_commit=m['source_base_commit'],
                  upstream_commit=m['upstream_commit'], upstream_modified_files=[],
                  source_sha256=m['files'], device=m['device'], clock_period_ns=10,
                  memory_guard=g, synthesis_completed=g['status']=='PASS',
                  gate_simulation_run=False, route_run=False, board_run=False,
                  routed_fmax_mhz=None, routed_wns_ns=None, unrouted_nets=None)
    evidence=['manifest.json','guard.json','synthesis.log','guard-samples.jsonl']
    db=a.project/'prj_tasks/syn_1/synthesize/report_db'
    if g['status']=='PASS':
        for key, stem in [('resources','resource_utilization'),('cell_usage','resource_usage'),
                          ('fmax','report_timing_fmax'),('setup','report_timing_setup'),
                          ('hold','report_timing_hold'),('check_timing','check_timing_summary')]:
            f=db/f'synthesize_{stem}.db'
            report[key]=table(f, recursive=key=='resources')
            evidence.append(str(f.relative_to(a.project)))
        f=db/'synthesize_report_timing_path_setup.db'
        paths=table(f)
        report['worst_setup_path']=paths[0]
        report['reported_setup_paths']=len(paths)
        evidence += [str(f.relative_to(a.project)), 'prj_tasks/syn_1/synthesize/adam_upstream_syn.vm']
    report['evidence_sha256']={f:digest(a.project/f) for f in evidence}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print('Saved synthesis status:', g['status'], a.output)


if __name__=='__main__':
    main()
