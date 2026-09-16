/**
 * Sentria Node.js Logging Client & Transport
 * Lightweight, async, buffered logger with graceful degradation.
 * Zero external dependencies (uses Node.js built-in http/https only).
 */
const http = require('http');
const https = require('https');
const { URL } = require('url');

class SentriaClient {
  constructor(options = {}) {
    this.url = options.url || 'http://localhost:8000/ingest/raw';
    this.source = options.source || 'node-app';
    this.batchSize = options.batchSize || 50;
    this.flushInterval = options.flushInterval || 5000;
    this.maxBufferSize = options.maxBufferSize || 10000;
    this.timeout = options.timeout || 3000;

    this.buffer = [];
    this.isClosed = false;

    // Telemetry & error throttling
    this.sentCount = 0;
    this.droppedCount = 0;
    this.lastErrorTime = 0;
    this.errorThrottleMs = 60000;

    // Background timer for periodic flushing
    this.timer = setInterval(() => {
      this.flush().catch(() => {});
    }, this.flushInterval);

    // Ensure timer doesn't prevent Node process from exiting
    if (this.timer.unref) {
      this.timer.unref();
    }
  }

  log(message) {
    if (this.isClosed) return;

    const formatted = typeof message === 'object' 
      ? JSON.stringify(message) 
      : String(message);

    if (this.buffer.length < this.maxBufferSize) {
      this.buffer.push(formatted);
    } else {
      this._recordDrop(1, 'Buffer capacity exceeded');
    }

    if (this.buffer.length >= this.batchSize) {
      this.flush().catch(() => {});
    }
  }

  info(msg) {
    this.log(`[INFO] ${msg}`);
  }

  warn(msg) {
    this.log(`[WARN] ${msg}`);
  }

  error(msg) {
    this.log(`[ERROR] ${msg}`);
  }

  async flush() {
    if (this.buffer.length === 0) return;

    const items = this.buffer.splice(0, this.buffer.length);
    const payload = items.join('\n');
    if (!payload.trim()) return;

    const parsedUrl = new URL(this.url);
    if (!parsedUrl.searchParams.has('source')) {
      parsedUrl.searchParams.set('source', this.source);
    }

    const isHttps = parsedUrl.protocol === 'https:';
    const client = isHttps ? https : http;

    return new Promise((resolve) => {
      const req = client.request(
        parsedUrl,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'text/plain; charset=utf-8',
            'User-Agent': 'sentria-node-handler/1.0',
            'Content-Length': Buffer.byteLength(payload, 'utf8'),
          },
          timeout: this.timeout,
        },
        (res) => {
          res.resume(); // Consume response to free memory
          if (res.statusCode >= 200 && res.statusCode < 300) {
            this.sentCount += items.length;
          } else {
            this._recordDrop(items.length, `HTTP ${res.statusCode}`);
          }
          resolve();
        }
      );

      req.on('timeout', () => {
        req.destroy(new Error('Request timed out'));
      });

      req.on('error', (err) => {
        this._recordDrop(items.length, err.message);
        resolve(); // Graceful degradation: never reject / crash host process
      });

      req.write(payload, 'utf8');
      req.end();
    });
  }

  _recordDrop(count, reason) {
    this.droppedCount += count;
    const now = Date.now();
    if (now - this.lastErrorTime > this.errorThrottleMs) {
      this.lastErrorTime = now;
      process.stderr.write(
        `[SentriaClient] Warning: Unable to send ${count} log(s) to ${this.url} (${reason}). ` +
        `Total dropped: ${this.droppedCount}. Degrading gracefully.\n`
      );
    }
  }

  async close() {
    this.isClosed = true;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    return this.flush();
  }

  // Integration helper for Winston
  winstonTransport() {
    const self = this;
    return {
      log(info, callback) {
        const msg = info[Symbol.for('message')] || info.message || JSON.stringify(info);
        self.log(msg);
        if (callback) callback();
      }
    };
  }

  // Integration helper for Pino
  pinoStream() {
    const self = this;
    return {
      write(chunk) {
        self.log(chunk.toString().trim());
      }
    };
  }
}

function createHandler(options) {
  return new SentriaClient(options);
}

module.exports = {
  SentriaClient,
  createHandler,
};
