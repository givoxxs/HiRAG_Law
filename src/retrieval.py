from llama_index.core.retrievers import RecursiveRetriever  # type: ignore
from llama_index.core.query_engine import RetrieverQueryEngine  # type: ignore
from llama_index.core.schema import NodeWithScore, QueryBundle  # type: ignore
from llama_index.core.base.response.schema import Response  # type: ignore
from typing import List, Dict, Any, Optional
import re
from .call_llm import GeminiLLM_instance


class EnhancedQueryEngine:
    """
    Enhanced Query Engine với Global-Bridge-Local strategy và multi-query support
    """

    def __init__(self, top_index, child_query_engines):
        self.top_index = top_index
        self.child_query_engines = child_query_engines

        # Setup basic recursive retriever
        top_retriever = top_index.as_retriever(similarity_top_k=10)
        retriever_dict = {"vector": top_retriever}

        self.recursive_retriever = RecursiveRetriever(
            "vector",
            retriever_dict=retriever_dict,
            query_engine_dict=child_query_engines,
            verbose=True,
        )

        self.basic_query_engine = RetrieverQueryEngine.from_args(
            self.recursive_retriever
        )

    def query(self, query_str: str) -> str:
        """Single query với structured response"""
        return self.multi_query([query_str])

    def multi_query(self, queries: List[str]) -> str:
        """
        Multi-query processing với Global-Bridge-Local analysis
        """
        print(
            f"\n🔍 Processing {len(queries)} queries with Global-Bridge-Local analysis..."
        )

        all_results = []

        for i, query_str in enumerate(queries, 1):
            print(f"\n📋 Query {i}/{len(queries)}: {query_str}")

            # Extract structured information
            structured_info = self._extract_global_bridge_local(query_str)

            # Get LLM response
            llm_response = self.basic_query_engine.query(query_str)

            # Format combined result
            answer, result = self._format_structured_response(
                query_str, structured_info, str(llm_response)
            )
            all_results.append(answer)

        return "\n\n" + "=" * 80 + "\n\n".join(
            all_results
        ), "\n\n" + "=" * 80 + "\n\n".join(result)

    def _extract_global_bridge_local(self, query_str: str) -> Dict[str, Any]:
        """
        Extract Global-Bridge-Local information từ retrieval process
        """
        print("📊 Analyzing retrieval hierarchy...")

        # Get retrieval results at different levels
        query_bundle = QueryBundle(query_str=query_str)

        # Level 1: Global (Chương/Phần level)
        global_nodes = self._get_global_level_nodes(query_bundle)

        # Level 2: Bridge (Điều level)
        bridge_nodes = self._get_bridge_level_nodes(query_bundle, global_nodes)

        # Level 3: Local (Khoản level)
        local_nodes = self._get_local_level_nodes(query_bundle, bridge_nodes)

        return {"global": global_nodes, "bridge": bridge_nodes, "local": local_nodes}

    def _get_global_level_nodes(
        self, query_bundle: QueryBundle
    ) -> List[Dict[str, str]]:
        """Extract Global level information (Chương/Phần)"""
        top_retriever = self.top_index.as_retriever(similarity_top_k=5)
        nodes = top_retriever.retrieve(query_bundle)

        global_info = []
        for node in nodes:
            # Extract Chương/Phần information
            text = node.node.text

            # Find Chương or Phần patterns
            chapter_match = re.search(r"(Chương [IVX\d]+[.\s]*[^.\n]*)", text)
            part_match = re.search(r"(PHẦN THỨ [A-Z\d]+[.\s]*[^.\n]*)", text)

            if chapter_match:
                title = chapter_match.group(1).strip()
                global_info.append(
                    {"type": "Chương", "title": title, "score": node.score}
                )
            elif part_match:
                title = part_match.group(1).strip()
                global_info.append(
                    {"type": "Phần", "title": title, "score": node.score}
                )

        return global_info[:1]  # Top 1 most relevant

    def _get_bridge_level_nodes(
        self, query_bundle: QueryBundle, global_nodes: List[Dict]
    ) -> List[Dict[str, str]]:
        """Extract Bridge level information (Điều)"""
        bridge_info = []

        # Get nodes from recursive retrieval
        nodes = self.recursive_retriever.retrieve(query_bundle)

        for node in nodes:
            text = node.node.text

            # Find Điều patterns
            article_match = re.search(r"(Điều \d+[.\s]*[^.\n]*)", text)

            if article_match:
                title = article_match.group(1).strip()
                bridge_info.append(
                    {"type": "Điều", "title": title, "score": node.score}
                )

        return bridge_info[:2]  # Top 1 most relevant

    def _get_local_level_nodes(
        self, query_bundle: QueryBundle, bridge_nodes: List[Dict]
    ) -> List[Dict[str, str]]:
        """Extract Local level information (Khoản)"""
        local_info = []

        # Get detailed nodes from recursive retrieval
        nodes = self.recursive_retriever.retrieve(query_bundle)

        for node in nodes:
            text = node.node.text

            # Find Khoản/Điểm patterns và extract actual content
            khoac_match = re.search(r"(\d+\.\s*[^0-9][^\n]+)", text)
            diem_match = re.search(r"([a-z]\)\s*[^a-z)][^\n]+)", text)

            if khoac_match:
                content = khoac_match.group(1).strip()
                local_info.append(
                    {"type": "Khoản", "content": content, "score": node.score}
                )
            elif diem_match:
                content = diem_match.group(1).strip()
                local_info.append(
                    {"type": "Điểm", "content": content, "score": node.score}
                )

        return local_info[:5]  # Top 2 most relevant

    def _format_structured_response(
        self, query: str, structured_info: Dict, llm_response: str
    ) -> str:
        """
        Format response với Global-Bridge-Local structure
        """
        result = f"🔍 **Query**: {query}\n\n"

        # Global level
        if structured_info["global"]:
            global_item = structured_info["global"][0]
            result += f"[Global] {global_item['type']} liên quan nhất: {global_item['title']}\n\n"

        # Bridge level
        if structured_info["bridge"]:
            bridge_item = structured_info["bridge"][0]
            result += f"[Bridge] {bridge_item['type']} liên quan nhất: {bridge_item['title']}\n\n"

        # Local level
        if structured_info["local"]:
            result += "[Local] Nội dung liên quan nhất:\n"
            for i, local_item in enumerate(structured_info["local"], 1):
                result += f"  {i}. {local_item['content']}\n"
            result += "\n"

        # Call LLM
        answer = GeminiLLM_instance.call_litellm(result)

        return answer, result


def setup_recursive_retriever(top_index, child_query_engines):
    """
    Thiết lập Enhanced Query Engine với Global-Bridge-Local support.
    """
    return EnhancedQueryEngine(top_index, child_query_engines)
