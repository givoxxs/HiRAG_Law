import os
import json
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import chromadb
from chromadb.config import Settings as ChromaSettings
import pickle
import base64


class DatabaseManager:
    """
    Production-ready database manager cho Hierarchical RAG system.

    Architecture:
    - ChromaDB: Vector storage cho embeddings
    - SQLite: Metadata, hierarchy, relationships
    - File system: Large objects (indices)
    """

    def __init__(self, db_dir: str = "data/db"):
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB for vector storage
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.db_dir / "vector_db")
        )

        # Initialize SQLite for metadata
        self.sql_db_path = self.db_dir / "metadata.db"
        self.init_sql_schema()

        # File storage for large objects
        self.objects_dir = self.db_dir / "objects"
        self.objects_dir.mkdir(exist_ok=True)

    def init_sql_schema(self):
        """Initialize SQL database schema."""
        conn = sqlite3.connect(self.sql_db_path)
        cursor = conn.cursor()

        # Documents table
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            file_hash TEXT NOT NULL,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT -- JSON metadata
        )
        """
        )

        # Hierarchy table
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS hierarchy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            parent_id INTEGER,
            level TEXT NOT NULL, -- 'part', 'chapter', 'section', 'article', 'clause'
            title TEXT NOT NULL,
            content TEXT,
            order_index INTEGER,
            vector_collection TEXT, -- ChromaDB collection name
            vector_id TEXT, -- ID in ChromaDB
            object_path TEXT, -- Path to pickled object
            FOREIGN KEY (document_id) REFERENCES documents (id),
            FOREIGN KEY (parent_id) REFERENCES hierarchy (id)
        )
        """
        )

        # Cache status table
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS cache_status (
            document_id INTEGER PRIMARY KEY,
            parsing_done BOOLEAN DEFAULT FALSE,
            indexing_done BOOLEAN DEFAULT FALSE,
            embeddings_done BOOLEAN DEFAULT FALSE,
            last_build TIMESTAMP,
            build_stats TEXT, -- JSON stats
            FOREIGN KEY (document_id) REFERENCES documents (id)
        )
        """
        )

        # Create indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_hierarchy_document ON hierarchy(document_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_hierarchy_parent ON hierarchy(parent_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_hierarchy_level ON hierarchy(level)"
        )

        conn.commit()
        conn.close()

    def get_file_hash(self, file_path: str) -> str:
        """Calculate file hash for change detection."""
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def register_document(self, file_path: str, title: str = None) -> int:
        """Register a document and return document ID."""
        file_hash = self.get_file_hash(file_path)

        conn = sqlite3.connect(self.sql_db_path)
        cursor = conn.cursor()

        # Check if document exists
        cursor.execute(
            "SELECT id, file_hash FROM documents WHERE file_path = ?", (file_path,)
        )
        result = cursor.fetchone()

        if result:
            doc_id, cached_hash = result
            if cached_hash == file_hash:
                print(f"📄 Document unchanged: {file_path}")
                conn.close()
                return doc_id
            else:
                # File changed - update hash and reset cache
                cursor.execute(
                    """
                UPDATE documents SET file_hash = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
                """,
                    (file_hash, doc_id),
                )

                # Clear cache status
                cursor.execute(
                    "DELETE FROM cache_status WHERE document_id = ?", (doc_id,)
                )
                cursor.execute("DELETE FROM hierarchy WHERE document_id = ?", (doc_id,))

                print(f"📄 Document changed: {file_path} - cache invalidated")
        else:
            # New document
            cursor.execute(
                """
            INSERT INTO documents (file_path, file_hash, title, metadata)
            VALUES (?, ?, ?, ?)
            """,
                (file_path, file_hash, title or Path(file_path).stem, "{}"),
            )
            doc_id = cursor.lastrowid
            print(f"📄 New document registered: {file_path}")

        conn.commit()
        conn.close()
        return doc_id

    def is_cache_complete(self, doc_id: int) -> bool:
        """Check if all caching is complete for a document."""
        conn = sqlite3.connect(self.sql_db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
        SELECT parsing_done, indexing_done, embeddings_done 
        FROM cache_status WHERE document_id = ?
        """,
            (doc_id,),
        )

        result = cursor.fetchone()
        conn.close()

        if result:
            parsing, indexing, embeddings = result
            return all([parsing, indexing, embeddings])
        return False

    def save_law_tree(self, doc_id: int, law_tree: Dict[str, Any]):
        """Save parsed law tree to hierarchy table."""
        conn = sqlite3.connect(self.sql_db_path)
        cursor = conn.cursor()

        # Save hierarchy structure
        self._save_hierarchy_recursive(
            cursor, doc_id, law_tree["content"], None, "root", 0
        )

        # Update cache status
        cursor.execute(
            """
        INSERT OR REPLACE INTO cache_status (document_id, parsing_done, last_build)
        VALUES (?, TRUE, CURRENT_TIMESTAMP)
        """,
            (doc_id,),
        )

        conn.commit()
        conn.close()
        print(f"💾 Law tree saved to database for doc_id: {doc_id}")

    def _save_hierarchy_recursive(
        self,
        cursor,
        doc_id: int,
        content: Dict,
        parent_id: Optional[int],
        level: str,
        order: int,
    ):
        """Recursively save hierarchy to database."""
        level_mapping = {
            "root": ("part", "PHẦN"),
            "part": ("chapter", "CHƯƠNG"),
            "chapter": ("section_or_article", "MỤC|Điều"),
            "section": ("article", "Điều"),
            "article": ("clause", "Khoản"),
        }

        for i, (title, sub_content) in enumerate(content.items()):
            # Insert current node
            cursor.execute(
                """
            INSERT INTO hierarchy (document_id, parent_id, level, title, content, order_index)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
                (doc_id, parent_id, level, title, "", order + i),
            )

            node_id = cursor.lastrowid

            if isinstance(sub_content, dict):
                # Determine next level
                next_level_info = level_mapping.get(level)
                if next_level_info:
                    next_level, pattern = next_level_info

                    # Special handling for chapter level (may have Mục or direct Điều)
                    if level == "chapter":
                        first_key = next(iter(sub_content.keys()))
                        if first_key.startswith("Mục"):
                            next_level = "section"
                        else:
                            next_level = "article"

                    self._save_hierarchy_recursive(
                        cursor, doc_id, sub_content, node_id, next_level, 0
                    )
                else:
                    # Leaf level - save content
                    if level == "article":
                        # This is clauses
                        for j, (clause_key, clause_content) in enumerate(
                            sub_content.items()
                        ):
                            cursor.execute(
                                """
                            INSERT INTO hierarchy (document_id, parent_id, level, title, content, order_index)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                                (
                                    doc_id,
                                    node_id,
                                    "clause",
                                    clause_key,
                                    clause_content,
                                    j,
                                ),
                            )

    def load_law_tree(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Load law tree from database."""
        conn = sqlite3.connect(self.sql_db_path)
        cursor = conn.cursor()

        # Get document info
        cursor.execute("SELECT title FROM documents WHERE id = ?", (doc_id,))
        doc_result = cursor.fetchone()
        if not doc_result:
            conn.close()
            return None

        # Build hierarchy tree
        law_tree = {"metadata": {"title": doc_result[0]}, "content": {}}

        # Get root parts
        cursor.execute(
            """
        SELECT id, title FROM hierarchy 
        WHERE document_id = ? AND level = 'part' 
        ORDER BY order_index
        """,
            (doc_id,),
        )

        parts = cursor.fetchall()
        for part_id, part_title in parts:
            law_tree["content"][part_title] = self._load_hierarchy_recursive(
                cursor, part_id
            )

        conn.close()
        print(f"📂 Law tree loaded from database for doc_id: {doc_id}")
        return law_tree

    def _load_hierarchy_recursive(self, cursor, parent_id: int) -> Dict[str, Any]:
        """Recursively load hierarchy from database."""
        cursor.execute(
            """
        SELECT id, level, title, content FROM hierarchy 
        WHERE parent_id = ? 
        ORDER BY order_index
        """,
            (parent_id,),
        )

        children = cursor.fetchall()
        result = {}

        for child_id, level, title, content in children:
            if level == "clause":
                # Leaf node
                result[title] = content
            else:
                # Intermediate node
                result[title] = self._load_hierarchy_recursive(cursor, child_id)

        return result

    def save_embeddings(self, doc_id: int, embeddings_data: List[Dict[str, Any]]):
        """Save embeddings to ChromaDB."""
        collection_name = f"doc_{doc_id}_embeddings"

        try:
            # Delete existing collection
            try:
                self.chroma_client.delete_collection(collection_name)
            except:
                pass

            # Create new collection
            collection = self.chroma_client.create_collection(
                name=collection_name, metadata={"document_id": doc_id}
            )

            # Prepare data for ChromaDB
            ids = []
            embeddings = []
            metadatas = []
            documents = []

            for item in embeddings_data:
                ids.append(item["id"])
                embeddings.append(item["embedding"])
                metadatas.append(item["metadata"])
                documents.append(item["text"])

            # Add to collection
            collection.add(
                ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents
            )

            # Update hierarchy table with vector info
            conn = sqlite3.connect(self.sql_db_path)
            cursor = conn.cursor()

            for item in embeddings_data:
                if "hierarchy_id" in item["metadata"]:
                    cursor.execute(
                        """
                    UPDATE hierarchy SET vector_collection = ?, vector_id = ?
                    WHERE id = ?
                    """,
                        (collection_name, item["id"], item["metadata"]["hierarchy_id"]),
                    )

            conn.commit()
            conn.close()

            print(
                f"💾 Saved {len(embeddings_data)} embeddings to ChromaDB collection: {collection_name}"
            )

        except Exception as e:
            print(f"⚠️ Failed to save embeddings: {e}")

    def save_indices(self, doc_id: int, top_index, child_query_engines: Dict[str, Any]):
        """Save built indices to file system."""
        try:
            # Save top index
            top_index_path = self.objects_dir / f"doc_{doc_id}_top_index.pkl"
            with open(top_index_path, "wb") as f:
                pickle.dump(top_index, f)

            # Save child query engines
            engines_path = self.objects_dir / f"doc_{doc_id}_engines.pkl"
            with open(engines_path, "wb") as f:
                pickle.dump(child_query_engines, f)

            # Update cache status
            conn = sqlite3.connect(self.sql_db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
            UPDATE cache_status SET 
                indexing_done = TRUE,
                embeddings_done = TRUE,
                last_build = CURRENT_TIMESTAMP,
                build_stats = ?
            WHERE document_id = ?
            """,
                (
                    json.dumps(
                        {
                            "top_index_size": os.path.getsize(top_index_path),
                            "engines_count": len(child_query_engines),
                        }
                    ),
                    doc_id,
                ),
            )

            conn.commit()
            conn.close()

            print(f"💾 Saved indices for doc_id: {doc_id}")
            print(f"   - Top index: {top_index_path}")
            print(f"   - Engines: {len(child_query_engines)} items")

        except Exception as e:
            print(f"⚠️ Failed to save indices: {e}")

    def load_indices(self, doc_id: int) -> Optional[Tuple[Any, Dict[str, Any]]]:
        """Load indices from file system."""
        try:
            top_index_path = self.objects_dir / f"doc_{doc_id}_top_index.pkl"
            engines_path = self.objects_dir / f"doc_{doc_id}_engines.pkl"

            if top_index_path.exists() and engines_path.exists():
                # Load top index
                with open(top_index_path, "rb") as f:
                    top_index = pickle.load(f)

                # Load engines
                with open(engines_path, "rb") as f:
                    child_query_engines = pickle.load(f)

                print(f"📂 Loaded indices for doc_id: {doc_id}")
                print(f"   - Engines: {len(child_query_engines)} items")

                return top_index, child_query_engines

        except Exception as e:
            print(f"⚠️ Failed to load indices: {e}")

        return None

    def get_database_stats(self) -> Dict[str, Any]:
        """Get comprehensive database statistics."""
        conn = sqlite3.connect(self.sql_db_path)
        cursor = conn.cursor()

        # Document stats
        cursor.execute("SELECT COUNT(*) FROM documents")
        doc_count = cursor.fetchone()[0]

        # Hierarchy stats
        cursor.execute("SELECT level, COUNT(*) FROM hierarchy GROUP BY level")
        hierarchy_stats = dict(cursor.fetchall())

        # Cache stats
        cursor.execute(
            """
        SELECT 
            SUM(CASE WHEN parsing_done THEN 1 ELSE 0 END) as parsed,
            SUM(CASE WHEN indexing_done THEN 1 ELSE 0 END) as indexed,
            SUM(CASE WHEN embeddings_done THEN 1 ELSE 0 END) as embedded
        FROM cache_status
        """
        )
        cache_stats = cursor.fetchone()

        conn.close()

        # ChromaDB stats
        collections = self.chroma_client.list_collections()
        vector_stats = {
            "collections": len(collections),
            "total_vectors": sum(c.count() for c in collections),
        }

        # File system stats
        objects_size = sum(f.stat().st_size for f in self.objects_dir.glob("*.pkl"))

        return {
            "documents": doc_count,
            "hierarchy": hierarchy_stats,
            "cache_status": {
                "parsed": cache_stats[0] if cache_stats else 0,
                "indexed": cache_stats[1] if cache_stats else 0,
                "embedded": cache_stats[2] if cache_stats else 0,
            },
            "vectors": vector_stats,
            "storage_size_mb": {
                "sql_db": os.path.getsize(self.sql_db_path) / 1024 / 1024,
                "objects": objects_size / 1024 / 1024,
                "vector_db": sum(
                    f.stat().st_size
                    for f in Path(self.db_dir / "vector_db").rglob("*")
                    if f.is_file()
                )
                / 1024
                / 1024,
            },
        }

    def clear_document_cache(self, doc_id: int):
        """Clear all cache for a specific document."""
        conn = sqlite3.connect(self.sql_db_path)
        cursor = conn.cursor()

        # Get vector collection name
        cursor.execute(
            "SELECT DISTINCT vector_collection FROM hierarchy WHERE document_id = ? AND vector_collection IS NOT NULL",
            (doc_id,),
        )
        collections = [row[0] for row in cursor.fetchall()]

        # Delete from ChromaDB
        for collection_name in collections:
            try:
                self.chroma_client.delete_collection(collection_name)
            except:
                pass

        # Delete from SQL
        cursor.execute("DELETE FROM hierarchy WHERE document_id = ?", (doc_id,))
        cursor.execute("DELETE FROM cache_status WHERE document_id = ?", (doc_id,))

        # Delete object files
        for pattern in [f"doc_{doc_id}_*.pkl"]:
            for file_path in self.objects_dir.glob(pattern):
                file_path.unlink()

        conn.commit()
        conn.close()

        print(f"🗑️ Cleared all cache for doc_id: {doc_id}")

    def search_vectors(
        self, doc_id: int, query_embedding: List[float], top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Search vectors in ChromaDB for a document."""
        collection_name = f"doc_{doc_id}_embeddings"

        try:
            collection = self.chroma_client.get_collection(collection_name)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )

            search_results = []
            for i in range(len(results["ids"][0])):
                search_results.append(
                    {
                        "id": results["ids"][0][i],
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i],
                    }
                )

            return search_results

        except Exception as e:
            print(f"⚠️ Vector search failed: {e}")
            return []
