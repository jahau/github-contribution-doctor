#!/usr/bin/env python3
"""Read-only Git contribution checks."""
import argparse
import json
import shutil
import subprocess


def run(*args):
    p = subprocess.run(args, text=True, capture_output=True, check=False)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.')
    args = parser.parse_args()
    checks = []
    if not shutil.which('git'):
        raise SystemExit('Git is required.')
    rc, path, err = run('git', '-C', args.repo, 'rev-parse', '--show-toplevel')
    if rc: raise SystemExit('Not a Git repository: ' + err)
    _, email, _ = run('git', '-C', path, 'log', '-1', '--format=%ae')
    checks.append(('Latest commit author email', email or 'Unknown', 'Verify this email on your GitHub account'))
    _, branch, _ = run('git', '-C', path, 'branch', '--show-current')
    _, remote, _ = run('git', '-C', path, 'symbolic-ref', 'refs/remotes/origin/HEAD')
    default = remote.rsplit('/', 1)[-1] if remote else None
    checks.append(('Current branch', branch or '(detached)', 'Contributions normally count on the default branch or gh-pages; PR merges have separate rules'))
    checks.append(('Origin default branch', default or 'Unknown', 'Set origin/HEAD or inspect GitHub repository settings'))
    if shutil.which('gh'):
        rc, out, _ = run('gh', 'repo', 'view', '--json', 'isFork,isPrivate,nameWithOwner')
        if rc == 0:
            try:
                info = json.loads(out)
                checks.append(('GitHub repository', info.get('nameWithOwner', 'Unknown'), ''))
                checks.append(('Fork', str(info.get('isFork')), 'Fork commits have separate contribution eligibility rules'))
                checks.append(('Private', str(info.get('isPrivate')), 'Private contribution visibility is an account setting'))
            except json.JSONDecodeError: pass
    print('GitHub Contribution Doctor (read-only)\n')
    for title, value, hint in checks:
        print(f'{title}: {value}')
        if hint: print(f'  Note: {hint}')
    print('\nManual checks: Verified email, private contributions setting, contribution timing.')


if __name__ == '__main__': main()
