const http = require('http');
const assert = require('assert');
const { createHandler } = require('./sentria');

async function runTests() {
  console.log('Running Node.js SDK tests...\n');

  // Test 1: Buffer and flush to a local mock HTTP server
  console.log('Test 1: Buffer and flush over HTTP...');
  let receivedRequests = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      receivedRequests.push({
        url: req.url,
        method: req.method,
        headers: req.headers,
        body: body,
      });
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok' }));
    });
  });

  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  const client = createHandler({
    url: `http://127.0.0.1:${port}/ingest/raw`,
    source: 'node-test-svc',
    batchSize: 100,
    flushInterval: 60000,
  });

  client.info('First test log');
  client.error('Second test error');

  assert.strictEqual(receivedRequests.length, 0, 'Should not flush immediately');
  await client.flush();

  assert.strictEqual(receivedRequests.length, 1, 'Should have sent 1 batch request');
  assert.ok(receivedRequests[0].url.includes('source=node-test-svc'), 'Should propagate source parameter');
  assert.ok(receivedRequests[0].body.includes('[INFO] First test log'), 'Should contain first log');
  assert.ok(receivedRequests[0].body.includes('[ERROR] Second test error'), 'Should contain second log');
  assert.strictEqual(client.sentCount, 2);
  console.log('✓ Test 1 passed\n');

  // Test 2: Batch size trigger
  console.log('Test 2: Automatic batch size trigger...');
  receivedRequests = [];
  const batchClient = createHandler({
    url: `http://127.0.0.1:${port}/ingest/raw`,
    source: 'batch-node-svc',
    batchSize: 3,
    flushInterval: 60000,
  });

  batchClient.log('Line 1');
  batchClient.log('Line 2');
  assert.strictEqual(receivedRequests.length, 0);

  batchClient.log('Line 3'); // Hits batchSize 3
  // Give async promise a microtask tick
  await new Promise(r => setTimeout(r, 100));

  assert.strictEqual(receivedRequests.length, 1);
  assert.ok(receivedRequests[0].body.includes('Line 1\nLine 2\nLine 3'));
  console.log('✓ Test 2 passed\n');

  // Test 3: Graceful degradation (unreachable endpoint)
  console.log('Test 3: Graceful degradation on connection error...');
  const deadClient = createHandler({
    url: 'http://127.0.0.1:1/ingest/raw', // Port 1 is refused
    source: 'dead-svc',
    batchSize: 100,
    flushInterval: 60000,
  });

  deadClient.error('Test error to dead port');
  // Should NOT throw or crash
  await deadClient.flush();
  assert.strictEqual(deadClient.droppedCount, 1);
  assert.strictEqual(deadClient.sentCount, 0);
  console.log('✓ Test 3 passed\n');

  // Test 4: Close flushes remaining
  console.log('Test 4: Close synchronously flushes remaining logs...');
  receivedRequests = [];
  const closeClient = createHandler({
    url: `http://127.0.0.1:${port}/ingest/raw`,
    source: 'close-svc',
    batchSize: 100,
    flushInterval: 60000,
  });

  closeClient.warn('Pending shutdown warning');
  await closeClient.close();

  assert.strictEqual(receivedRequests.length, 1);
  assert.ok(receivedRequests[0].body.includes('[WARN] Pending shutdown warning'));
  console.log('✓ Test 4 passed\n');

  // Clean up server
  await new Promise(resolve => server.close(resolve));
  console.log('All 4 Node.js SDK tests passed successfully!');
}

runTests().catch(err => {
  console.error('Node.js test failed:', err);
  process.exit(1);
});
