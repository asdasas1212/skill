#!/usr/bin/env python3
"""Build/verify explicit migration bundles; rewrite only a separate text copy."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def relative(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or '..' in p.parts or str(p) == '.':
        raise ValueError('Archive path must be a nonempty relative path: ' + value)
    return str(p)


def git_output(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def add_file(files, source, target):
    source = Path(source)
    target = relative(target)
    if source.is_symlink():
        raise ValueError('Symlink requires explicit relocation handling: ' + str(source))
    if source.is_dir():
        for child in sorted(source.iterdir()):
            add_file(files, child, str(PurePosixPath(target) / child.name))
    elif source.is_file():
        if target == 'manifest.json':
            raise ValueError('manifest.json is reserved')
        if target in files and files[target] != source:
            raise ValueError('Conflicting archive path: ' + target)
        files[target] = source
    else:
        raise ValueError('Missing or unsupported source: ' + str(source))


def pack(args):
    output = Path(args.output)
    if output.exists() or Path(str(output) + '.sha256').exists():
        raise ValueError('Bundle or checksum already exists')
    files = {}
    repositories = []
    if args.spec:
        for item in json.loads(Path(args.spec).read_text())['items']:
            add_file(files, item['source'], item['target'])
    for value in args.git_repo:
        source, sep, target = value.partition('=')
        if not sep:
            raise ValueError('--git-repo requires SOURCE=ARCHIVE_PATH')
        root = Path(source).resolve()
        gitdir = root / '.git'
        if not gitdir.is_dir() or gitdir.is_symlink():
            raise ValueError('Only a standalone repository with ordinary .git is supported')
        if (gitdir / 'objects/info/alternates').exists() or (root / '.gitmodules').exists():
            raise ValueError('Submodules/alternate object stores require a self-contained snapshot')
        if any(gitdir.rglob('*.lock')):
            raise ValueError('Git lock present; wait until the repository is idle')
        actual_root = git_output(root, 'rev-parse', '--show-toplevel').decode().strip()
        if Path(actual_root).resolve() != root:
            raise ValueError('Specify the repository root')
        names = git_output(root, 'ls-files', '-c', '-o', '--exclude-standard', '-z')
        for name in sorted(set(names.split(b'\0')) - {b''}):
            rel = os.fsdecode(name)
            p = root / rel
            if p.exists() or p.is_symlink():
                add_file(files, p, str(PurePosixPath(target) / rel))
        add_file(files, gitdir, str(PurePosixPath(target) / '.git'))
        repositories.append({
            'target': relative(target),
            'head': git_output(root, 'rev-parse', 'HEAD').decode().strip(),
            'status': git_output(root, 'status', '--porcelain=v1', '-uno').decode(),
            'unstaged_diff_sha256': hashlib.sha256(git_output(root, 'diff', '--binary')).hexdigest(),
            'staged_diff_sha256': hashlib.sha256(git_output(root, 'diff', '--cached', '--binary')).hexdigest(),
        })
    if not files:
        raise ValueError('No files selected')
    # A file must not also be an ancestor of another selected path.
    for name in files:
        if any(str(parent) in files for parent in PurePosixPath(name).parents):
            raise ValueError('File/directory archive collision: ' + name)
    rows = []
    for target, source in sorted(files.items()):
        s = source.stat()
        rows.append({'path': target, 'bytes': s.st_size, 'sha256': digest(source),
                     'mode': stat.S_IMODE(s.st_mode)})
    manifest = {'format': 'codex-session-file-bundle-v1', 'files': rows,
                'git_repositories': repositories}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as raw:
        with tarfile.open(fileobj=raw, mode='w:gz', compresslevel=3) as archive:
            for row in rows:
                source = files[row['path']]
                archive.add(source, arcname=row['path'], recursive=False)
                if digest(source) != row['sha256']:
                    raise ValueError('Source changed during snapshot: ' + row['path'])
            data = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
            entry = tarfile.TarInfo('manifest.json')
            entry.size = len(data)
            entry.mode = 0o600
            archive.addfile(entry, io.BytesIO(data))
    checksum = digest(output)
    with Path(str(output) + '.sha256').open('x') as stream:
        stream.write(checksum + '  ' + output.name + '\n')
    print(json.dumps({'archive': str(output), 'sha256': checksum,
                      'files': len(rows), 'bytes': sum(r['bytes'] for r in rows)}))


def unpack(args):
    if digest(args.archive) != args.sha256.lower():
        raise ValueError('Archive SHA-256 mismatch')
    destination = Path(args.destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination must not exist')
    with tarfile.open(args.archive) as archive:
        entries = archive.getmembers()
        names = [relative(e.name) for e in entries]
        if len(names) != len(set(names)) or any(not e.isfile() for e in entries):
            raise ValueError('Bundle must contain unique regular files only')
        for name in names:
            if any(str(parent) in names for parent in PurePosixPath(name).parents):
                raise ValueError('Unsafe file/ancestor collision')
        item = archive.extractfile('manifest.json')
        if item is None:
            raise ValueError('Missing manifest')
        manifest = json.load(item)
        if manifest.get('format') != 'codex-session-file-bundle-v1':
            raise ValueError('Unsupported bundle format')
        expected = {row['path']: row for row in manifest['files']}
        if len(expected) != len(manifest['files']) or set(names) != set(expected) | {'manifest.json'}:
            raise ValueError('Manifest/archive member mismatch')
        for row in manifest['files']:
            relative(row['path'])
        destination.mkdir(parents=True)
        for entry in entries:
            out = destination / entry.name
            out.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(entry) as source, out.open('xb') as target:
                shutil.copyfileobj(source, target)
            os.chmod(out, entry.mode & 0o777)
            if entry.name in expected:
                row = expected[entry.name]
                if out.stat().st_size != row['bytes'] or digest(out) != row['sha256']:
                    raise ValueError('File checksum mismatch: ' + entry.name)
    for repo in manifest.get('git_repositories', []):
        root = destination / relative(repo['target'])
        actual = {'head': git_output(root, 'rev-parse', 'HEAD').decode().strip(),
                  'status': git_output(root, 'status', '--porcelain=v1', '-uno').decode(),
                  'unstaged_diff_sha256': hashlib.sha256(git_output(root, 'diff', '--binary')).hexdigest(),
                  'staged_diff_sha256': hashlib.sha256(git_output(root, 'diff', '--cached', '--binary')).hexdigest()}
        if any(actual[k] != repo[k] for k in actual):
            raise ValueError('Git state mismatch: ' + repo['target'])
    print(json.dumps({'destination': str(destination), 'verified_files': len(expected),
                      'verified_git_repositories': len(manifest.get('git_repositories', []))}))


def rewrite(args):
    source, output = Path(args.input), Path(args.output)
    if source.resolve() == output.resolve():
        raise ValueError('Keep the original; select a different output')
    mapping = json.loads(Path(args.mapping).read_text())
    if not isinstance(mapping, dict) or not mapping or any(
            not isinstance(k, str) or not k or not isinstance(v, str)
            for k, v in mapping.items()):
        raise ValueError('Mapping must be a nonempty string-to-string object')
    pattern = re.compile('|'.join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
    text, count = pattern.subn(lambda m: mapping[m.group()], source.read_text())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        stream.write(text)
    print(json.dumps({'output': str(output), 'replacements': count,
                      'source_sha256': digest(source), 'output_sha256': digest(output)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('pack')
    p.add_argument('--spec')
    p.add_argument('--git-repo', action='append', default=[])
    p.add_argument('--output', required=True)
    p.set_defaults(run=pack)
    p = commands.add_parser('unpack')
    p.add_argument('--archive', required=True)
    p.add_argument('--destination', required=True)
    p.add_argument('--sha256', required=True)
    p.set_defaults(run=unpack)
    p = commands.add_parser('rewrite')
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--mapping', required=True)
    p.set_defaults(run=rewrite)
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
