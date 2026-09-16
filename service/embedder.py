import os
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from typing import List, Union

class MiniLMEmbedder:
    """
    Production-grade MiniLM sentence embedder running via ONNX Runtime & Tokenizers.
    Zero PyTorch or sentence-transformers dependencies at runtime.
    Produces exact 384-dimensional normalized embeddings.
    """
    def __init__(
        self, 
        model_path: str = None, 
        tokenizer_path: str = None,
        quantized: bool = False,
        max_length: int = 128
    ):
        base_dir = os.path.join(os.path.dirname(__file__), "onnx")
        
        if model_path is None:
            model_name = "model_quantized.onnx" if quantized else "model.onnx"
            model_path = os.path.join(base_dir, model_name)
            
        if tokenizer_path is None:
            tokenizer_path = os.path.join(base_dir, "tokenizer.json")
            
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ONNX model not found at {model_path}")
        if not os.path.exists(tokenizer_path):
            raise FileNotFoundError(f"Tokenizer not found at {tokenizer_path}")
            
        self.model_path = model_path
        self.tokenizer_path = tokenizer_path
        self.max_length = max_length
        self.quantized = quantized
        
        # Configure ONNX Runtime session for optimal CPU latency
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 2
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        
        self.session = ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=self.max_length)
        self.tokenizer.enable_padding(length=self.max_length)

    def embed(self, texts: Union[str, List[str]], batch_size: int = 64) -> np.ndarray:
        """
        Embed a single text or a list of texts into normalized 384-dim vectors.
        """
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            return np.empty((0, 384), dtype=np.float32)
            
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            encoded = self.tokenizer.encode_batch(batch)
            
            input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            token_type_ids = np.array([e.type_ids for e in encoded], dtype=np.int64)
            
            # Run inference
            inputs = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids
            }
            outputs = self.session.run(None, inputs)
            last_hidden_state = outputs[0]  # (batch_size, seq_len, 384)
            
            # Mean pooling over attention mask
            input_mask_expanded = np.expand_dims(attention_mask, -1).astype(np.float32)
            sum_embeddings = np.sum(last_hidden_state * input_mask_expanded, axis=1)
            sum_mask = np.clip(input_mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
            mean_pooled = sum_embeddings / sum_mask
            
            # L2 Normalization (so cosine similarity = dot product)
            norms = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
            norms = np.clip(norms, a_min=1e-9, a_max=None)
            normalized = mean_pooled / norms
            all_embeddings.append(normalized.astype(np.float32))
            
        return np.vstack(all_embeddings)
