declare const Netlify: any;

const OWNER = "volcanofir";
const REPO = "banqiao-house-monitor";
const WORKFLOW = "monitor-clean.yml";

export default async () => {
  const token = Netlify.env.get("GH_WORKFLOW_TOKEN");
  if (!token) throw new Error("Missing GH_WORKFLOW_TOKEN");

  const res = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "banqiao-monitor-wakeup",
    },
    body: JSON.stringify({ ref: "main" }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`GitHub dispatch failed: ${res.status} ${body}`);
  }

  console.log(`Triggered ${OWNER}/${REPO} workflow ${WORKFLOW} at ${new Date().toISOString()}`);
};

// TEMP TEST: every 5 minutes. After verification, change to the production 3-hour schedule.
export const config = {
  schedule: "*/5 * * * *",
};
