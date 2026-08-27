const OWNER = "volcanofir";
const REPO = "banqiao-house-monitor";
const WORKFLOW = "monitor-clean.yml";
const STATE_URL = `https://raw.githubusercontent.com/${OWNER}/${REPO}/main/state/monitor-schedule.json`;
const MAX_AGE_MINUTES = 210;

async function githubFetch(path, env, init = {}) {
  return fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "banqiao-cloudflare-watchdog",
      ...(init.headers || {}),
    },
  });
}

async function probeGithubToken(env) {
  if (!env.GITHUB_TOKEN) {
    return {
      ok: false,
      status: "missing-secret",
      message: "GITHUB_TOKEN is not available to this Worker.",
    };
  }

  const response = await githubFetch(
    `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=1`,
    env,
  );

  if (!response.ok) {
    const text = await response.text();
    return {
      ok: false,
      status: "github-auth-failed",
      httpStatus: response.status,
      message: text.slice(0, 300),
    };
  }

  const data = await response.json();
  const latest = (data.workflow_runs || [])[0] || null;
  return {
    ok: true,
    status: "github-auth-ok",
    repository: `${OWNER}/${REPO}`,
    workflow: WORKFLOW,
    latestRun: latest
      ? {
          id: latest.id,
          status: latest.status,
          conclusion: latest.conclusion,
          event: latest.event,
          createdAt: latest.created_at,
        }
      : null,
  };
}

async function checkAndWake(env) {
  const stateResponse = await fetch(`${STATE_URL}?t=${Date.now()}`, {
    headers: { "Cache-Control": "no-cache" },
  });

  if (!stateResponse.ok) {
    throw new Error(`Cannot read monitor state: ${stateResponse.status}`);
  }

  const state = await stateResponse.json();
  const raw = state.lastSuccessfulFullCheckAt;
  if (!raw) throw new Error("Missing lastSuccessfulFullCheckAt");

  const last = new Date(raw);
  if (Number.isNaN(last.getTime())) throw new Error("Invalid lastSuccessfulFullCheckAt");

  const ageMinutes = (Date.now() - last.getTime()) / 60000;

  if (ageMinutes < MAX_AGE_MINUTES) {
    return {
      status: "healthy",
      lastSuccessfulFullCheckAt: raw,
      ageMinutes: Math.round(ageMinutes),
      thresholdMinutes: MAX_AGE_MINUTES,
    };
  }

  const runsResponse = await githubFetch(
    `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=10`,
    env,
  );

  if (!runsResponse.ok) {
    const text = await runsResponse.text();
    throw new Error(`Cannot inspect GitHub runs: ${runsResponse.status} ${text.slice(0, 300)}`);
  }

  const runs = await runsResponse.json();
  const active = (runs.workflow_runs || []).some((run) =>
    ["queued", "in_progress", "waiting", "pending", "requested"].includes(run.status),
  );

  if (active) {
    return {
      status: "already-running",
      lastSuccessfulFullCheckAt: raw,
      ageMinutes: Math.round(ageMinutes),
      thresholdMinutes: MAX_AGE_MINUTES,
    };
  }

  const dispatchResponse = await githubFetch(
    `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    env,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main" }),
    },
  );

  if (!dispatchResponse.ok) {
    const text = await dispatchResponse.text();
    throw new Error(`GitHub dispatch failed: ${dispatchResponse.status} ${text.slice(0, 500)}`);
  }

  return {
    status: "github-woken",
    lastSuccessfulFullCheckAt: raw,
    ageMinutes: Math.round(ageMinutes),
    thresholdMinutes: MAX_AGE_MINUTES,
  };
}

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(
      checkAndWake(env)
        .then((result) => console.log(JSON.stringify(result)))
        .catch((error) => console.error(error.stack || String(error))),
    );
  },

  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (url.searchParams.get("probe") === "github") {
        const result = await probeGithubToken(env);
        return Response.json(result, {
          status: result.ok ? 200 : 500,
          headers: { "Cache-Control": "no-store" },
        });
      }

      const result = await checkAndWake(env);
      return Response.json(result, {
        headers: { "Cache-Control": "no-store" },
      });
    } catch (error) {
      return Response.json(
        { status: "error", message: error.message },
        { status: 500, headers: { "Cache-Control": "no-store" } },
      );
    }
  },
};
