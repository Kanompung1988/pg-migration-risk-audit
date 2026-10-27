#!/usr/bin/env python3
"""Offline, read-only PostgreSQL migration heuristics. Never executes SQL."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAX_BYTES = 512 * 1024
MAX_FILES = 1000
SEVERITY = {"low": 1, "medium": 2, "high": 3, "critical": 4}


class InputError(Exception):
    pass


def mask_sql(text: str) -> str:
    """Mask SQL comments and literals preserving newlines and character positions.

    Understands doubled single/double quotes, nested block comments and dollar strings.
    Any unterminated construct fails closed rather than guessing statement boundaries.
    """
    out = list(text)
    i, n = 0, len(text)

    def blank(a: int, b: int) -> None:
        for j in range(a, b):
            if out[j] != '\n':
                out[j] = ' '

    while i < n:
        if text.startswith('--', i):
            end = text.find('\n', i)
            if end < 0:
                end = n
            blank(i, end)
            i = end
        elif text.startswith('/*', i):
            start, depth, i = i, 1, i + 2
            while i < n and depth:
                if text.startswith('/*', i):
                    depth += 1
                    i += 2
                elif text.startswith('*/', i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise InputError('Unterminated block comment')
            blank(start, i)
        elif text[i] in ("'", '"'):
            mark, start = text[i], i
            i += 1
            while i < n:
                if text[i] == mark:
                    if i + 1 < n and text[i + 1] == mark:
                        i += 2
                    else:
                        i += 1
                        break
                elif text[i] == '\\' and mark == "'" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            else:
                raise InputError('Unterminated SQL quoted literal')
            blank(start, i)
        elif text[i] == '$':
            m = re.match(r'\$[A-Za-z_][A-Za-z_0-9]*\$|\$\$', text[i:])
            if not m:
                i += 1
                continue
            tag, start = m.group(), i
            end = text.find(tag, i + len(tag))
            if end < 0:
                raise InputError('Unterminated dollar-quoted SQL literal')
            i = end + len(tag)
            blank(start, i)
        else:
            i += 1
    return ''.join(out)


def statements(text: str):
    cleaned = mask_sql(text)
    start = 0
    for idx, char in enumerate(cleaned):
        if char == ';':
            segment = cleaned[start:idx].strip()
            if segment:
                first = start + next((p for p,c in enumerate(cleaned[start:idx]) if not c.isspace()), 0)
                yield segment, text.count('\n', 0, first) + 1
            start = idx + 1
    segment = cleaned[start:].strip()
    if segment:
        first = start + next((p for p,c in enumerate(cleaned[start:]) if not c.isspace()), 0)
        yield segment, text.count('\n', 0, first) + 1


def tokenize(segment: str):
    """Uppercase SQL words, omit masked string bodies."""
    return [w.upper() for w in re.findall(r'[A-Za-z_][A-Za-z_0-9]*|[;,()]', segment)]


def audit_text(text: str, path: str):
    findings = []
    in_tx = False

    def add(rule: str, level: str, line: int, why: str, remedy: str):
        findings.append({"rule": rule, "severity": level, "path": path,
                         "line": line, "message": why, "recommendation": remedy})

    for sql, line in statements(text):
        words = tokenize(sql)
        if not words:
            continue
        first = words[0]
        if first in ('BEGIN', 'START') and (first == 'BEGIN' or words[:2] == ['START', 'TRANSACTION']):
            in_tx = True
            continue
        if first in ('COMMIT', 'ROLLBACK', 'END'):
            in_tx = False
            continue
        if words[:2] in (['DROP', 'TABLE'], ['DROP', 'SCHEMA']):
            add('PG001', 'critical', line, 'DROP TABLE/SCHEMA may irreversibly remove data.',
                'Validate dependencies, backups, rollout sequence and explicit approval.')
        if words[:2] == ['ALTER', 'TABLE'] and 'DROP' in words:
            for j in range(2, len(words)-1):
                if words[j] == 'DROP' and words[j+1] in ('COLUMN','CONSTRAINT'):
                    add('PG002', 'high', line, 'ALTER TABLE DROP COLUMN/CONSTRAINT changes existing schema.',
                        'Use expand/contract migration and check consumer compatibility first.')
                    break
        if words[:2] == ['TRUNCATE', 'TABLE'] or first == 'TRUNCATE':
            add('PG003', 'critical', line, 'TRUNCATE removes all rows from targeted tables.',
                'Require explicit production data-loss review and verified recovery plan.')
        if first in ('UPDATE','DELETE') and len(words)>1 and (first!='DELETE' or words[1]=='FROM'):
            if 'WHERE' not in words:
                add('PG004', 'high', line, f'{first} statement has no WHERE clause.',
                    'Verify bulk modification is intended, and use a bounded reviewed migration.')
        if len(words)>2 and words[0]=='CREATE' and 'INDEX' in words[:4]:
            if 'CONCURRENTLY' not in words[:6]:
                add('PG005', 'medium', line, 'CREATE INDEX without CONCURRENTLY can block writers.',
                    'For large live tables evaluate CREATE INDEX CONCURRENTLY; assess tradeoffs.')
            elif in_tx:
                add('PG006', 'high', line, 'CREATE INDEX CONCURRENTLY is inside an explicit transaction block.',
                    'Move the concurrent index operation outside transaction blocks.')
        if len(words)>1 and words[:2] == ['ALTER','TABLE'] and 'TYPE' in words:
            add('PG007', 'medium', line, 'ALTER TABLE ... TYPE may require a rewrite and strong lock.',
                'Check PostgreSQL version, table size, lock duration and safe rollout.')
        if len(words)>1 and first in ('DROP','ALTER') and 'CASCADE' in words:
            add('PG008', 'high', line, 'CASCADE can affect dependent database objects.',
                'List dependent objects and review impact before deployment.')
    return findings


def scan(path: Path):
    if path.is_symlink():
        raise InputError('Symlink paths are not allowed')
    if not path.exists():
        raise InputError('Input path not found')
    if not (path.is_file() or path.is_dir()):
        raise InputError('Input must be a file or directory')
    if path.is_file():
        paths = [path]
    else:
        paths = []
        for p in sorted(path.rglob('*')):
            if any(part.startswith('.') or part in ('node_modules','vendor','dist','build') for part in p.relative_to(path).parts):
                continue
            if p.is_symlink():
                continue
            if p.is_file() and p.suffix.lower() == '.sql':
                paths.append(p)
                if len(paths) > MAX_FILES:
                    raise InputError('Too many .sql files (max 1000)')
    issues = []
    for file in paths:
        if file.stat().st_size > MAX_BYTES:
            raise InputError(f'Oversized SQL file: {file.name} (limit 512KiB)')
        try:
            text = file.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as e:
            raise InputError(f'Could not read {file.name}: {type(e).__name__}') from e
        rel = file.name if path.is_file() else file.relative_to(path).as_posix()
        try:
            issues.extend(audit_text(text, rel))
        except InputError as e:
            raise InputError(f'{rel}: {e}') from e
    return sorted(issues, key=lambda x: (x['path'],x['line'],x['rule']))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', help='SQL file or directory of .sql migrations')
    parser.add_argument('--format', choices=('json','markdown'), default='markdown')
    parser.add_argument('--fail-on', choices=('none','low','medium','high','critical'), default='high')
    ns=parser.parse_args(argv)
    try:
        found = scan(Path(ns.path))
    except InputError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1
    if ns.format == 'json':
        print(json.dumps({'findings': found, 'count': len(found)},indent=2))
    else:
        print('# PostgreSQL migration review\n')
        print('| Severity | Rule | Location | Review finding |\n|---|---|---|---|')
        for f in found:
            summary=f['message'].replace('|', '\\|')
            print(f"| {f['severity'].upper()} | {f['rule']} | {f['path']}:{f['line']} | {summary} |")
        print(f'\n{len(found)} finding(s); human migration review required.')
    return 2 if ns.fail_on!='none' and any(SEVERITY[f['severity']]>=SEVERITY[ns.fail_on] for f in found) else 0


if __name__=='__main__':
    raise SystemExit(main())
