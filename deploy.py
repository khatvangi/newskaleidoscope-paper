#!/usr/bin/env python3
"""
deploy.py — push docs/ to git for Cloudflare Pages deployment.

checks that HTML exists, commits docs/, pushes to main branch.
cloudflare pages auto-deploys from docs/ on push.
"""

import os
import subprocess
import sys


def run(cmd, check=True):
    """run shell command, return stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"FAILED: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result.stdout.strip()


def deploy():
    # verify docs exist
    event_dirs = []
    for d in os.listdir("docs/events"):
        index = os.path.join("docs/events", d, "index.html")
        if os.path.exists(index):
            size = os.path.getsize(index)
            event_dirs.append((d, size))
            print(f"  {d}: {size:,} bytes")

    if not event_dirs:
        print("ERROR: no event pages found in docs/events/")
        sys.exit(1)

    # check git status
    status = run("git status --porcelain docs/", check=False)
    if not status:
        print("docs/ has no changes to deploy")
        return

    print(f"\nchanges to deploy:")
    print(status)

    # confirm
    if "--yes" not in sys.argv:
        resp = input("\npush to main? [y/N] ")
        if resp.lower() != "y":
            print("aborted")
            return

    # commit and push
    run("git add docs/")
    run('git commit -m "deploy: update event pages"')

    # push to main (cloudflare pages source branch)
    current = run("git branch --show-current")
    if current != "main":
        print(f"on branch '{current}', pushing docs to main...")
        run("git push origin HEAD:main")
    else:
        run("git push origin main")

    print("\ndeployed. cloudflare pages will auto-build from docs/.")


if __name__ == "__main__":
    deploy()
