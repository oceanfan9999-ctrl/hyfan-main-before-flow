"""Read-only release snapshot/gate. No fetch, commit, push, or file writes.

Exit 0 = mechanical checks passed (NOT authorization); 2 = blocked; 1 = error.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FULL_SHA = re.compile(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z')
CONVENTIONAL = re.compile(r'(?:feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(?:\([^\r\n()]+\))?!?: [^\r\n]+')


def git(repo, *args, optional=False):
    result = subprocess.run(
        ['git', '--no-optional-locks', '-C', str(repo), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0'),
    )
    if result.returncode:
        if optional:
            return None
        # Do not echo stderr/config/remote URLs that might contain secrets.
        raise ValueError('Git inspection failed: ' + args[0])
    return result.stdout


def txt(repo, *args):
    return git(repo, *args).decode('utf-8', 'replace').strip()


def resolve(repo, ref):
    value = git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}', optional=True)
    return value.decode().strip() if value is not None else None


def diff_hash(repo, *args):
    raw = git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames',
              '--binary', '--full-index', '--no-color', '--src-prefix=a/',
              '--dst-prefix=b/', '--unified=3', '--diff-algorithm=myers',
              '--no-indent-heuristic', *args, '--')
    return hashlib.sha256(raw).hexdigest()


def ancestor(repo, older, newer):
    return git(repo, 'merge-base', '--is-ancestor', older, newer, optional=True) is not None


def operations(repo):
    found = []
    for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply'):
        path = Path(txt(repo, 'rev-parse', '--git-path', marker))
        if not path.is_absolute():
            path = Path(repo) / path
        if path.exists():
            found.append(marker)
    return found


def snapshot(repo, paths=()):
    root = Path(txt(repo, 'rev-parse', '--show-toplevel')).resolve()
    head = txt(repo, 'rev-parse', 'HEAD')
    status = git(repo, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    merges = git(repo, 'rev-parse', '--verify', 'MERGE_HEAD', optional=True)
    result = {
        'repo': str(root), 'branch': txt(repo, 'branch', '--show-current'),
        'head_sha': head, 'operations': operations(repo),
        'merge_parents': merges.decode().splitlines() if merges else [],
        'status': [x for x in status.decode('utf-8', 'replace').split('\0') if x],
        'index_diff_sha256': diff_hash(repo, '--cached', head),
        'unstaged_diff_sha256': diff_hash(repo),
        'refs': {name: resolve(repo, 'origin/' + name) for name in ('main', 'dev', 'hyfan-main-before')},
        'reference_freshness': 'local_refs_only_no_fetch',
    }
    fingerprints = {}
    for relative in paths:
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError('Fingerprint path escapes repository')
        parts = path.relative_to(root).parts
        if any(p == '.git' or p.startswith('.env') for p in parts) or path.suffix.lower() in ('.pem', '.key'):
            raise ValueError('Do not fingerprint secret/config paths')
        fingerprints[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    result['source_fingerprints'] = fingerprints
    return result


def gate(repo, record, component, phase):
    snap = snapshot(repo)
    blockers = []
    row = record.get('repos', {}).get(component, {})
    status = record.get('status')
    if not record.get('batch_id') or not record.get('scope'):
        blockers.append('missing_batch_identity_or_scope')
    if status not in ('draft', 'testing', 'ready', 'partially_published'):
        blockers.append('batch_not_active')
    if row.get('involved') is not True:
        blockers.append('component_not_marked_involved')
    branch = snap['branch']
    if branch != 'hyfan-main-before' and not branch.startswith('hyfan/test-'):
        blockers.append('wrong_release_worktree')
    if git(repo, 'ls-files', '-u').strip():
        blockers.append('unresolved_conflicts')
    if phase == 'verify-commit':
        a = row.get('commit_approval') or {}
        parents = txt(repo, 'show', '-s', '--format=%P', snap['head_sha']).split()
        expected = [a.get('head_sha')] + (a.get('merge_parents') or [])
        if a.get('confirmed') is not True or not a.get('confirmation_ref'):
            blockers.append('commit_not_confirmed')
        if parents != expected:
            blockers.append('committed_parents_differ_from_approval')
        if not parents or a.get('index_diff_sha256') != diff_hash(repo, parents[0], snap['head_sha']):
            blockers.append('committed_content_differs_from_approval')
        if txt(repo, 'show', '-s', '--format=%B', snap['head_sha']) != (a.get('message') or '').strip():
            blockers.append('committed_message_differs_from_approval')
        if snap['status'] or snap['operations']:
            blockers.append('post_commit_worktree_not_clean')
    elif phase == 'commit':
        a = row.get('commit_approval') or {}
        if a.get('confirmed') is not True or not a.get('confirmation_ref'):
            blockers.append('commit_message_and_diff_not_confirmed')
        if a.get('head_sha') != snap['head_sha']:
            blockers.append('head_changed_since_confirmation')
        if a.get('merge_parents') != snap['merge_parents']:
            blockers.append('merge_parents_changed_since_confirmation')
        if a.get('index_diff_sha256') != snap['index_diff_sha256']:
            blockers.append('staged_content_changed_or_unconfirmed')
        message = a.get('message') or ''
        if not message or not CONVENTIONAL.fullmatch(message.splitlines()[0]):
            blockers.append('invalid_conventional_commit_message')
        if any(x != 'MERGE_HEAD' for x in snap['operations']):
            blockers.append('operation_in_progress')
        if git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--name-only').strip():
            blockers.append('unstaged_changes_in_release_worktree')
        if git(repo, 'ls-files', '--others', '--exclude-standard', '-z').strip():
            blockers.append('untracked_files_in_release_worktree')
        if not git(repo, 'diff', '--cached', '--no-ext-diff', '--name-only').strip() and not snap['merge_parents']:
            blockers.append('nothing_to_commit')
    else:
        a = row.get('push_approval') or {}
        target, candidate = a.get('target'), a.get('candidate_sha')
        if a.get('confirmed') is not True or not a.get('confirmation_ref'):
            blockers.append('push_content_and_target_not_confirmed')
        if snap['status'] or snap['operations']:
            blockers.append('release_worktree_not_clean')
        if target not in ('main', 'dev', 'hyfan-main-before'):
            blockers.append('invalid_target')
            return {'phase': phase, 'blockers': blockers}
        expected_branch = branch.startswith('hyfan/test-') if target == 'dev' else branch == 'hyfan-main-before'
        if not expected_branch:
            blockers.append('target_worktree_mismatch')
        if not isinstance(candidate, str) or not FULL_SHA.fullmatch(candidate) or resolve(repo, candidate) != candidate:
            blockers.append('invalid_full_candidate_sha')
            return {'phase': phase, 'blockers': blockers}
        if candidate != snap['head_sha']:
            blockers.append('candidate_not_current_reviewed_head')
        remote_base = snap['refs'][target]
        base = a.get('base_sha')
        if base != remote_base or (not remote_base and target != 'hyfan-main-before'):
            blockers.append('target_baseline_changed_or_missing')
        # New candidate branch compares against main; absent main is not safe.
        compare_base = remote_base or snap['refs']['main']
        if not compare_base:
            blockers.append('missing_comparison_base')
        else:
            if not ancestor(repo, compare_base, candidate):
                blockers.append('not_fast_forward')
            if a.get('diff_sha256') != diff_hash(repo, compare_base, candidate):
                blockers.append('final_push_diff_changed_or_unconfirmed')
            names = txt(repo, 'diff', '--no-ext-diff', '--name-only', compare_base, candidate).splitlines()
            if any('/migrations/' in p for p in names) and row.get('migration_compatibility') != 'verified':
                blockers.append('migration_compatibility_not_verified')
        if target == 'dev':
            feature = row.get('candidate_sha')
            if not feature or not FULL_SHA.fullmatch(feature) or not resolve(repo, feature) or not ancestor(repo, feature, candidate):
                blockers.append('integration_does_not_include_recorded_candidate')
        if target == 'main':
            if status not in ('ready', 'partially_published'):
                blockers.append('batch_not_test_ready')
            if candidate != row.get('tested_candidate_sha') or candidate != row.get('candidate_sha') or not row.get('test_confirmation'):
                blockers.append('candidate_not_confirmed_tested')
            if row.get('tested_main_base_sha') != remote_base:
                blockers.append('main_changed_since_test')
            deployed = row.get('tested_deployment_sha')
            if not deployed or not FULL_SHA.fullmatch(deployed) or not resolve(repo, deployed) or not ancestor(repo, candidate, deployed):
                blockers.append('tested_deployment_does_not_include_candidate')
    return {'phase': phase, 'blockers': blockers, 'notice': 'Mechanical checks only; verify real user approval and fresh remote refs.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    snap = sub.add_parser('snapshot')
    snap.add_argument('--repo', required=True)
    snap.add_argument('--paths', nargs='*', default=[])
    check = sub.add_parser('gate')
    check.add_argument('--repo', required=True)
    check.add_argument('--record', required=True)
    check.add_argument('--component', choices=('backend', 'frontend'), required=True)
    check.add_argument('--phase', choices=('commit', 'verify-commit', 'push'), required=True)
    diff = sub.add_parser('review-diff')
    diff.add_argument('--repo', required=True)
    diff.add_argument('--base', required=True)
    diff.add_argument('--candidate', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'snapshot':
            result = snapshot(args.repo, args.paths)
        elif args.command == 'review-diff':
            base, candidate = resolve(args.repo, args.base), resolve(args.repo, args.candidate)
            if not base or not candidate:
                raise ValueError('Missing diff refs')
            result = {'base_sha': base, 'candidate_sha': candidate,
                      'diff_sha256': diff_hash(args.repo, base, candidate),
                      'paths': txt(args.repo, 'diff', '--no-ext-diff', '--name-only', base, candidate).splitlines()}
        else:
            result = gate(args.repo, json.loads(Path(args.record).read_text(encoding='utf-8-sig')), args.component, args.phase)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get('blockers') else 0
    except (ValueError, OSError, TypeError, AttributeError, KeyError):
        print(json.dumps({'error': 'Inspection failed; check repo access, refs and record schema. No mutation performed.'}))
        return 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
