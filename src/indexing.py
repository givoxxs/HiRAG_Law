from llama_index.core import (  # type: ignore
    VectorStoreIndex,
    SummaryIndex,
    Document,
    Settings,
)
from llama_index.core.schema import IndexNode, TextNode  # type: ignore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding  # type: ignore
from typing import Dict, Any, List, Optional, Tuple
import os
from dotenv import load_dotenv

load_dotenv()

from llama_index.core.llms.llm import LLM
from llama_index.llms.litellm import LiteLLM
from pydantic import Field
import json
import requests
import os

os.environ["GEMINI_API_KEY"] = os.getenv("GEMINI_API_KEY")


# Simple response classes
class SimpleCompletionResponse:
    def __init__(self, text: str):
        self.text = text


class SimpleChatMessage:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


class SimpleChatResponse:
    def __init__(self, message):
        self.message = message


class OpenRouter(LLM):
    """
    Custom OpenRouter LLM for LlamaIndex.
    """

    openrouter_api_key: str = Field(description="OpenRouter API key")
    model: str = Field(description="Model name to use")
    provider_order: Optional[List[str]] = Field(
        default=None, description="Provider order preference"
    )

    def __init__(
        self,
        openrouter_api_key: str,
        model: str,
        provider_order: Optional[List[str]] = None,
        **kwargs,
    ):
        super().__init__(
            openrouter_api_key=openrouter_api_key,
            model=model,
            provider_order=provider_order,
            **kwargs,
        )

    def _call_api(self, messages: List[Dict], **kwargs) -> str:
        """Internal method to call OpenRouter API."""
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": self.model,
            "messages": messages,
        }

        if self.provider_order:
            data["provider"] = {"order": self.provider_order}

        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                data=json.dumps(data),
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"OpenRouter API error: {e}")
            return f"Error calling OpenRouter API: {e}"

    def complete(self, prompt: str, **kwargs):
        """Calls OpenRouter API and returns the completion response."""
        messages = [{"role": "user", "content": prompt}]
        content = self._call_api(messages, **kwargs)
        return SimpleCompletionResponse(text=content)

    def chat(self, messages, **kwargs):
        """Chat interface."""
        # Convert messages to proper format if needed
        if hasattr(messages, "messages"):
            chat_messages = [
                {"role": msg.role, "content": msg.content} for msg in messages.messages
            ]
        else:
            chat_messages = messages
        content = self._call_api(chat_messages, **kwargs)
        return SimpleChatResponse(
            message=SimpleChatMessage(role="assistant", content=content)
        )

    def stream_complete(self, prompt: str, **kwargs):
        """Stream completion - simplified implementation."""
        result = self.complete(prompt, **kwargs)
        yield result

    def stream_chat(self, messages, **kwargs):
        """Stream chat - simplified implementation."""
        result = self.chat(messages, **kwargs)
        yield result

    async def acomplete(self, prompt: str, **kwargs):
        """Async completion - falls back to sync."""
        return self.complete(prompt, **kwargs)

    async def achat(self, messages, **kwargs):
        """Async chat - falls back to sync."""
        return self.chat(messages, **kwargs)

    async def astream_complete(self, prompt: str, **kwargs):
        """Async stream completion - falls back to sync."""
        for chunk in self.stream_complete(prompt, **kwargs):
            yield chunk

    async def astream_chat(self, messages, **kwargs):
        """Async stream chat - falls back to sync."""
        for chunk in self.stream_chat(messages, **kwargs):
            yield chunk

    @property
    def metadata(self):
        """Return metadata about the model."""

        class LLMMetadata:
            def __init__(self, model_name):
                self.context_window = 4096  # Default context window
                self.num_output = 512  # Default max output tokens
                self.model_name = model_name

        return LLMMetadata(self.model)


def setup_models():
    """Cấu hình các mô hình LLM và Embedding."""
    # Settings.llm = OpenRouter(
    #     openrouter_api_key=os.getenv("API_KEY"),
    #     model=os.getenv("MODEL_NAME"),
    #     provider_order=["DeepInfra", "Together"],
    # )
    Settings.llm = LiteLLM(
        model="gemini/gemini-2.5-flash-preview-04-17",  # Model dùng LiteLLM wrapper
        api_key=os.getenv("GEMINI_API_KEY"),
        context_window=8192,  # Số token có thể tùy chỉnh (Gemini Pro hỗ trợ lớn)
        max_tokens=1024,
    )
    Settings.embed_model = HuggingFaceEmbedding(
        model_name="dangvantuan/vietnamese-document-embedding", trust_remote_code=True
    )
    print("Models setup complete.")


