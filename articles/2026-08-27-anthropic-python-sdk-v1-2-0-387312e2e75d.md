---
title: "Anthropic Python SDK v1.2.0"
date: 2026-08-27
source: Anthropic Python SDK Releases
source_url: https://github.com/anthropics/anthropic-sdk-python/releases/tag/v1.2.0
---

# Anthropic Python SDK v1.2.0

Direct SDK release from Anthropic (Tier 1) with concrete API consistency improvements and a critical fix for AWS Bedrock file uploads.

<h2>1.2.0 (2026-08-27)</h2>
<p>Full Changelog: <a href="https://github.com/anthropics/anthropic-sdk-python/compare/v1.1.0...v1.2.0">v1.1.0...v1.2.0</a></p>
<h3>Features</h3>
<ul>
<li><strong>api:</strong> beta files/skills namespaces use GA shapes; drop dated beta header pins (<a href="https://github.com/anthropics/anthropic-sdk-python/commit/9df4565fdfe4eec941809a0a3d1615ee11e16b68">9df4565</a>)</li>
</ul>
<h3>Bug Fixes</h3>
<ul>
<li><strong>aws,bedrock:</strong> sign raw request bytes so binary file uploads work (<a href="https://github.com/anthropics/anthropic-sdk-python/issues/531">#531</a>) (<a href="https://github.com/anthropics/anthropic-sdk-python/commit/f50e9106c002d71966f5f8027758b3d703999936">f50e910</a>)</li>
<li><strong>ci:</strong> resolve assignment aliases in detect-breaking-changes (<a href="https://github.com/anthropics/anthropic-sdk-python/commit/f2c49254941b4d700fe97cbe6bb85205b06a6460">f2c4925</a>)</li>
<li><strong>sessions:</strong> make event accumulator forward-compatible with new event types (<a href="https://github.com/anthropics/anthropic-sdk-python/issues/533">#533</a>) (<a href="https://github.com/anthropics/anthropic-sdk-python/commit/cbbaf6e46358d5c844eac01ed3c50a797daf93a7">cbbaf6e</a>)</li>
<li><strong>tools:</strong> let read return a view_range of a file over the size cap (<a href="https://github.com/anthropics/anthropic-sdk-python/issues/538">#538</a>) (<a href="https://github.com/anthropics/anthropic-sdk-python/commit/b68e876345bde1ecc099ef245e87b1319dc8d080">b68e876</a>)</li>
<li><strong>tools:</strong> preserve exact file bytes in the agent toolset and memory tool (no newline translation) (<a href="https://github.com/anthropics/anthropic-sdk-python/issues/540">#540</a>) (<a href="https://github.com/anthropics/anthropic-sdk-python/commit/56921a8c04e0ec71192fcd22dd28db2a5e1306f7">56921a8</a>)</li>
<li><strong>webhooks:</strong> require headers to be passed to <code>unwrap()</code> (<a href="https://github.com/anthropics/anthropic-sdk-python/commit/0baa90225359f6b4bec50476c19bb52c2ad4250d">0baa902</a>)</li>
</ul>
<h3>Documentation</h3>
<ul>
<li><strong>api:</strong> clarify pagination on the organization rate-limit list endpoints (<a href="https://github.com/anthropics/anthropic-sdk-python/commit/1832b27d0751943640cb898bb77c088ea3f24acb">1832b27</a>)</li>
</ul>

This story surfaced via Anthropic Python SDK Releases. For the original details and any numbers we have not confirmed here, follow the source below.

## Sources

- [Anthropic Python SDK Releases](https://github.com/anthropics/anthropic-sdk-python/releases/tag/v1.2.0)

