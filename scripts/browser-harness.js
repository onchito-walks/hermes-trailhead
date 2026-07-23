#!/usr/bin/env node
/* Minimal, bounded CDP adapter. It uses only Node 22 built-ins. */
'use strict';

const cdpBase = process.env.TRAILHEAD_BROWSER_CDP_URL || 'http://127.0.0.1:19222';
const deadlineMs = Math.max(1000, Number(process.env.TRAILHEAD_BROWSER_HARNESS_TIMEOUT_MS || 40000));
const input = await readStdin();
const urlMatch = input.match(/goto_url\((['"])(.*?)\1\)/s);
if (!urlMatch) fail('browser-harness DSL did not contain goto_url(url)');
const url = urlMatch[2];
const timeoutMatch = input.match(/range\(1,\s*(\d+)\)/);
const settleAttempts = timeoutMatch ? Math.max(1, Number(timeoutMatch[1]) - 1) : 14;
const started = Date.now();

function fail(message) { console.error(message); process.exitCode = 1; }
function remaining() {
  const left = deadlineMs - (Date.now() - started);
  if (left <= 0) throw new Error('browser-harness timeout');
  return left;
}
async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}
async function fetchJson(path, options) {
  const response = await fetch(new URL(path, cdpBase), { ...options, signal: AbortSignal.timeout(remaining()) });
  if (!response.ok) throw new Error(`CDP HTTP ${response.status} for ${path}`);
  return response.json();
}
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

class Connection {
  constructor(ws) { this.ws = ws; this.nextId = 1; this.pending = new Map(); }
  command(method, params = {}, sessionId) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }
  dispatch(message) {
    if (!message.id || !this.pending.has(message.id)) return;
    const pending = this.pending.get(message.id); this.pending.delete(message.id);
    if (message.error) pending.reject(new Error(message.error.message || 'CDP command failed'));
    else pending.resolve(message.result || {});
  }
  close() { for (const p of this.pending.values()) p.reject(new Error('CDP connection closed')); this.pending.clear(); this.ws.close(); }
}

let connection, targetId;
try {
  const browser = await fetchJson('/json/version');
  if (!browser.webSocketDebuggerUrl) throw new Error('CDP /json/version has no webSocketDebuggerUrl');
  const ws = new WebSocket(browser.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });
  connection = new Connection(ws);
  ws.addEventListener('message', event => { try { connection.dispatch(JSON.parse(event.data)); } catch (_) {} });
  const target = await connection.command('Target.createTarget', { url: 'about:blank', background: false });
  targetId = target.targetId;
  const { sessionId } = await connection.command('Target.attachToTarget', { targetId, flatten: true });
  const command = (method, params = {}) => connection.command(method, params, sessionId);
  await command('Page.enable');
  await command('Runtime.enable');
  await command('Page.navigate', { url });
  await sleep(500);
  let body = '', title = '';
  for (let i = 0; i < settleAttempts && Date.now() - started < deadlineMs; i++) {
    await sleep(800);
    const result = await command('Runtime.evaluate', {
      expression: '({title: document.title || "", body: (document.body && document.body.innerText) || ""})',
      returnByValue: true,
    });
    const value = result.result && result.result.value;
    title = value && value.title || '';
    body = value && value.body || '';
    if (body.length > 50) break;
  }
  if (!body || body.length < 10) throw new Error('NO_VISIBLE_TEXT');
  if (title) console.log(`TITLE: ${title}`);
  console.log(body.length > 8000 ? `${body.slice(0, 8000)}...` : body);
  await connection.command('Target.closeTarget', { targetId });
  connection.close();
} catch (error) {
  fail(error && error.message ? error.message : String(error));
  if (connection) connection.close();
}
