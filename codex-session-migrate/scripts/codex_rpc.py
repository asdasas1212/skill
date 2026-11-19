#!/usr/bin/env python3
"""Explicit Codex migration RPC calls and exported-history comparison."""
import argparse
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

ALLOWED = {'thread/list', 'thread/read', 'thread/turns/list', 'thread/items/list',
           'thread/items/read', 'thread/fork', 'thread/resume', 'thread/name/set', 'thread/archive'}


class Client:
    def __init__(self, executable, timeout):
        self.process = subprocess.Popen([executable, 'app-server', '--stdio'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b''
        self.timeout = timeout
        self.sequence = 0

    def request(self, method, params):
        self.sequence += 1
        sequence = self.sequence
        data = json.dumps({'id': sequence, 'method': method, 'params': params}).encode() + b'\n'
        self.process.stdin.write(data)
        self.process.stdin.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                response = json.loads(line)
                if response.get('id') != sequence:
                    continue
                if 'error' in response:
                    raise RuntimeError(json.dumps(response['error'], ensure_ascii=False))
                return response['result']
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise RuntimeError('RPC timed out: ' + method + '; inspect target state before retrying')
            block = os.read(self.process.stdout.fileno(), 1024 * 1024)
            if not block:
                raise RuntimeError('App server disconnected; inspect target state before retrying')
            self.buffer += block

    def initialize(self):
        result = self.request('initialize', {
            'clientInfo': {'name': 'codex_session_migration', 'version': '1.0'},
            'capabilities': {'experimentalApi': True}})
        self.process.stdin.write(b'{"method":"initialized","params":{}}\n')
        self.process.stdin.flush()
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.selector.close()
        self.process.stdin.close()
        self.process.stdout.close()


def call(args):
    requests = json.loads(Path(args.requests).read_text())
    if not isinstance(requests, list) or not requests:
        raise ValueError('Provide a nonempty request array')
    for request in requests:
        if request.get('method') not in ALLOWED or not isinstance(request.get('params'), dict):
            raise ValueError('Unsupported migration request')
    # Reserve the report before executing any mutation. Save each completed response.
    with Path(args.output).open('x') as report:
        os.chmod(args.output, 0o600)
        results = {'calls': []}
        def save():
            report.seek(0)
            json.dump(results, report, ensure_ascii=False, indent=2)
            report.truncate()
            report.flush()
            os.fsync(report.fileno())
        save()
        client = Client(args.codex, args.timeout)
        try:
            results['initialize'] = client.initialize()
            save()
            for request in requests:
                entry = {'method': request['method'], 'status': 'pending'}
                results['calls'].append(entry)
                save()
                try:
                    entry['result'] = client.request(request['method'], request['params'])
                    entry['status'] = 'completed'
                    save()
                except Exception as exc:
                    entry['status'] = 'failed_or_unknown'
                    entry['error'] = str(exc)
                    save()
                    raise
        finally:
            client.close()
    print(json.dumps({'output': args.output, 'completed_calls': len(results['calls'])}))


def read_export(path):
    data = json.loads(Path(path).read_text())
    if 'calls' in data:
        results = [c['result'] for c in data['calls']
                   if c.get('method') == 'thread/read' and c.get('status') == 'completed']
        if len(results) != 1:
            raise ValueError('Comparison input must have exactly one completed thread/read')
        data = results[0]
    thread = data.get('thread', data)
    turns = thread.get('turns')
    if not isinstance(turns, list) or not turns:
        raise ValueError('No complete turns exported; load all pages first')
    pagination = thread.get('turnsPagination') or {}
    if (pagination.get('hasMore') or pagination.get('nextCursor') or
            pagination.get('hasLoadedOldest') is False or pagination.get('olderCursor')):
        raise ValueError('Incomplete turn pagination')
    signatures = []
    for turn in turns:
        page = turn.get('itemsPagination') or {}
        if turn.get('itemsView') in {'notLoaded', 'summary'} or page.get('hasMore') or page.get('nextCursor') or page.get('olderCursor') or page.get('hasLoadedOldest') is False:
            raise ValueError('Incomplete items; export all pages first')
        if turn.get('status') not in {'completed', 'interrupted', 'failed'} or not isinstance(turn.get('items'), list):
            raise ValueError('Turn still running, unknown status or missing items')
        items = turn['items']
        if not turn.get('id') or any(not i.get('id') or not i.get('type') for i in items):
            raise ValueError('Missing turn/item identity')
        signatures.append({'id': turn['id'], 'status': turn['status'],
                           'items': [(i['id'], i['type']) for i in items]})
    if len({t['id'] for t in signatures}) != len(signatures):
        raise ValueError('Duplicate turn identities')
    return signatures


def compare(args):
    source = read_export(args.source)
    destination = read_export(args.destination)
    if source != destination:
        raise ValueError('Turn/item IDs, types, order or completion status differ')
    result = {'signature_match': True, 'turns_preserved': len(source),
              'items_preserved': sum(len(t['items']) for t in source),
              'check': 'turn IDs/status and item IDs/types/order; text bytes not compared'}
    with Path(args.output).open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('call')
    p.add_argument('--codex', default='codex')
    p.add_argument('--requests', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--timeout', type=float, default=45)
    p.set_defaults(run=call)
    p = commands.add_parser('compare')
    p.add_argument('--source', required=True)
    p.add_argument('--destination', required=True)
    p.add_argument('--output', required=True)
    p.set_defaults(run=compare)
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
