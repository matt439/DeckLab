'use strict';
// Headless-only browser boundary shared by the disposable rendered review suites.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');

const FIXTURE_TYPE = 'decklab-ui-review-v1';
const PLAYWRIGHT_VERSION = '1.65.0';
const LIMITATIONS = [
  'Disposable synthetic data only; all simulation payloads, scores and ordering are invented.',
  'Browser contexts are temporary, headless and isolated from the user browser profile.',
  'Chromium emulation does not qualify physical touch, Safari, screen readers or software keyboards.',
  'CSS root-font 200% is layout stress, not browser zoom or OS text scaling.',
  'Screenshots require human inspection; DOM readiness is not visual acceptance.',
  'Synthetic card images do not qualify artwork recognition; offscreen lazy images may be unloaded.',
  'Synthetic result adapters do not qualify backend result authorization, real Forge or deep Details.',
];

function argumentsFor(argv) {
  const result = { smoke: false };
  const values = new Map([
    ['--runtime', 'runtime'], ['--output', 'output'], ['--run-id', 'runId'], ['--browser', 'browser'],
  ]);
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (key === '--smoke') {
      assert.equal(result.smoke, false, 'Duplicate --smoke');
      result.smoke = true;
    } else if (key === '--strict-console') {
      assert(!result.strictConsole, 'Duplicate --strict-console');
      result.strictConsole = true;
    } else {
      assert(values.has(key), 'Unknown review worker argument');
      const name = values.get(key);
      assert(!Object.hasOwn(result, name), 'Duplicate review worker argument');
      assert(i + 1 < argv.length && !argv[i + 1].startsWith('--'), 'Missing worker argument value');
      result[name] = argv[++i];
    }
  }
  for (const name of ['runtime', 'output', 'runId', 'browser']) {
    assert.equal(typeof result[name], 'string', 'Required review worker argument is missing');
    assert(result[name].length > 0, 'Empty review worker argument');
  }
  assert(/^[A-Za-z0-9_-]{16,128}$/.test(result.runId), 'Invalid disposable run token');
  return result;
}

