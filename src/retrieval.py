from llama_index.core.retrievers import RecursiveRetriever  # type: ignore
from llama_index.core.query_engine import RetrieverQueryEngine  # type: ignore


def setup_recursive_retriever(top_index, child_query_engines):
    """
    Thiết lập RecursiveRetriever và QueryEngine cuối cùng.
    """
    # Retriever cho chỉ mục gốc (cấp Chương)
    top_retriever = top_index.as_retriever(similarity_top_k=10)

    # Tạo một từ điển retriever, trong đó "vector" là retriever mặc định
    retriever_dict = {"vector": top_retriever}

    # Khởi tạo RecursiveRetriever
    # Nó sẽ sử dụng top_retriever để tìm các node cấp cao (Chương).
    # Khi gặp một IndexNode, nó sẽ dùng index_id để tra trong query_engine_dict
    # và gọi query engine tương ứng để tìm kiếm sâu hơn.
    recursive_retriever = RecursiveRetriever(
        "vector",
        retriever_dict=retriever_dict,
        query_engine_dict=child_query_engines,
        verbose=True,
    )

    # Tạo query engine cuối cùng để người dùng tương tác
    query_engine = RetrieverQueryEngine.from_args(recursive_retriever)

    return query_engine