def build_hierarchical_index(law_tree: dict):
    """
    Xây dựng chỉ mục phân cấp theo paper HiRAG với bottom-up summarization.

    Hierarchy: Khoản (Clause) → Điều (Article) → Mục (Section) → Chương (Chapter) → Phần (Part)

    Args:
        law_tree: Cấu trúc cây dữ liệu luật đã parse

    Returns:
        tuple: (top_index, child_query_engines)
    """
    print("🔨 Building hierarchical index with bottom-up summarization...")

    all_part_nodes = []
    child_query_engines = {}

    # Lấy metadata
    title = law_tree.get("metadata", {}).get("title", "Văn bản luật")

    # Duyệt qua từng PHẦN
    for part_title, part_content in law_tree["content"].items():
        print(f"\n📚 Processing Part: {part_title}")

        part_chapter_nodes = []

        # Duyệt qua từng CHƯƠNG trong Phần
        for chapter_title, chapter_content in part_content.items():
            print(f"  📖 Processing Chapter: {chapter_title}")

            chapter_nodes = []

            # Xử lý nội dung chương - có thể là Điều trực tiếp hoặc Mục
            for item_key, item_content in chapter_content.items():

                # Kiểm tra xem có phải là MỤC không
                if item_key.startswith("Mục"):
                    # Case: Chương -> Mục -> Điều -> Khoản
                    section_title = item_key
                    print(f"    📑 Processing Section: {section_title}")

                    section_article_nodes = []

                    # Duyệt qua các Điều trong Mục
                    for article_title, article_clauses in item_content.items():
                        article_node, article_query_engine = build_article_index(
                            article_title,
                            article_clauses,
                            f"{section_title} - {article_title}",
                        )
                        if article_node:
                            section_article_nodes.append(article_node)
                            child_query_engines[article_title] = article_query_engine

                    # Tạo index cho Mục từ các Điều
                    if section_article_nodes:
                        section_index = VectorStoreIndex(section_article_nodes)
                        section_summary = summarize_nodes(
                            section_article_nodes,
                            f"Tóm tắt nội dung của {section_title}",
                            "section",
                        )

                        section_node = IndexNode(
                            text=f"{section_title}: {section_summary}",
                            index_id=section_title,
                        )
                        chapter_nodes.append(section_node)
                        child_query_engines[section_title] = (
                            section_index.as_query_engine()
                        )

                elif item_key.startswith("Điều"):
                    # Case: Chương -> Điều -> Khoản (không có Mục)
                    article_title = item_key
                    article_clauses = item_content

                    article_node, article_query_engine = build_article_index(
                        article_title,
                        article_clauses,
                        f"{chapter_title} - {article_title}",
                    )
                    if article_node:
                        chapter_nodes.append(article_node)
                        child_query_engines[article_title] = article_query_engine

            # Tạo index cho Chương từ các Điều/Mục
            if chapter_nodes:
                chapter_index = VectorStoreIndex(chapter_nodes)
                chapter_summary = summarize_nodes(
                    chapter_nodes, f"Tóm tắt nội dung của {chapter_title}", "chapter"
                )

                chapter_node = IndexNode(
                    text=f"{chapter_title}: {chapter_summary}", index_id=chapter_title
                )
                part_chapter_nodes.append(chapter_node)
                child_query_engines[chapter_title] = chapter_index.as_query_engine()

        # Tạo index cho Phần từ các Chương
        if part_chapter_nodes:
            part_index = VectorStoreIndex(part_chapter_nodes)
            part_summary = summarize_nodes(
                part_chapter_nodes, f"Tóm tắt nội dung của {part_title}", "part"
            )

            part_node = IndexNode(
                text=f"{part_title}: {part_summary}", index_id=part_title
            )
            all_part_nodes.append(part_node)
            child_query_engines[part_title] = part_index.as_query_engine()

    # Tạo top-level index từ các Phần
    if not all_part_nodes:
        raise ValueError(
            "Không có dữ liệu để tạo index. Kiểm tra lại cấu trúc law_tree."
        )

    top_index = VectorStoreIndex(all_part_nodes)

    print(f"\n✅ Hierarchical index built successfully!")
    print(f"   📊 Total Parts: {len(all_part_nodes)}")
    print(f"   🔧 Total Query Engines: {len(child_query_engines)}")

    return top_index, child_query_engines


