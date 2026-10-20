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
name) and a lookup of each of our process IDs (to decide create vs. update).

Usage (after `pip install cirro` and `cirro configure`):
    python scripts/register_cirro_pipelines.py --project BTC-GBM-Development
    python scripts/register_cirro_pipelines.py --project BTC-GBM-Development --apply
    python scripts/register_cirro_pipelines.py --project BTC-GBM-Development --apply --sync-only
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CIRRO_DIR = REPO_ROOT / ".cirro"
ID_PREFIX = "process-astril-"
# Cirro's built-in "Files" upload type: not one of ours, never created or modified here.
BUILTIN_PARENTS = {"custom_dataset"}
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .&\-@!#'()/]*")


# Cirro reads the (public) repo from GitHub on every create/update/sync. After a few calls in
# quick succession it starts answering with this error for a repo it read fine seconds earlier
# (looks like a GitHub rate limit on Cirro's side), so pace calls and retry on exactly that error.
REPO_THROTTLE_MSG = "repository is not found or we do not have the required permissions"
PAUSE_BETWEEN_PIPELINES_S = 30
RETRY_WAITS_S = (60, 120, 240)


def call(fn, expected_type, what):
    """Run one Cirro write, check its result, and retry only on the repo-throttle error.

    The SDK's create endpoint RETURNS a PortalErrorResponse on HTTP 400 instead of raising
    (sync/update raise instead), so every result is checked explicitly; never assume a call
    that didn't raise worked."""
    from cirro_api_client.v1.errors import BadRequestException
    for wait in (*RETRY_WAITS_S, None):
        try:
            result = fn()
        except BadRequestException as e:
            result = e
        if expected_type is None and result is None or \
                expected_type is not None and isinstance(result, expected_type):
            return result
        if wait is None or REPO_THROTTLE_MSG not in str(result):
            sys.exit(f"{what} failed: {result}")
        print(f"       {what}: Cirro couldn't read the repo; retrying in {wait}s")
        time.sleep(wait)


def load_definitions():
    defs = []
    for path in sorted(CIRRO_DIR.glob("*/process-definition.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if not d["id"].startswith(ID_PREFIX):
            sys.exit(f"{path}: id {d['id']!r} doesn't start with {ID_PREFIX!r}; refusing to touch it")
        # Cirro's own validation rules, checked up front rather than failing halfway through a run.
        if not NAME_RE.fullmatch(d["name"]):
            sys.exit(f"{path}: name {d['name']!r} must start with a letter/digit and contain only "
                     "letters, digits, spaces and .&-@!#'()/")
        if not 4 <= len(d["desc"]) <= 500:
            sys.exit(f"{path}: desc is {len(d['desc'])} chars; Cirro requires 4-500")
        if d["code"]["repository"] != "GITHUBPUBLIC":
            sys.exit(f"{path}: only public GitHub repos are supported here")
        d["_folder"] = path.parent.relative_to(REPO_ROOT).as_posix()
        defs.append(d)
    if not defs:
        sys.exit(f"no process-definition.json files under {CIRRO_DIR}")
    return defs


def process_exists(cirro, pid):
    from cirro_api_client.v1.errors import NotFoundException
    try:
        return cirro.processes.get(pid) is not None
    except NotFoundException:
        return False


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
        # Upload guidance Cirro shows for this pipeline's input; carries the PHI warning.
        file_requirements_message=d["fileRequirementsMessage"],
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
    from cirro_api_client.v1.models import CreateResponse, CustomPipelineSettings
    cirro = CirroApi()
    project_id = resolve_project_id(cirro, args.project)
    existing = {d["id"] for d in defs if process_exists(cirro, d["id"])}
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
                call(lambda: cirro.processes.sync_custom_process(pid), CustomPipelineSettings, f"sync {pid}")
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
                call(lambda: cirro.processes.create_custom_process(body), CreateResponse, f"create {pid}")
                if not process_exists(cirro, pid):
                    sys.exit(f"create {pid} reported success but the process doesn't exist")
            else:
                call(lambda: cirro.processes.update_custom_process(pid, body), None, f"update {pid}")
            call(lambda: cirro.processes.sync_custom_process(pid), CustomPipelineSettings, f"sync {pid}")
            time.sleep(PAUSE_BETWEEN_PIPELINES_S)
        existing.add(pid)  # later stages can now name it as a parent/child

    # A stage listing a LATER stage as its child (e.g. segment -> quantify) was created
    # without that link; add it now that every process exists.
    for pid, d in deferred_children.items():
        print(f"link   {pid} -> children {d['childProcessIds']}")
        if args.apply:
            body = build_input(d, project_id, d["childProcessIds"])
            call(lambda: cirro.processes.update_custom_process(pid, body), None, f"update {pid}")
            call(lambda: cirro.processes.sync_custom_process(pid), CustomPipelineSettings, f"sync {pid}")

    print("\nDone." if args.apply else "\nDry run only; nothing was changed.")


if __name__ == "__main__":
    main()
