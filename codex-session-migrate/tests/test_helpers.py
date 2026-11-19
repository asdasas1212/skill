import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


class MigrationHelpers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def helper(self, script, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *map(str, args)],
            text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def json_file(self, name, data):
        p = self.root / name
        p.write_text(json.dumps(data))
        return p

    def git(self, repo, *args):
        return subprocess.check_output(
            ['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL)

    def test_dirty_git_roundtrip(self):
        repo = self.root / 'repo'
        repo.mkdir()
        self.git(repo, 'init')
        (repo / 'model.py').write_text('original\n')
        self.git(repo, 'add', 'model.py')
        self.git(repo, '-c', 'user.name=Fixture',
                 '-c', 'user.email=fixture@example.invalid',
                 'commit', '-m', 'initial')
        (repo / 'model.py').write_text('staged\n')
        self.git(repo, 'add', 'model.py')
        (repo / 'model.py').write_text('staged and unstaged\n')
        (repo / 'draft.md').write_text('new research\n')
        (repo / '.gitignore').write_text('weights/\n')
        (repo / 'weights').mkdir()
        (repo / 'weights/model.pt').write_bytes(b'ignored')
        archive = self.root / 'snapshot.tgz'
        result = self.helper('file_bundle.py', 'pack', '--git-repo',
                             str(repo) + '=workspace/repo', '--output', archive)
        checksum = json.loads(result.stdout)['sha256']
        restored = self.root / 'restored'
        self.helper('file_bundle.py', 'unpack', '--archive', archive,
                    '--destination', restored, '--sha256', checksum)
        target = restored / 'workspace/repo'
        for args in [('status', '--porcelain=v1'), ('diff', '--binary'),
                     ('diff', '--cached', '--binary')]:
            self.assertEqual(self.git(repo, *args), self.git(target, *args))
        self.assertEqual((target / 'draft.md').read_text(), 'new research\n')
        self.assertFalse((target / 'weights').exists())
        self.helper('file_bundle.py', 'unpack', '--archive', archive,
                    '--destination', self.root / 'wrong',
                    '--sha256', '0' * 64, ok=False)
        self.assertFalse((self.root / 'wrong').exists())
        self.helper('file_bundle.py', 'unpack', '--archive', archive,
                    '--destination', restored, '--sha256', checksum, ok=False)

    def test_traversal_and_symlink_refused(self):
        source = self.root / 'draft'
        source.write_text('data')
        spec = self.json_file('unsafe.json', {
            'items': [{'source': str(source), 'target': '../escape'}]})
        self.helper('file_bundle.py', 'pack', '--spec', spec,
                    '--output', self.root / 'unsafe.tgz', ok=False)
        link = self.root / 'link'
        link.symlink_to(source)
        spec = self.json_file('link.json', {
            'items': [{'source': str(link), 'target': 'link'}]})
        self.helper('file_bundle.py', 'pack', '--spec', spec,
                    '--output', self.root / 'link.tgz', ok=False)
        archive = self.root / 'traversal.tgz'
        with tarfile.open(archive, 'w:gz') as tar:
            entry = tarfile.TarInfo('../escape')
            entry.size = 1
            tar.addfile(entry, io.BytesIO(b'x'))
        self.helper('file_bundle.py', 'unpack', '--archive', archive,
                    '--destination', self.root / 'bad-restore', '--sha256',
                    hashlib.sha256(archive.read_bytes()).hexdigest(), ok=False)
        self.assertFalse((self.root / 'escape').exists())

    def test_overlapping_path_rewrite_keeps_original(self):
        source = self.root / 'source.jsonl'
        original = '/old/project/code /old/alias/design'
        source.write_text(original)
        mapping = self.json_file('map.json', {
            '/old/project': '/old/project/migrated',
            '/old/alias': '/old/project/migrated'})
        output = self.root / 'import.jsonl'
        self.helper('file_bundle.py', 'rewrite', '--input', source,
                    '--output', output, '--mapping', mapping)
        self.assertEqual(source.read_text(), original)
        self.assertEqual(output.read_text(),
                         '/old/project/migrated/code /old/project/migrated/design')
        self.helper('file_bundle.py', 'rewrite', '--input', source,
                    '--output', source, '--mapping', mapping, ok=False)

    def test_compare_rejects_incomplete_and_changed_history(self):
        data = {'thread': {'turns': [{'id': 'turn-1', 'status': 'completed',
                'items': [{'id': 'item-1', 'type': 'userMessage'},
                          {'id': 'item-2', 'type': 'agentMessage'}]}]}}
        source = self.json_file('source.json', data)
        destination = self.json_file('destination.json', data)
        result = self.helper('codex_rpc.py', 'compare', '--source', source,
                             '--destination', destination,
                             '--output', self.root / 'verification.json')
        self.assertEqual(json.loads(result.stdout)['items_preserved'], 2)
        data['thread']['turns'][0]['itemsView'] = 'summary'
        destination.write_text(json.dumps(data))
        self.helper('codex_rpc.py', 'compare', '--source', source,
                    '--destination', destination,
                    '--output', self.root / 'incomplete.json', ok=False)
        del data['thread']['turns'][0]['itemsView']
        data['thread']['turns'][0]['items'][1]['id'] = 'different'
        destination.write_text(json.dumps(data))
        self.helper('codex_rpc.py', 'compare', '--source', source,
                    '--destination', destination,
                    '--output', self.root / 'different.json', ok=False)

    def fake_server(self, fail=False):
        server = self.root / 'fake-codex'
        server.write_text('#!' + sys.executable + '\n' + '''
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    result = {'server': 'fixture'} if request['method'] == 'initialize' else {'data': []}
    response = {'id': request['id'], 'result': result}
''' + ("    if request['method'] != 'initialize': response = {'id': request['id'], 'error': {'code': -32600, 'message': 'fixture failure'}}\n" if fail else '') + '''
    # A notification and response arrive in the same read.
    sys.stdout.write(json.dumps({'method': 'fixture/notification'}) + '\\n' + json.dumps(response) + '\\n')
    sys.stdout.flush()
''')
        server.chmod(0o700)
        return server

    def test_rpc_framing_and_failure_receipt(self):
        requests = self.json_file('requests.json', [
            {'method': 'thread/list', 'params': {'limit': 1}}])
        server = self.fake_server()
        output = self.root / 'success.json'
        self.helper('codex_rpc.py', 'call', '--codex', server,
                    '--requests', requests, '--output', output, '--timeout', 2)
        receipt = json.loads(output.read_text())
        self.assertEqual(receipt['calls'][0]['status'], 'completed')
        server = self.fake_server(fail=True)
        output = self.root / 'failure.json'
        self.helper('codex_rpc.py', 'call', '--codex', server,
                    '--requests', requests, '--output', output, '--timeout', 2, ok=False)
        receipt = json.loads(output.read_text())
        self.assertEqual(receipt['calls'][0]['status'], 'failed_or_unknown')
        self.assertIn('fixture failure', receipt['calls'][0]['error'])

    def test_terminal_interrupted_history_is_preserved(self):
        data = {'thread': {'turns': [
            {'id': 'interrupted-old-turn', 'status': 'interrupted', 'items': []},
            {'id': 'latest-turn', 'status': 'completed',
             'items': [{'id': 'answer', 'type': 'agentMessage'}]}]}}
        source = self.json_file('source.json', data)
        destination = self.json_file('destination.json', data)
        self.helper('codex_rpc.py', 'compare', '--source', source,
                    '--destination', destination,
                    '--output', self.root / 'terminal.json')
        data['thread']['turns'][-1]['status'] = 'inProgress'
        destination.write_text(json.dumps(data))
        self.helper('codex_rpc.py', 'compare', '--source', source,
                    '--destination', destination,
                    '--output', self.root / 'running.json', ok=False)


if __name__ == '__main__':
    unittest.main()
