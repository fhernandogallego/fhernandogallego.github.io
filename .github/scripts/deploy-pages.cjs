// Use the exact uploaded artifact ID; avoid the artifact SDK's failing name lookup.
module.exports = async function deployPages(
  { github, context, core }, artifactId,
  { sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), attempts = 60,
    artifactAttempts = 12 } = {}
) {
  if (!/^\d+$/.test(String(artifactId || ''))) {
    throw new Error('The upload step did not return a Pages artifact ID.');
  }
  const repository = context.repo;
  // Upload finalization can precede availability through the REST API.
  // Retry only a missing artifact, retaining the exact ID and run validation.
  let artifact;
  for (let attempt = 0; attempt < artifactAttempts; attempt++) {
    try {
      ({ data: artifact } = await github.request(
        'GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}',
        { ...repository, artifact_id: Number(artifactId) }
      ));
      break;
    } catch (error) {
      if (error.status !== 404 || attempt === artifactAttempts - 1) throw error;
      core.info(`Waiting for Pages artifact ${artifactId} to become available (${attempt + 1}/${artifactAttempts}).`);
      await sleep(5000);
    }
  }
  if (artifact.name !== 'github-pages' || artifact.expired ||
      String(artifact.workflow_run?.id) !== String(context.runId)) {
    throw new Error('Pages artifact does not belong to this workflow run or is unavailable.');
  }
  const identityToken = await core.getIDToken();
  core.setSecret(identityToken);
  const { data: deployment } = await github.request(
    'POST /repos/{owner}/{repo}/pages/deployments',
    { ...repository, artifact_id: Number(artifactId), pages_build_version: context.sha, oidc_token: identityToken }
  );
  const deploymentId = deployment.id || deployment.status_url?.split('/').pop() || context.sha;
  core.info(`Created Pages deployment ${deploymentId} from artifact ${artifactId}.`);
  let pending = true;
  try {
    for (let attempt = 0; attempt < attempts; attempt++) {
      await sleep(5000);
      const { data: result } = await github.request(
        'GET /repos/{owner}/{repo}/pages/deployments/{deployment_id}',
        { ...repository, deployment_id: deploymentId }
      );
      core.info(`Pages deployment status: ${result.status}`);
      if (result.status === 'succeed') {
        pending = false;
        core.setOutput('page_url', deployment.page_url);
        return;
      }
      if (['deployment_failed', 'deployment_content_failed', 'deployment_cancelled', 'deployment_lost'].includes(result.status)) {
        pending = false;
        throw new Error(`Pages deployment ended with status ${result.status}.`);
      }
    }
    throw new Error('Pages deployment did not complete within five minutes.');
  } catch (error) {
    if (pending) {
      try {
        await github.request('POST /repos/{owner}/{repo}/pages/deployments/{deployment_id}/cancel',
          { ...repository, deployment_id: deploymentId });
      } catch (_) {
        core.warning(`Could not cancel Pages deployment ${deploymentId}; check its status in GitHub.`);
      }
    }
    throw error;
  }
};
