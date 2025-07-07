#!/usr/bin/env python3
"""
Database CLI Tool for HiRAG System

Commands:
- info: Show database statistics
- clear: Clear database
- inspect: Inspect specific document  
- list: List all documents
- rebuild: Rebuild specific document
- search: Search vectors (debugging)
- vacuum: Optimize database
"""

import sys
import argparse
from pathlib import Path
from .database_manager import DatabaseManager
import json


def cmd_info(db: DatabaseManager):
    """Show comprehensive database statistics."""
    print("🗄️ DATABASE INFORMATION")
    print("=" * 50)

    stats = db.get_database_stats()

    print(f"📊 Documents: {stats['documents']}")
    print(f"📊 Cache Status:")
    print(f"   - Parsed: {stats['cache_status']['parsed']}")
    print(f"   - Indexed: {stats['cache_status']['indexed']}")
    print(f"   - Embedded: {stats['cache_status']['embedded']}")

    print(f"📊 Hierarchy Nodes:")
    for level, count in stats["hierarchy"].items():
        print(f"   - {level}: {count}")

    print(f"📊 Vector Storage:")
    print(f"   - Collections: {stats['vectors']['collections']}")
    print(f"   - Total vectors: {stats['vectors']['total_vectors']}")

    print(f"📊 Storage Size:")
    total_size = sum(stats["storage_size_mb"].values())
    print(f"   - SQL DB: {stats['storage_size_mb']['sql_db']:.1f} MB")
    print(f"   - Vector DB: {stats['storage_size_mb']['vector_db']:.1f} MB")
    print(f"   - Objects: {stats['storage_size_mb']['objects']:.1f} MB")
    print(f"   - TOTAL: {total_size:.1f} MB")


