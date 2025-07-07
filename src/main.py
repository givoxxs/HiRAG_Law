import os
from dotenv import load_dotenv

# Tải các biến môi trường (ví dụ: OPENAI_API_KEY)
load_dotenv()

from .parsing import parse_law_document
from .indexing import setup_models, build_hierarchical_index
from .retrieval import setup_recursive_retriever
from .database_manager import DatabaseManager


def main():
    # --- Giai đoạn 1: Cấu hình ---
    print("🚀 Starting Hierarchical RAG System")
    print("Setting up models...")
    setup_models()  # Cấu hình LLM và Embedding model

    # Initialize database manager
    db = DatabaseManager()

    # --- Giai đoạn 2: Xử lý và Đánh chỉ mục (HiIndex) với Database ---
    file_path = "data/bo_luat_dan_su_2015.docx"

    # Register document and get ID
    doc_id = db.register_document(file_path, "Bộ luật Dân sự 2015")

    # Check if processing is complete
    if db.is_cache_complete(doc_id):
        # FAST PATH: Load from database
        print("🚀 Loading from database...")
        law_tree = db.load_law_tree(doc_id)
        cached_indices = db.load_indices(doc_id)

        if law_tree and cached_indices:
            top_index, child_query_engines = cached_indices
            print("✅ Successfully loaded from database!")

            # Show database stats
            stats = db.get_database_stats()
            total_size = sum(stats["storage_size_mb"].values())
            print(f"📊 Database size: {total_size:.1f} MB")
            print(f"📊 Vector count: {stats['vectors']['total_vectors']}")
        else:
            print("⚠️ Database corrupted, rebuilding...")
            law_tree, top_index, child_query_engines = build_fresh_data(
                file_path, doc_id, db
            )
    else:
        # SLOW PATH: Build from scratch
        law_tree, top_index, child_query_engines = build_fresh_data(
            file_path, doc_id, db
        )

    # --- Giai đoạn 3: Thiết lập Truy vấn (HiRetrieval) ---
    print("Setting up recursive retriever...")
    query_engine = setup_recursive_retriever(top_index, child_query_engines)
    print("System is ready to query.")
    print("-" * 50)

    # --- Giai đoạn 4: Truy vấn ---
    run_queries(query_engine)


def build_fresh_data(file_path: str, doc_id: int, db: DatabaseManager):
    """Build fresh data and save to database."""
    print("🔨 Building fresh data...")

    # Parse document
    print(f"📄 Parsing document: {file_path}...")
    law_tree = parse_law_document(file_path)

    # Save parsed data to database
    print("💾 Saving law tree to database...")
    db.save_law_tree(doc_id, law_tree)

    # Build hierarchical index
    print("🏗️ Building hierarchical index...")
    top_index, child_query_engines = build_hierarchical_index(law_tree)

    # Save indices to database
    print("💾 Saving indices to database...")
    db.save_indices(doc_id, top_index, child_query_engines)

    print("✅ Index built and saved to database successfully.")
    return law_tree, top_index, child_query_engines


def run_queries(query_engine):
    """Run test queries."""
    test_queries = [
        "Quyền dân sự được xác lập từ các căn cứ nào?",
        "Doanh nghiệp có vốn đầu tư nước ngoài có những quyền gì?",
        "Các nguyên tắc cơ bản của pháp luật dân sự là gì?",
    ]

    for i, query_str in enumerate(test_queries, 1):
        print(f"\n🔍 Query {i}: {query_str}")
        response = query_engine.query(query_str)
        print("\nCâu trả lời:")
        print(response)
        print("-" * 50)


if __name__ == "__main__":
    main()

# python -m src.main
