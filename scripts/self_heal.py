import argparse
import json
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from modal_app.cf_client import CloudflareAPIClient


def list_errors(cf: CloudflareAPIClient, unresolved: bool = True, workflow: str | None = None, limit: int = 50):
    errors = cf.get_errors(unresolved=unresolved, workflow=workflow, limit=limit)
    if not errors:
        status_label = "unresolved" if unresolved else "recorded"
        print(f"✅ No {status_label} errors found in D1.")
        return []

    print(f"Found {len(errors)} error log entries in D1:\n")
    for err in errors:
        err_id = err.get("id")
        wf = err.get("workflow", "unknown")
        created = err.get("created_at", "—")
        msg = err.get("error_message", "")
        err_type = err.get("error_type", "Error")
        resolved = "Resolved" if err.get("is_resolved") else "OPEN"
        print(f"[{err_id}] {created} | {wf} | {err_type} | [{resolved}]")
        print(f"     Message: {msg}")
        if err.get("stack_trace"):
            tb_first = err["stack_trace"].strip().split("\n")[-1]
            print(f"     Traceback: {tb_first}")
        if err.get("resolution_notes"):
            print(f"     Resolution: {err['resolution_notes']} (by {err.get('resolved_by')})")
        print("-" * 60)
    return errors


def inspect_error(cf: CloudflareAPIClient, error_id: int):
    errors = cf.get_errors(unresolved=False, limit=100)
    matched = [e for e in errors if int(e.get("id")) == int(error_id)]
    if not matched:
        print(f"❌ Error #{error_id} not found in recent records.")
        sys.exit(1)

    err = matched[0]
    print(f"==================================================")
    print(f"ERROR DETAILS #{err['id']} ({err['workflow']})")
    print(f"==================================================")
    print(f"Timestamp:   {err.get('created_at')}")
    print(f"Run ID:      {err.get('run_id') or 'N/A'}")
    print(f"Type:        {err.get('error_type') or 'N/A'}")
    print(f"Severity:    {err.get('severity') or 'error'}")
    print(f"Resolved:    {'Yes' if err.get('is_resolved') else 'No'}")
    if err.get("resolved_at"):
        print(f"Resolved At: {err.get('resolved_at')} by {err.get('resolved_by')}")
        print(f"Notes:       {err.get('resolution_notes')}")
    print(f"\nMessage:\n{err.get('error_message')}")
    if err.get("stack_trace"):
        print(f"\nFull Stack Trace:\n{err.get('stack_trace')}")
    if err.get("context"):
        print(f"\nContext Payload:\n{err.get('context')}")
    print(f"==================================================")


def resolve_error(cf: CloudflareAPIClient, error_id: int, notes: str, resolved_by: str):
    success = cf.resolve_error(
        error_id=error_id,
        resolution_notes=notes,
        resolved_by=resolved_by,
    )
    if success:
        print(f"✅ Marked Error #{error_id} as resolved in D1 ({resolved_by}: {notes})")
    else:
        print(f"❌ Failed to resolve Error #{error_id}")


def main():
    parser = argparse.ArgumentParser(description="Extrapcap D1 Error Log & Self-Healing Tool")
    parser.add_argument("--list", action="store_true", help="List unresolved errors")
    parser.add_argument("--all", action="store_true", help="Include resolved errors")
    parser.add_argument("--workflow", type=str, default=None, help="Filter by workflow name")
    parser.add_argument("--limit", type=int, default=50, help="Max records to retrieve")
    parser.add_argument("--inspect", type=int, default=None, help="Inspect full details for error ID")
    parser.add_argument("--resolve", type=int, default=None, help="Mark error ID as resolved")
    parser.add_argument("--notes", type=str, default="Resolved via self-healing pipeline", help="Resolution notes")
    parser.add_argument("--by", type=str, default="antigravity-healer", help="Resolver entity name")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()
    cf = CloudflareAPIClient()

    if args.inspect:
        inspect_error(cf, args.inspect)
    elif args.resolve:
        resolve_error(cf, args.resolve, args.notes, args.by)
    else:
        unresolved = not args.all
        if args.json:
            errors = cf.get_errors(unresolved=unresolved, workflow=args.workflow, limit=args.limit)
            print(json.dumps(errors, indent=2))
        else:
            list_errors(cf, unresolved=unresolved, workflow=args.workflow, limit=args.limit)


if __name__ == "__main__":
    main()
