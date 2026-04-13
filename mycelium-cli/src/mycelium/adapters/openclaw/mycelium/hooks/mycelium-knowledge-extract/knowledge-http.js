/**
 * Knowledge ingest HTTP only — no process.env (see knowledge-env.js).
 */

export async function postKnowledgeIngest(apiUrl, body) {
  try {
    const res = await fetch(`${apiUrl}/api/knowledge/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch {
    return false;
  }
}
