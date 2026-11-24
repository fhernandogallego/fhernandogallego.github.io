const assert = require('node:assert/strict');
const test = require('node:test');
const deploy = require('./deploy-pages.cjs');

function fixture({ runId = 7, statuses = ['succeed'], expired = false } = {}) {
  const calls = [];
  const outputs = {};
  const masked = [];
  const api = {
    context: { repo: { owner: 'example', repo: 'site' }, runId: 7, sha: 'commit-sha' },
    core: { getIDToken: async () => 'test-identity-token', setSecret: value => masked.push(value),
      info() {}, warning() {}, setOutput: (key, value) => { outputs[key] = value; } },
    github: { request: async (route, parameters) => {
      calls.push({ route, parameters });
      if (route.includes('/actions/artifacts/')) return { data: { name: 'github-pages', expired, workflow_run: { id: runId } } };
      if (route.endsWith('/cancel')) return { data: {} };
      if (route.startsWith('POST')) return { data: { id: 'deployment-1', page_url: 'https://example.com/' } };
      return { data: { status: statuses.shift() || 'deployment_in_progress' } };
    } }
  };
  return { api, calls, outputs, masked };
}
const options = { sleep: async () => {}, attempts: 3 };

test('deploys the exact uploaded ID, masks identity and waits for success', async () => {
  const f = fixture({ statuses: ['deployment_in_progress', 'succeed'] });
  await deploy(f.api, '42', options);
  assert.equal(f.calls[1].parameters.artifact_id, 42);
  assert.equal(f.calls[1].parameters.pages_build_version, 'commit-sha');
  assert.equal(f.calls[1].parameters.oidc_token, 'test-identity-token');
  assert.deepEqual(f.masked, ['test-identity-token']);
  assert.equal(f.outputs.page_url, 'https://example.com/');
  assert.equal(f.calls.length, 4);
});
test('rejects an absent uploaded ID before contacting the API', async () => {
  const f = fixture();
  await assert.rejects(deploy(f.api, undefined, options), /did not return/);
  assert.equal(f.calls.length, 0);
});
test('rejects artifacts belonging to another workflow', async () => {
  const f = fixture({ runId: 8 });
  await assert.rejects(deploy(f.api, '42', options), /does not belong/);
  assert.equal(f.calls.length, 1);
});
test('rejects expired artifacts', async () => {
  const f = fixture({ expired: true });
  await assert.rejects(deploy(f.api, '42', options), /unavailable/);
  assert.equal(f.calls.length, 1);
});
test('fails on deployment errors without reporting a URL', async () => {
  const f = fixture({ statuses: ['deployment_content_failed'] });
  await assert.rejects(deploy(f.api, '42', options), /deployment_content_failed/);
  assert.deepEqual(f.outputs, {});
});
test('cancels a deployment that never completes', async () => {
  const f = fixture({ statuses: [] });
  await assert.rejects(deploy(f.api, '42', options), /five minutes/);
  assert.ok(f.calls.at(-1).route.endsWith('/cancel'));
  assert.equal(f.calls.length, 6);
  assert.deepEqual(f.outputs, {});
});
