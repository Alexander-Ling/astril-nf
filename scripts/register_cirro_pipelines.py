#!/usr/bin/env python3
"""Register (or update) the astril-nf custom pipelines in Cirro via the Cirro SDK.

Every pipeline is described by `.cirro/<stage>/process-definition.json`; this script reads
those files and registers them in folder order (00 -> 03b), which is also the dependency order
(each stage's parent process must already exist). Existing pipelines are updated in place.
After each create/update the pipeline is synced, so Cirro re-reads the form, input mapping,
compute config and preprocess script from GitHub.

Dry run by default: prints what it would do and changes nothing. Pass --apply to write.

Scope: the only Cirro writes this script makes are create/update/sync of the process IDs
found in .cirro/*/process-definition.json, all of which must start with `process-astril-`.
It never archives or deletes anything. Reads: the project list (to resolve --project by
name) and the process list (to decide create vs. update).

Usage (after `pip install cirro` and `cirro configure`):
    python scripts/register_cirro_pipelines.py --project BTC-GBM-Development
    python scripts/register_cirro_pipelines.py --project BTC-GBM-Development --apply
    python scripts/register_cirro_pipelines.py --project BTC-GBM-Development --apply --sync-only
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CIRRO_DIR = REPO_ROOT / ".cirro"
ID_PREFIX = "process-astril-"
# Cirro's built-in "Files" upload type: not one of ours, never created or modified here.
BUILTIN_PARENTS = {"custom_dataset"}


def load_definitions():
    defs = []
    for path in sorted(CIRRO_DIR.glob("*/process-definition.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if not d["id"].startswith(ID_PREFIX):
            sys.exit(f"{path}: id {d['id']!r} doesn't start with {ID_PREFIX!r}; refusing to touch it")
        # Cirro's update endpoint enforces this (create doesn't), so check up front rather than
        # failing halfway through a run.
        if not 4 <= len(d["desc"]) <= 500:
            sys.exit(f"{path}: desc is {len(d['desc'])} chars; Cirro requires 4-500")
        if d["code"]["repository"] != "GITHUBPUBLIC":
            sys.exit(f"{path}: only public GitHub repos are supported here")
        d["_folder"] = path.parent.relative_to(REPO_ROOT).as_posix()
        defs.append(d)
    if not defs:
        sys.exit(f"no process-definition.json files under {CIRRO_DIR}")
    return defs


def resolve_project_id(cirro, project):
    projects = cirro.projects.list()
    matches = [p for p in projects if project in (p.id, p.name)]
    if len(matches) != 1:
        names = ", ".join(sorted(p.name for p in projects))
        sys.exit(f"expected exactly 1 project matching {project!r}, found {len(matches)}. "
                 f"Projects visible to you: {names}")
    return matches[0].id


def build_input(d, project_id, child_ids):
    from cirro_api_client.v1.models import (
        CustomPipelineSettings, CustomProcessInput, Executor, PipelineCode, RepositoryType)
    code = d["code"]
    return CustomProcessInput(
        id=d["id"],
        name=d["name"],
        description=d["desc"],
        executor=Executor(d["executor"]),
        parent_process_ids=d["parentProcessIds"],
        child_process_ids=child_ids,
        linked_project_ids=[project_id],
        category=d["category"],
        documentation_url=d["documentationUrl"],
        is_tenant_wide=False,
        allow_multiple_sources=False,
        uses_sample_sheet=False,
        pipeline_code=PipelineCode(
            repository_path=code["uri"],
            version=code["version"],
            repository_type=RepositoryType.GITHUB_PUBLIC,
            entry_point=code["script"],
            executor_version=code["executorVersion"],
        ),
        # Pipeline config (form, input mapping, compute, preprocess) lives in the same repo,
        # in this stage's own .cirro/<stage> folder.
        custom_settings=CustomPipelineSettings(
            repository=code["uri"],
            branch=code["version"],
            folder=d["_folder"],
            repository_type=RepositoryType.GITHUB_PUBLIC,
        ),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", required=True, help="Cirro project name or ID to make the pipelines visible in")
    ap.add_argument("--apply", action="store_true", help="actually write to Cirro (default: dry run)")
    ap.add_argument("--sync-only", action="store_true",
                    help="only re-sync existing pipelines from GitHub (e.g. after pushing config edits)")
    args = ap.parse_args()

    defs = load_definitions()
    ours = {d["id"] for d in defs}
    for d in defs:
        unknown = set(d["parentProcessIds"]) - ours - BUILTIN_PARENTS
        if unknown:
            sys.exit(f"{d['id']}: parent(s) {sorted(unknown)} are neither astril-nf processes nor {BUILTIN_PARENTS}")

    from cirro.cirro_client import CirroApi
    cirro = CirroApi()
    project_id = resolve_project_id(cirro, args.project)
    existing = {p.id for p in cirro.processes.list(include_archived=True)}
    mode = "APPLY" if args.apply else "DRY RUN (pass --apply to write)"
    print(f"{mode}: project {args.project!r} -> {project_id}\n")

    deferred_children = {}  # child_process_ids that pointed at not-yet-created processes
    for d in defs:
        pid = d["id"]
        is_new = pid not in existing
        if args.sync_only:
            if is_new:
                print(f"skip   {pid}: not registered yet")
                continue
            print(f"sync   {pid}")
            if args.apply:
                cirro.processes.sync_custom_process(pid)
            continue

        children = [c for c in d["childProcessIds"] if c in existing]
        if len(children) != len(d["childProcessIds"]):
            deferred_children[pid] = d
        action = "create" if is_new else "update"
        print(f"{action} {pid}  [{d['_folder']}]\n"
              f"       name:    {d['name']}\n"
              f"       parents: {d['parentProcessIds']}\n"
              f"       code:    {d['code']['uri']}@{d['code']['version']} {d['code']['script']}"
              f" (Nextflow {d['code']['executorVersion']})")
        if args.apply:
            body = build_input(d, project_id, children)
            if is_new:
                cirro.processes.create_custom_process(body)
            else:
                cirro.processes.update_custom_process(pid, body)
            cirro.processes.sync_custom_process(pid)
        existing.add(pid)  # later stages can now name it as a parent/child

    # A stage listing a LATER stage as its child (e.g. segment -> quantify) was created
    # without that link; add it now that every process exists.
    for pid, d in deferred_children.items():
        print(f"link   {pid} -> children {d['childProcessIds']}")
        if args.apply:
            cirro.processes.update_custom_process(pid, build_input(d, project_id, d["childProcessIds"]))
            cirro.processes.sync_custom_process(pid)

    print("\nDone." if args.apply else "\nDry run only; nothing was changed.")


if __name__ == "__main__":
    main()
