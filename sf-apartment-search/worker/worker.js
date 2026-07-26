/**
 * Cloudflare Worker: SF Apartment Search — Run Now trigger
 * ----------------------------------------------------------
 * This exists purely so the "Run search now" button on the website can
 * kick off the GitHub Action WITHOUT putting a GitHub token in public
 * client-side code. The token lives only here, as a Worker secret.
 *
 * Deploy steps are in SETUP.md. Summary:
 *   1. Create a GitHub fine-grained Personal Access Token with ONLY
 *      "Actions: Read and write" permission on this one repo.
 *   2. Create a Cloudflare Worker, paste this file in.
 *   3. Set two secrets on the Worker: GITHUB_TOKEN and GITHUB_REPO
 *      (e.g. "yourname/sf-apartment-search").
 *   4. Copy the Worker's URL into RUN_NOW_WORKER_URL in docs/index.html.
 */

export default {
  async fetch(request, env) {
    // Only allow POST, and only from your own site (adjust the origin
    // check once you know your GitHub Pages URL).
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const githubUrl = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/apartment-search.yml/dispatches`;

    const resp = await fetch(githubUrl, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "sf-apartment-search-worker",
      },
      body: JSON.stringify({ ref: "main" }),
    });

    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
    };

    if (resp.status === 204) {
      return new Response("Triggered", { status: 200, headers: corsHeaders });
    }

    const text = await resp.text();
    return new Response(`GitHub API error: ${resp.status} ${text}`, {
      status: 502,
      headers: corsHeaders,
    });
  },
};
