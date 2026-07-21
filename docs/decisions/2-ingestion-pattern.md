# ADR 2: Ingestion Pattern (Push/Webhook-based direct-to-classify)

## Context
We need to determine how logs flow from their source into Sentria's classification service. In a full production system, logs might be collected by an agent (like Promtail or FluentBit), sent to a message queue or log aggregator (like Loki or Kafka), and then read by an inference worker. This introduces significant operational complexity (message queues, ingestion workers, state management, and network overhead) that is unnecessary for our goals.

## Decision
We will use a **Direct Push (Webhook-based)** model:
- The **Synthetic Log Generator** acts as the ingestion pipeline.
- It will batch logs (e.g., every 1–2 seconds or every N lines) and post them directly using HTTP POST to the classification service's `/classify` endpoint.
- In other words, "ingestion and inference share a transport".

## Consequences
- **Low Complexity**: No external message queues (like Kafka/RabbitMQ) or storage backends (like Loki) are required to transfer data.
- **Immediate Feedback**: Logs are processed as soon as they are generated, making the demonstration highly responsive.
- **Tight Coupling**: The generator is directly coupled to the FastAPI `/classify` API. If the classification service is down, the generator will experience failures. This is an acceptable trade-off for a lightweight standalone platform.
- **No Hidden Worker**: The generator is the ingestion client, and the FastAPI app is the inference server. No intermediate poller or file-tailer daemon is needed.
