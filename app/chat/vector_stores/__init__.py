from functools import partial
from .pinecone import build_retriever, build_multi_doc_retriever

# Retriever map for single-doc and multi-doc modes
# The build_retriever function now handles both modes based on chat_args.mode
retriever_map = {
    "pinecone_1": partial(build_retriever, k=1),
    "pinecone_2": partial(build_retriever, k=2),
    "pinecone_3": partial(build_retriever, k=3),
    # Multi-doc retrievers with higher k for broader search
    "pinecone_multi_5": partial(build_retriever, k=5),
    "pinecone_multi_10": partial(build_retriever, k=10),
}