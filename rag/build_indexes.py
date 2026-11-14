"""为 login_demo 登录资料构建向量索引与 BM25 关键词索引。

- 向量索引：真实 Embedding（BAAI/bge-small-zh-v1.5）+ Milvus（本地 milvus-lite）
- BM25 索引：与向量索引共用同一批分块节点
"""

import json
import logging
from pathlib import Path

from llama_index.core import (
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import MetadataMode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.readers.file import HTMLTagReader
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.milvus import MilvusVectorStore

# milvus-lite 未实现 gRPC 的 AllocTimestamp，pymilvus 探测时会打出无害的 ERROR 堆栈
logging.getLogger("grpc._server").setLevel(logging.CRITICAL)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "login_demo"
MILVUS_URI = PROJECT_ROOT / "milvus" / "login_demo.db"
STORAGE_DIR = PROJECT_ROOT / "rag" / "storage"
BM25_DIR = STORAGE_DIR / "bm25"

COLLECTION_NAME = "login_demo_chunks"
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
EMBED_DIM = 512
CHUNK_SIZE = 384
CHUNK_OVERLAP = 64
# 中文没有空格分词，按单字切分交给 BM25，英文/数字按词切分
TOKEN_PATTERN = r"(?u)[A-Za-z0-9_.]+|[\u4e00-\u9fff]"

SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", ".git"}
READABLE_SUFFIXES = {".md", ".py", ".html", ".csv", ".pdf", ".txt", ".json"}


def collect_source_files() -> list[Path]:
    files = []
    for path in SOURCE_DIR.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(SOURCE_DIR).parts):
            continue
        if path.suffix.lower() in READABLE_SUFFIXES:
            files.append(path)
    return sorted(files)


def load_nodes(parser: SentenceSplitter):
    files = collect_source_files()
    documents = SimpleDirectoryReader(
        input_files=[str(f) for f in files],
        # SimpleDirectoryReader 默认把 .html 当纯文本读，这里改为提取正文
        file_extractor={".html": HTMLTagReader(tag="body")},
    ).load_data()
    nodes = parser.get_nodes_from_documents(documents)
    return files, documents, nodes


def build_vector_index(nodes, embed_model: HuggingFaceEmbedding) -> StorageContext:
    MILVUS_URI.parent.mkdir(parents=True, exist_ok=True)
    vector_store = MilvusVectorStore(
        uri=str(MILVUS_URI),
        collection_name=COLLECTION_NAME,
        dim=EMBED_DIM,
        similarity_metric="COSINE",
        overwrite=True,
    )
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    VectorStoreIndex(
        nodes=nodes,
        storage_context=storage_context,
        embed_model=embed_model,
        show_progress=True,
    )
    # docstore / index_store 元数据落盘，向量本身已写入 Milvus
    storage_context.persist(persist_dir=str(STORAGE_DIR))
    return storage_context


def build_bm25_index(nodes) -> BM25Retriever:
    retriever = BM25Retriever.from_defaults(
        nodes=nodes,
        similarity_top_k=3,
        language="en",
        skip_stemming=True,
        token_pattern=TOKEN_PATTERN,
    )
    BM25_DIR.mkdir(parents=True, exist_ok=True)
    retriever.persist(str(BM25_DIR))

    # llama-index 默认只持久化部分参数，补写分词配置，保证 from_persist_dir 可复现
    retriever_file = BM25_DIR / "retriever.json"
    saved = json.loads(retriever_file.read_text(encoding="utf-8"))
    saved.update(
        {
            "skip_stemming": True,
            "token_pattern": TOKEN_PATTERN,
            "language": "en",
        }
    )
    retriever_file.write_text(
        json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return retriever


def relative_source(node) -> str:
    file_path = node.metadata.get("file_path", "")
    try:
        return str(Path(file_path).relative_to(PROJECT_ROOT))
    except ValueError:
        return file_path or node.metadata.get("file_name", "unknown")


def main() -> None:
    Settings.llm = None
    Settings.embed_model = HuggingFaceEmbedding(
        model_name=EMBED_MODEL,
        device="cpu",
        embed_batch_size=16,
        max_length=512,
    )

    parser = SentenceSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        paragraph_separator="\n\n",
    )

    files, documents, nodes = load_nodes(parser)
    print(f"读取文件数: {len(files)}")
    print(f"文档数: {len(documents)}")
    print(f"节点数量: {len(nodes)}")

    storage_context = build_vector_index(nodes, Settings.embed_model)
    bm25_retriever = build_bm25_index(nodes)

    vector_count = storage_context.vector_store.client.get_collection_stats(
        COLLECTION_NAME
    )["row_count"]
    print(f"向量索引节点数: {vector_count}")
    print(f"BM25 索引节点数: {bm25_retriever.bm25.scores['num_docs']}")
    print(f"Milvus 数据文件: {MILVUS_URI}")
    print(f"BM25 索引目录: {BM25_DIR}")

    sample = nodes[0]
    print("\n示例分块:")
    print(f"来源: {relative_source(sample)}")
    print(f"节点ID: {sample.node_id}")
    print(f"内容:\n{sample.get_content(metadata_mode=MetadataMode.NONE)}")


if __name__ == "__main__":
    main()
