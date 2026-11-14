"""对 login_demo 索引做向量、BM25、RRF 混合检索，并用真实模型生成带引用的回答。"""

import logging
import os
from pathlib import Path

from llama_index.core import Settings, StorageContext, load_index_from_storage
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import MetadataMode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.milvus import MilvusVectorStore
from openai import OpenAI

# milvus-lite 未实现 gRPC 的 AllocTimestamp，pymilvus 探测时会打出无害的 ERROR 堆栈
logging.getLogger("grpc._server").setLevel(logging.CRITICAL)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MILVUS_URI = PROJECT_ROOT / "milvus" / "login_demo.db"
STORAGE_DIR = PROJECT_ROOT / "rag" / "storage"
BM25_DIR = STORAGE_DIR / "bm25"

COLLECTION_NAME = "login_demo_chunks"
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
EMBED_DIM = 512
LLM_MODEL = "deepseek-flash"
TOP_K = 5
QUESTION = "登录会话的有效期是多少分钟？"


def source_of(node) -> str:
    file_path = node.metadata.get("file_path", "")
    try:
        return str(Path(file_path).relative_to(PROJECT_ROOT))
    except ValueError:
        return file_path or node.metadata.get("file_name", "unknown")


def print_results(title: str, score_name: str, results) -> None:
    print(f"\n===== {title}（前 {len(results)} 条）=====")
    for rank, item in enumerate(results, 1):
        snippet = item.node.get_content(metadata_mode=MetadataMode.NONE)
        snippet = " ".join(snippet.split())[:120]
        print(f"{rank}. [{score_name}={item.score:.4f}] 来源: {source_of(item.node)}")
        print(f"   {snippet}...")


def build_evidence(results) -> str:
    blocks = []
    for index, item in enumerate(results, 1):
        text = item.node.get_content(metadata_mode=MetadataMode.NONE).strip()
        blocks.append(f"[{index}] 来源：{source_of(item.node)}\n{text}")
    return "\n\n".join(blocks)


def main() -> None:
    Settings.llm = None
    Settings.embed_model = HuggingFaceEmbedding(
        model_name=EMBED_MODEL, device="cpu", embed_batch_size=16, max_length=512
    )

    vector_store = MilvusVectorStore(
        uri=str(MILVUS_URI),
        collection_name=COLLECTION_NAME,
        dim=EMBED_DIM,
        overwrite=False,
    )
    # 新进程打开本地 Milvus 时集合默认处于 released，检索前需要 load
    vector_store.client.load_collection(COLLECTION_NAME)
    storage_context = StorageContext.from_defaults(
        vector_store=vector_store, persist_dir=str(STORAGE_DIR)
    )
    index = load_index_from_storage(storage_context)

    vector_retriever = index.as_retriever(similarity_top_k=TOP_K)
    bm25_retriever = BM25Retriever.from_persist_dir(str(BM25_DIR))
    bm25_retriever.similarity_top_k = TOP_K
    hybrid_retriever = QueryFusionRetriever(
        [vector_retriever, bm25_retriever],
        similarity_top_k=TOP_K,
        mode=FUSION_MODES.RECIPROCAL_RANK,
        num_queries=1,
        use_async=False,
    )

    print(f"问题：{QUESTION}")
    vector_results = vector_retriever.retrieve(QUESTION)
    bm25_results = bm25_retriever.retrieve(QUESTION)
    hybrid_results = hybrid_retriever.retrieve(QUESTION)

    print_results("向量检索", "相似度", vector_results)
    print_results("BM25 检索", "BM25", bm25_results)
    print_results("RRF 混合检索", "RRF", hybrid_results)

    evidence = build_evidence(hybrid_results)
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com/v1",
    )
    prompt = (
        "你是严谨的文档问答助手。请只依据下面的证据回答问题，"
        "每个结论后面用 [编号] 标注引用来源；证据不足时直接说明。\n\n"
        f"问题：{QUESTION}\n\n证据：\n{evidence}\n\n"
        "请用中文简洁回答，并在结尾列出所引用的来源编号与文件名。"
    )
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    answer = response.choices[0].message.content

    print("\n===== 混合检索 + 真实模型回答 =====")
    print(answer)


if __name__ == "__main__":
    main()
