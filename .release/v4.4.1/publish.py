"""Publish only the exact, already tested 4.4.1 files using this repository's token."""
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

REPOSITORY = 'gatshcrypto/planner-releases'
TAG = 'v4.4.1'
ROOT = Path(__file__).resolve().parent
EXPECTED = {
    'PlannerSetup.exe': (2031616, 'b2bd04ae4fb12c6cc3734ebb436e91b3e918db9141ab1fb97135b142d9b94b92'),
    'Planner-4.4.1-Sources.zip': (2541441, '9860f4823fbb744b164a857917e3c726d3d53bf4fcf4451142277432851114de'),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


def api(path, method='GET', data=None, payload=None):
    origin = 'https://uploads.github.com' if payload is not None else 'https://api.github.com'
    headers = {'User-Agent': 'PlannerVerifiedRelease', 'Accept': 'application/vnd.github+json',
               'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'X-GitHub-Api-Version': '2022-11-28'}
    body = None
    if payload is not None:
        body = payload
        headers['Content-Type'] = 'application/octet-stream'
    elif data is not None:
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(origin + path, data=body, headers=headers, method=method)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
        return json.load(response)


def optional(path):
    try:
        return api(path)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def verify_assets(release):
    assets = {item['name']: item for item in release.get('assets', [])}
    for name, (size, digest) in EXPECTED.items():
        asset = assets.get(name)
        if not asset or asset.get('size') != size or asset.get('digest') != 'sha256:' + digest:
            raise RuntimeError('Release asset size or checksum mismatch: ' + name)


def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise RuntimeError('This publisher is restricted to its owner repository.')
    files = {}
    for name, (size, digest) in EXPECTED.items():
        content = (ROOT / name).read_bytes()
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise RuntimeError('The payload differs from the verified build: ' + name)
        files[name] = content
    base = '/repos/' + REPOSITORY + '/releases'
    latest = optional(base + '/latest')
    if latest:
        version = tuple(map(int, latest['tag_name'].lstrip('v').split('.')))
        if version > (4, 4, 1):
            raise RuntimeError('A newer planner release exists; refusing to replace latest.')
    release = optional(base + '/tags/' + TAG)
    if release is None:
        release = next((item for item in api(base + '?per_page=50') if item['tag_name'] == TAG), None)
    if release is None:
        release = api(base, 'POST', {'tag_name': TAG, 'target_commitish': os.environ['GITHUB_SHA'],
            'name': 'Планер 4.4.1', 'body': (ROOT / 'RELEASE.txt').read_text(encoding='utf-8-sig'),
            'draft': True, 'prerelease': False})
    for name, content in files.items():
        asset = next((item for item in release.get('assets', []) if item['name'] == name), None)
        if asset is None:
            asset = api(base + '/' + str(release['id']) + '/assets?name=' + name, 'POST', payload=content)
        expected_size, expected_digest = EXPECTED[name]
        if asset.get('size') != expected_size or asset.get('digest') != 'sha256:' + expected_digest:
            raise RuntimeError('Existing or uploaded asset does not match; nothing was overwritten: ' + name)
        print('Verified uploaded asset:', name)
    release = api(base + '/' + str(release['id']))
    verify_assets(release)
    if release.get('draft') or release.get('prerelease') or not latest or latest['tag_name'] != TAG:
        release = api(base + '/' + str(release['id']), 'PATCH', {'draft': False, 'prerelease': False, 'make_latest': 'true'})
    # Verify public metadata without forwarding the repository credential to download hosts.
    with urllib.request.urlopen(urllib.request.Request('https://api.github.com' + base + '/latest',
            headers={'User-Agent': 'PlannerPublicVerification'}), timeout=45) as response:
        public = json.load(response)
    if public['tag_name'] != TAG or public.get('draft') or public.get('prerelease'):
        raise RuntimeError('The update is not the latest stable release.')
    verify_assets(public)
    asset = next(item for item in public['assets'] if item['name'] == 'PlannerSetup.exe')
    with urllib.request.urlopen(urllib.request.Request(asset['browser_download_url'],
            headers={'User-Agent': 'PlannerPublicVerification'}), timeout=60) as response:
        downloaded = response.read(EXPECTED['PlannerSetup.exe'][0] + 1)
    if hashlib.sha256(downloaded).hexdigest() != EXPECTED['PlannerSetup.exe'][1]:
        raise RuntimeError('The public download differs from the verified installer.')
    print(json.dumps({'published': True, 'url': public['html_url'], 'installer': asset['browser_download_url'],
                      'sha256': EXPECTED['PlannerSetup.exe'][1]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