def cmd_list(db: DatabaseManager):
    """List all documents in database."""
    import sqlite3

    conn = sqlite3.connect(db.sql_db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
    SELECT d.id, d.file_path, d.title, d.created_at, d.updated_at,
           c.parsing_done, c.indexing_done, c.embeddings_done, c.last_build
    FROM documents d
    LEFT JOIN cache_status c ON d.id = c.document_id
    ORDER BY d.created_at DESC
    """
    )

    results = cursor.fetchall()
    conn.close()

    if not results:
        print("📄 No documents found in database")
        return

    print("📄 DOCUMENTS IN DATABASE")
    print("=" * 80)

    for row in results:
        (
            doc_id,
            file_path,
            title,
            created,
            updated,
            parsing,
            indexing,
            embedding,
            last_build,
        ) = row

        status_icons = []
        if parsing:
            status_icons.append("📝")
        if indexing:
            status_icons.append("🏗️")
        if embedding:
            status_icons.append("🔮")

        status = "".join(status_icons) or "❌"

        print(f"ID: {doc_id} | {status} | {title}")
        print(f"   Path: {file_path}")
        print(f"   Created: {created}")
        if last_build:
            print(f"   Last Build: {last_build}")
        print()


def cmd_inspect(db: DatabaseManager, doc_id: int):
    """Inspect specific document details."""
    import sqlite3

    conn = sqlite3.connect(db.sql_db_path)
    cursor = conn.cursor()

    # Get document info
    cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    doc_result = cursor.fetchone()

    if not doc_result:
        print(f"❌ Document ID {doc_id} not found")
        return

    print(f"🔍 DOCUMENT INSPECTION - ID: {doc_id}")
    print("=" * 50)

    doc_id, file_path, file_hash, title, created, updated, metadata = doc_result
    print(f"Title: {title}")
    print(f"Path: {file_path}")
    print(f"Hash: {file_hash}")
    print(f"Created: {created}")
    print(f"Updated: {updated}")

    # Get cache status
    cursor.execute("SELECT * FROM cache_status WHERE document_id = ?", (doc_id,))
    cache_result = cursor.fetchone()

    if cache_result:
        _, parsing, indexing, embedding, last_build, build_stats = cache_result
        print(f"\n📊 Cache Status:")
        print(f"   - Parsing: {'✅' if parsing else '❌'}")
        print(f"   - Indexing: {'✅' if indexing else '❌'}")
        print(f"   - Embedding: {'✅' if embedding else '❌'}")
        print(f"   - Last Build: {last_build}")

        if build_stats:
            stats = json.loads(build_stats)
            print(f"   - Build Stats: {stats}")

    # Get hierarchy statistics
    cursor.execute(
        """
    SELECT level, COUNT(*) FROM hierarchy 
    WHERE document_id = ? 
    GROUP BY level 
    ORDER BY 
        CASE level
            WHEN 'part' THEN 1
            WHEN 'chapter' THEN 2
            WHEN 'section' THEN 3
            WHEN 'article' THEN 4
            WHEN 'clause' THEN 5
        END
    """,
        (doc_id,),
    )

    hierarchy_stats = cursor.fetchall()

    if hierarchy_stats:
        print(f"\n🏗️ Hierarchy Structure:")
        for level, count in hierarchy_stats:
            print(f"   - {level}: {count}")

    # Check vector collections
    collection_name = f"doc_{doc_id}_embeddings"
    try:
        collection = db.chroma_client.get_collection(collection_name)
        vector_count = collection.count()
        print(f"\n🔮 Vector Storage:")
        print(f"   - Collection: {collection_name}")
        print(f"   - Vector Count: {vector_count}")
    except:
        print(f"\n🔮 Vector Storage: Not found")

    conn.close()


def cmd_clear(db: DatabaseManager, doc_id: int = None):
    """Clear database cache."""
    if doc_id:
        print(f"🗑️ Clearing cache for document ID: {doc_id}")
        db.clear_document_cache(doc_id)
        print("✅ Document cache cleared")
    else:
        response = input("⚠️ Clear ALL database? This is irreversible! (yes/no): ")
        if response.lower() == "yes":
            # Clear everything
            import sqlite3
            import shutil

            conn = sqlite3.connect(db.sql_db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM hierarchy")
            cursor.execute("DELETE FROM cache_status")
            cursor.execute("DELETE FROM documents")

            conn.commit()
            conn.close()

            # Clear ChromaDB
            try:
                collections = db.chroma_client.list_collections()
                for collection in collections:
                    db.chroma_client.delete_collection(collection.name)
            except:
                pass

            # Clear objects
            if db.objects_dir.exists():
                shutil.rmtree(db.objects_dir)
                db.objects_dir.mkdir(exist_ok=True)

            print("✅ All database cleared")
        else:
            print("❌ Operation cancelled")


def cmd_rebuild(db: DatabaseManager, doc_id: int):
    """Rebuild specific document."""
    import sqlite3

    # Get document path
    conn = sqlite3.connect(db.sql_db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT file_path FROM documents WHERE id = ?", (doc_id,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        print(f"❌ Document ID {doc_id} not found")
        return

    file_path = result[0]

    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return

    print(f"🔨 Rebuilding document ID: {doc_id}")
    print(f"📄 File: {file_path}")

    # Clear existing cache
    db.clear_document_cache(doc_id)

    # Re-register document (will detect as changed)
    from .parsing import parse_law_document
    from .indexing import setup_models, build_hierarchical_index

    try:
        print("🚀 Setting up models...")
        setup_models()

        print("📄 Parsing document...")
        law_tree = parse_law_document(file_path)

        print("💾 Saving to database...")
        db.save_law_tree(doc_id, law_tree)

        print("🏗️ Building indices...")
        top_index, child_query_engines = build_hierarchical_index(law_tree)

        print("💾 Saving indices...")
        db.save_indices(doc_id, top_index, child_query_engines)

        print("✅ Document rebuilt successfully!")

    except Exception as e:
        print(f"❌ Rebuild failed: {e}")


def cmd_vacuum(db: DatabaseManager):
    """Optimize database performance."""
    print("🧹 Vacuuming database...")

    import sqlite3

    conn = sqlite3.connect(db.sql_db_path)

    # Get size before
    cursor = conn.cursor()
    cursor.execute(
        "SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()"
    )
    size_before = cursor.fetchone()[0]

    # VACUUM
    conn.execute("VACUUM")

    # Get size after
    cursor.execute(
        "SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()"
    )
    size_after = cursor.fetchone()[0]

    conn.close()

    saved = (size_before - size_after) / 1024 / 1024
    print(f"✅ Database vacuumed")
    print(f"💾 Space saved: {saved:.1f} MB")


def cmd_search(db: DatabaseManager, doc_id: int, query: str, top_k: int = 5):
    """Search vectors for debugging."""
    try:
        from .indexing import setup_models

        print(f"🔍 Searching vectors for doc {doc_id}: '{query}'")

        # Setup embedding model
        setup_models()
        from llama_index.core import Settings

        # Get query embedding
        query_embedding = Settings.embed_model.get_text_embedding(query)

        # Search
        results = db.search_vectors(doc_id, query_embedding, top_k)

        if results:
            print(f"📊 Found {len(results)} results:")
            for i, result in enumerate(results, 1):
                print(f"\n{i}. Distance: {result['distance']:.4f}")
                print(f"   ID: {result['id']}")
                print(f"   Text: {result['document'][:100]}...")
                print(f"   Metadata: {result['metadata']}")
        else:
            print("❌ No results found")

    except Exception as e:
        print(f"❌ Search failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Database CLI for HiRAG System")
    parser.add_argument(
        "command",
        choices=["info", "list", "inspect", "clear", "rebuild", "vacuum", "search"],
        help="Command to run",
    )
    parser.add_argument(
        "--doc-id", type=int, help="Document ID for commands that need it"
    )
    parser.add_argument("--query", type=str, help="Search query for vector search")
    parser.add_argument(
        "--top-k", type=int, default=5, help="Number of results for search"
    )

    args = parser.parse_args()

    # Initialize database manager
    db = DatabaseManager()

    try:
        if args.command == "info":
            cmd_info(db)
        elif args.command == "list":
            cmd_list(db)
        elif args.command == "inspect":
            if not args.doc_id:
                print("❌ --doc-id required for inspect command")
                sys.exit(1)
            cmd_inspect(db, args.doc_id)
        elif args.command == "clear":
            cmd_clear(db, args.doc_id)
        elif args.command == "rebuild":
            if not args.doc_id:
                print("❌ --doc-id required for rebuild command")
                sys.exit(1)
            cmd_rebuild(db, args.doc_id)
        elif args.command == "vacuum":
            cmd_vacuum(db)
        elif args.command == "search":
            if not args.doc_id or not args.query:
                print("❌ --doc-id and --query required for search command")
                sys.exit(1)
            cmd_search(db, args.doc_id, args.query, args.top_k)

    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