function readReady(options) {
  const runtime = fs.realpathSync(options.runtime);
  assert(fs.statSync(runtime).isDirectory(), 'Runtime must be a directory');
  function runtimeFile(value, required) {
    assert.equal(typeof value, 'string', 'Fixture control path must be a string');
    const resolved = path.resolve(value);
    assert.equal(fs.realpathSync(path.dirname(resolved)), runtime, 'Control must be directly inside runtime');
    if (required) {
      assert(fs.statSync(resolved).isFile(), 'Fixture control must be a regular file');
      assert.equal(fs.realpathSync(resolved), resolved, 'Fixture control must not be a symlink');
    }
    return resolved;
  }
  const readyFile = runtimeFile(path.join(runtime, 'ready.json'), true);
  const ready = JSON.parse(fs.readFileSync(readyFile, 'utf8').replace(/^\uFEFF/, ''));
  assert(ready && typeof ready === 'object' && !Array.isArray(ready), 'Invalid fixture readiness object');
  assert.equal(ready.fixture_type, FIXTURE_TYPE, 'Refusing an unrecognized fixture type');
  assert.equal(ready.run_id, options.runId, 'Disposable run token does not match');
  assert.equal(typeof ready.base_url, 'string', 'Invalid fixture base URL type');
  const base = new URL(ready.base_url);
  assert.equal(base.protocol, 'http:', 'Only a plain HTTP disposable fixture is allowed');
  assert.equal(base.hostname, '127.0.0.1', 'Only the disposable IPv4 loopback fixture is allowed');
  assert(base.port && Number(base.port) > 0, 'Fixture must use an explicit ephemeral port');
  assert.notEqual(Number(base.port), 8642, 'Refusing the ordinary Deck Lab listener port');
  assert(!base.username && !base.password && !base.search && !base.hash && base.pathname === '/',
    'Fixture URL must contain only its loopback origin');
  const profileControl = runtimeFile(ready.profile_control, true);
  const caseControl = runtimeFile(ready.case_control, true);
  const stopFile = runtimeFile(ready.stop_file, false);
  const cancelFile = runtimeFile(path.join(runtime, 'cancel-file'), false);
  assert(!fs.existsSync(stopFile), 'Disposable fixture is already stopped');
  assert(!fs.existsSync(cancelFile), 'Review was already cancelled');
  assert(ready.routes && typeof ready.routes === 'object' && !Array.isArray(ready.routes), 'Missing fixture routes');
  for (const name of ['home_variant', 'member_variant', 'board', 'pair', 'editor', 'receipt']) {
    assert.equal(typeof ready.routes[name], 'string', 'Fixture route must be a string');
    assert(/^\/?#\//.test(ready.routes[name]), 'Only local hash routes are allowed');
  }
  assert(path.isAbsolute(options.browser), 'Browser executable must be an absolute path');
  assert(fs.statSync(options.browser).isFile(), 'Installed browser executable is missing');
  return { ready, runtime, base, profileControl, caseControl, stopFile, cancelFile };
}

function verifyServer(config, runId) {
  return new Promise((resolve, reject) => {
    const req = http.get(new URL('/_ui_review/ready', config.base), {
      timeout: 5000, headers: { 'X-DeckLab-Review-Run': runId },
    }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => {
        body += chunk;
        if (body.length > 4096) req.destroy(new Error('Oversized disposable identity response'));
      });
      response.on('end', () => {
        try {
          assert.equal(response.statusCode, 200, 'Disposable server identity endpoint refused');
          assert(/^application\/json\b/.test(response.headers['content-type'] || ''), 'Expected JSON fixture identity');
          const identity = JSON.parse(body);
          assert.equal(identity.fixture_type, FIXTURE_TYPE, 'Server fixture type does not match');
          assert.equal(identity.run_id, runId, 'Server disposable run token does not match');
          assert.equal(identity.isolated, true, 'Server is not an isolated fixture');
          resolve();
        } catch (error) { reject(error); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('Disposable server identity check timed out')));
    req.on('error', reject);
  });
}

class Review {
  constructor(suite, options) {
    this.suite = suite;
    this.options = options;
    this.config = readReady(options); // All local guards run before loading or launching a browser.
    this.origin = this.config.base.origin;
    this.out = path.join(path.resolve(options.output), suite);
    assert(!fs.existsSync(this.out), 'Suite output already exists; choose a fresh output directory');
    fs.mkdirSync(this.out, { recursive: true });
    this.originalProfile = fs.readFileSync(this.config.profileControl, 'utf8');
    this.originalCase = fs.readFileSync(this.config.caseControl, 'utf8');
    assert(['matt', 'user2'].includes(this.originalProfile.trim()), 'Invalid synthetic fixture profile');
    assert(['complete', 'stale', 'failed', 'running'].includes(this.originalCase.trim()), 'Invalid fixture case');
    this.contexts = new Set();
    this.report = {
      schema_version: 1, suite, fixture_type: FIXTURE_TYPE, synthetic: true,
      headless: true, no_native_input: true, smoke: options.smoke, strict_console: Boolean(options.strictConsole),
      browser_version: null, playwright_core_version: PLAYWRIGHT_VERSION,
      limitations: LIMITATIONS,
      network: { allowed_reads: 0, dry_checks: 0, blocked: [] },
      cleanup: { browser_started: false, browser_closed: false, contexts_closed: false,
        controls_restored: false, cancelled: false },
      completed: false,
    };
  }

  safeUrl(raw) {
    try {
      const parsed = new URL(raw, this.origin);
      return parsed.origin === this.origin ? parsed.pathname + parsed.search + parsed.hash : '[external origin]';
    } catch (_) { return '[invalid URL]'; }
  }

  safeText(value) {
    let text = String(value);
    for (const privateValue of [this.options.runId, this.config.runtime, this.options.browser,
      this.origin, this.out, __dirname]) {
      text = text.split(privateValue).join(privateValue === this.origin ? '' : '[local]');
      text = text.split(privateValue.replaceAll('\\', '/')).join('[local]');
    }
    return text.replace(/https?:\/\/[^\s"'<>]+/g, value => this.safeUrl(value))
      .replace(/[A-Za-z]:[\\/][^\s"'<>]*/g, '[local path]')
      .replace(/\bpid[=: ]+\d+\b/gi, '[process]');
  }

  safe(value) {
    if (typeof value === 'string') return this.safeText(value);
    if (Array.isArray(value)) return value.map(item => this.safe(item));
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, this.safe(item)]));
    }
    return value;
  }

  save() {
    fs.writeFileSync(path.join(this.out, 'summary.json'), JSON.stringify(this.safe(this.report), null, 2) + '\n');
  }

  checkCancelled() {
    if (this.report.cleanup.cancelled || fs.existsSync(this.config.cancelFile) || fs.existsSync(this.config.stopFile)) {
      this.report.cleanup.cancelled = true;
      throw new Error('Review cancelled');
    }
  }

  async start() {
    this.checkCancelled();
    await verifyServer(this.config, this.options.runId);
    this.checkCancelled();
    assert.equal(require('playwright-core/package.json').version, PLAYWRIGHT_VERSION,
      'Run the explicit dependency setup to install the pinned playwright-core version');
    const { chromium } = require('playwright-core');
    this.browser = await chromium.launch({ headless: true, executablePath: this.options.browser, args: [
      '--disable-background-networking', '--no-first-run', '--disable-default-apps',
    ] });
    this.report.cleanup.browser_started = true;
    this.report.browser_version = this.browser.version();
    this.cancel = () => {
      this.report.cleanup.cancelled = true;
      if (this.browser?.isConnected()) this.browser.close().catch(() => {});
    };
    this.timer = setInterval(() => {
      if (fs.existsSync(this.config.cancelFile) || fs.existsSync(this.config.stopFile)) this.cancel();
    }, 200);
    this.timer.unref();
    process.on('SIGINT', this.cancel);
    process.on('SIGTERM', this.cancel);
    this.save();
  }

  select(profile = 'matt', fixtureCase = 'complete') {
    this.checkCancelled();
    assert(['matt', 'user2'].includes(profile), 'Unknown synthetic profile');
    assert(['complete', 'stale', 'failed', 'running', 'unknown-counts', 'library-failed'].includes(fixtureCase), 'Unknown synthetic case');
    fs.writeFileSync(this.config.profileControl, profile, 'utf8');
    fs.writeFileSync(this.config.caseControl, fixtureCase, 'utf8');
  }

  async context({ width, height, coarse = false, theme = 'light' }) {
    this.checkCancelled();
    const context = await this.browser.newContext({
      viewport: { width, height }, deviceScaleFactor: 2,
      isMobile: coarse, hasTouch: coarse, colorScheme: theme,
      reducedMotion: 'reduce', acceptDownloads: false, serviceWorkers: 'block',
      locale: 'en-AU', timezoneId: 'Australia/Brisbane',
    });
    return this.guardContext(context);
  }

  async guardContext(context) {
    // Also used by an owned, temporary-profile zoom experiment. Keep identical
    // read/write/origin guards instead of making browser qualification a bypass.
    this.contexts.add(context);
    context.on('close', () => this.contexts.delete(context));
    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      const same = url.origin === this.origin;
      const check = same && method === 'POST' && ['/api/deck/check', '/api/deck/cuts'].includes(url.pathname);
      if (!same || (!['GET', 'HEAD'].includes(method) && !check)) {
        const telemetry = same && method === 'POST' && ['/api/visit', '/api/errors/report'].includes(url.pathname);
        this.report.network.blocked.push({ method, url: this.safeUrl(url.href),
          category: telemetry ? 'expected_fixture_telemetry' : 'unexpected_blocked_request' });
        // Suppress the beacon inside the browser boundary: no app route or database write.
        // Aborting expected telemetry generates a browser console error and spoils strict smoke.
        if (telemetry) return route.fulfill({status: 204, body: ''});
        return route.abort('blockedbyclient');
      }
      this.report.network[check ? 'dry_checks' : 'allowed_reads']++;
      return route.continue();
    });
    return context;
  }

  observe(page, errors, httpErrors) {
    page.on('pageerror', error => errors.push(this.safeText(error.message)));
    if (this.options?.strictConsole) page.on('console', message => {
      if (message.type() === 'error') errors.push('Console error: ' + this.safeText(message.text()));
    });
    page.on('response', response => {
      if (response.status() < 400) return;
      const url = new URL(response.url());
      const status = response.status();
      const knownGap = status === 404 && url.pathname === '/api/deck'
        && url.searchParams.get('id') === 'casual/synthetic-opponent'
        || status === 403 && url.pathname === '/api/gauntlet/catalogue';
      const selectedCase = fs.readFileSync(this.config.caseControl, 'utf8').trim();
      const expectedState = status === 503 && (url.pathname === '/api/gauntlet/board' && selectedCase === 'failed'
        || url.pathname === '/api/decks' && selectedCase === 'library-failed');
      httpErrors.push({ url: this.safeUrl(response.url()), status,
        category: knownGap ? 'expected_fixture_gap' : expectedState ? 'expected_failure_state' : 'unexpected_http_error' });
    });
  }

  pageUrl(route, theme = 'light') {
    assert(/^\/?#\//.test(route), 'Expected a local hash route');
    return this.origin + '/?theme=' + theme + route.replace(/^\//, '');
  }

  async readFixture(context, pathname) {
    // APIRequestContext bypasses page routing: only an explicit same-origin relative GET is permitted here.
    assert(typeof pathname === 'string' && pathname.startsWith('/') && !pathname.startsWith('//'), 'Expected a local API path');
    const url = new URL(pathname, this.origin);
    assert.equal(url.origin, this.origin);
    assert(['/api/deck/edit', '/api/deck/draft', '/api/profiles/matt/wishlist', '/api/receipt'].includes(url.pathname),
      'Unapproved fixture proof read');
    this.checkCancelled();
    const response = await context.request.get(url.href, { timeout: 15000, maxRedirects: 0 });
    assert(response.ok(), 'Fixture proof GET failed: ' + url.pathname + ' ' + response.status());
    return response.json();
  }

  assertNetwork() {
    assert(!this.report.network.blocked.some(row => row.category === 'unexpected_blocked_request'),
      'Unexpected write or external origin was blocked');
  }

  async finish() {
    clearInterval(this.timer);
    if (this.cancel) {
      process.off('SIGINT', this.cancel);
      process.off('SIGTERM', this.cancel);
    }
    const errors = [];
    for (const context of [...this.contexts]) {
      try { await context.close(); } catch (error) { errors.push(this.safeText(error.message)); }
    }
    if (this.browser) {
      try { await this.browser.close(); } catch (error) { errors.push(this.safeText(error.message)); }
    }
    const replacementsClosed = !this.report.zoomBrowsers
      || this.report.zoomBrowsers.every(row => row.started && row.closed);
    this.report.cleanup.browser_closed = (!this.browser || !this.browser.isConnected()) && replacementsClosed;
    this.report.browser_closed = this.report.cleanup.browser_closed;
    this.report.cleanup.contexts_closed = this.contexts.size === 0;
    try {
      fs.writeFileSync(this.config.profileControl, this.originalProfile, 'utf8');
      fs.writeFileSync(this.config.caseControl, this.originalCase, 'utf8');
      this.report.cleanup.controls_restored = fs.readFileSync(this.config.profileControl, 'utf8') === this.originalProfile
        && fs.readFileSync(this.config.caseControl, 'utf8') === this.originalCase;
    } catch (error) { errors.push(this.safeText(error.message)); }
    if (errors.length) this.report.cleanup.errors = errors;
    const latePageErrors = this.report.page_errors?.length
      || this.report.results?.some(result => result.page_errors?.length);
    if (!this.report.cleanup.browser_closed || !this.report.cleanup.contexts_closed
      || !this.report.cleanup.controls_restored || this.report.cleanup.cancelled || errors.length || latePageErrors) {
      this.report.completed = false;
      process.exitCode = 1;
    }
    this.save();
    console.log(JSON.stringify({ suite: this.suite, completed: this.report.completed,
      browser_closed: this.report.cleanup.browser_closed, cancelled: this.report.cleanup.cancelled,
      summary: this.suite + '/summary.json' }));
  }
}

async function run(suite, work) {
  let review;
  try {
    review = new Review(suite, argumentsFor(process.argv.slice(2)));
    await review.start();
    await work(review);
    review.checkCancelled();
    review.assertNetwork();
    review.report.completed = true;
  } catch (error) {
    process.exitCode = 1;
    if (review) {
      review.report.failure = review.safeText(error.message);
      console.error(JSON.stringify({ suite, failure: review.report.failure }));
    } else console.error(JSON.stringify({ suite, failure: error.code === 'ERR_ASSERTION'
      ? 'Review preflight rejected: ' + String(error.message).split('\n')[0]
      : 'Review preflight rejected: invalid arguments, readiness or local files' }));
  } finally {
    if (review) {
      try { await review.finish(); } catch (_) {
        process.exitCode = 1;
        console.error(JSON.stringify({ suite, failure: 'Could not persist browser cleanup summary' }));
      }
    }
  }
}

module.exports = { argumentsFor, readReady, Review, run };