def build_article_index(
    article_title: str, article_clauses: Dict[str, str], context: str = ""
) -> Tuple[IndexNode, Any]:
    """
    Xây dựng index cho một Điều từ các Khoản.

    Args:
        article_title: Tiêu đề điều (vd: "Điều 1. Phạm vi điều chỉnh")
        article_clauses: Dict các khoản {khoản_key: nội_dung}
        context: Context để debug

    Returns:
        tuple: (article_index_node, article_query_engine)
    """
    if not article_clauses:
        print(f"    ⚠️ No clauses found for {article_title}")
        return None, None

    # 1. Tạo TextNode từ mỗi Khoản (leaf nodes)
    clause_nodes = []
    for clause_key, clause_content in article_clauses.items():
        if clause_content and clause_content.strip():
            clause_node = TextNode(
                text=f"{article_title} - {clause_key}: {clause_content.strip()}",
                metadata={
                    "article": article_title,
                    "clause": clause_key,
                    "level": "clause",
                    "context": context,
                },
            )
            clause_nodes.append(clause_node)

    if not clause_nodes:
        print(f"    ⚠️ No valid clause nodes for {article_title}")
        return None, None

    # 2. Tạo VectorStoreIndex từ các Khoản
    clause_index = VectorStoreIndex(clause_nodes)

    # 3. Tóm tắt các Khoản thành summary của Điều (bottom-up)
    article_summary = summarize_nodes(
        clause_nodes, f"Tóm tắt nội dung chính của {article_title}", "article"
    )

    # 4. Tạo IndexNode cho Điều
    article_node = IndexNode(
        text=f"{article_title}: {article_summary}",
        index_id=article_title,
        metadata={
            "level": "article",
            "num_clauses": len(clause_nodes),
            "context": context,
        },
    )

    print(f"    ✅ Built article index: {article_title} ({len(clause_nodes)} clauses)")

    return article_node, clause_index.as_query_engine()


def summarize_nodes(nodes: List, summary_prompt_prefix: str, level: str) -> str:
    """
    Tóm tắt nội dung từ list of nodes theo paper HiRAG.

    Args:
        nodes: List TextNode hoặc IndexNode cần tóm tắt
        summary_prompt_prefix: Prefix cho prompt tóm tắt
        level: Level hiện tại (clause, article, section, chapter, part)

    Returns:
        str: Nội dung tóm tắt
    """
    if not nodes:
        return "Không có nội dung."

    # Lấy text từ các nodes
    node_texts = []
    for node in nodes:
        if hasattr(node, "text"):
            node_texts.append(node.text)
        elif hasattr(node, "get_content"):
            node_texts.append(node.get_content())

    if not node_texts:
        return "Không có nội dung hợp lệ."

    # Tạo prompt tóm tắt phù hợp với từng level
    combined_text = "\n".join(node_texts)

    # Giới hạn độ dài input cho LLM
    max_chars = 8000  # Giới hạn để tránh token limit
    if len(combined_text) > max_chars:
        combined_text = combined_text[:max_chars] + "..."

    summary_prompt = f"""
{summary_prompt_prefix} dựa trên các nội dung sau:

{combined_text}

Hãy tóm tắt ngắn gọn và súc tích theo yêu cầu sau:
- Nêu được ý chính và điểm quan trọng nhất
- Sử dụng ngôn ngữ pháp lý chính xác
- Độ dài không quá 200 từ
- Giữ nguyên các thuật ngữ pháp luật quan trọng

Tóm tắt:"""

    try:
        summary_response = Settings.llm.complete(summary_prompt)
        summary = summary_response.text.strip()

        if not summary or len(summary) < 10:
            # Fallback: lấy phần đầu của combined_text
            summary = (
                combined_text[:300] + "..."
                if len(combined_text) > 300
                else combined_text
            )

        print(
            f"    📝 Summarized {level} ({len(node_texts)} items) -> {len(summary)} chars"
        )
        return summary

    except Exception as e:
        print(f"    ⚠️ Summarization failed for {level}: {e}")
        # Fallback: lấy phần đầu của combined_text
        fallback_summary = (
            combined_text[:300] + "..." if len(combined_text) > 300 else combined_text
        )
        return fallback_summary


def call_llm(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("API_KEY"),
    )

    completion = client.chat.completions.create(
        extra_headers={
            "HTTP-Referer": "<YOUR_SITE_URL>",  # Optional. Site URL for rankings on openrouter.ai.
            "X-Title": "<YOUR_SITE_NAME>",  # Optional. Site title for rankings on openrouter.ai.
        },
        extra_body={},
        model="deepseek/deepseek-r1-0528:free",
        messages=[{"role": "user", "content": prompt}],
    )
    print(completion.choices[0].message.content)
    return completion.choices[0].message.content
