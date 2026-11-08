const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

export async function resilientFetch(url, options = {}, policy = {}) {
  const { attempts = 4, timeoutMs = 1000, baseDelayMs = 150, sleep = wait, random = Math.random } = policy;
  const headers = new Headers(options.headers || {});
  if ((options.method || "GET") !== "GET" && !headers.has("Idempotency-Key")) {
    headers.set("Idempotency-Key", globalThis.crypto.randomUUID());
  }
  for (let attempt = 0; attempt < attempts; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    let failure;
    try {
      headers.set("X-Retry-Attempt", String(attempt + 1));
      response = await fetch(url, { ...options, headers, signal: controller.signal });
    } catch (error) { failure = error; }
    finally { clearTimeout(timer); }
    const retryable = failure || [429, 502, 503, 504].includes(response.status);
    if (!retryable) return response;
    if (attempt + 1 === attempts) {
      if (failure) throw failure;
      return response;
    }
    await response?.body?.cancel().catch(() => {});
    await sleep(baseDelayMs * 2 ** attempt + random() * baseDelayMs);
  }
}
