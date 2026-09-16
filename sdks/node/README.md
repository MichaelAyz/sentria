# Sentria Node.js Logging Client

Lightweight, buffered, non-blocking HTTP logging client with graceful degradation. Plugs directly into standard Node.js console, Winston, or Pino.

---

## Features

- **Zero External Dependencies**: Uses only Node.js built-in `http`/`https` modules.
- **Non-Blocking**: Logs are buffered in memory and flushed asynchronously.
- **Automatic Batching**: Flushes when `batchSize` is reached (default 50) or `flushInterval` expires (default 5s).
- **Graceful Degradation**: Network errors and service unreachability drop logs silently without throwing uncaught exceptions or crashing your Node.js server.
- **Winston & Pino Compatible**: Built-in adapter helpers for popular logging frameworks.

---

## Quickstart

```javascript
const { createHandler } = require('./sentria');

const sentria = createHandler({
  url: 'http://localhost:8000/ingest/raw',
  source: 'web-api-node',
  batchSize: 50,
  flushInterval: 5000,
});

// Direct logging
sentria.info('Server listening on port 3000');
sentria.error('FATAL: Database connection timeout');
sentria.warn('Approaching connection limit: 92%');

// Graceful shutdown
process.on('SIGTERM', async () => {
  await sentria.close();
  process.exit(0);
});
```

---

## Framework Integrations

### Winston
```javascript
const winston = require('winston');
const { createHandler } = require('./sentria');

const sentria = createHandler({
  url: 'http://localhost:8000/ingest/raw',
  source: 'express-app',
});

const logger = winston.createLogger({
  level: 'info',
  transports: [
    new winston.transports.Console(),
    sentria.winstonTransport(),
  ],
});
```

### Pino
```javascript
const pino = require('pino');
const { createHandler } = require('./sentria');

const sentria = createHandler({
  url: 'http://localhost:8000/ingest/raw',
  source: 'fastify-app',
});

const logger = pino(sentria.pinoStream());
```
