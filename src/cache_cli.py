#!/usr/bin/env python3
"""
Cache CLI tool để quản lý cache của Hierarchical RAG system.
"""

import argparse
import sys
from .cache_manager import CacheManager


def main():
    parser = argparse.ArgumentParser(description="Quản lý cache cho POC Graph RAG")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Info command
    info_parser = subparsers.add_parser("info", help="Hiển thị thông tin cache")

    # Clear command
    clear_parser = subparsers.add_parser("clear", help="Xóa toàn bộ cache")
    clear_parser.add_argument(
        "--force", "-f", action="store_true", help="Không hỏi xác nhận"
    )

    # Validate command
    validate_parser = subparsers.add_parser(
        "validate", help="Kiểm tra cache có valid không"
    )
    validate_parser.add_argument("source_file", help="Đường dẫn file nguồn")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    cache = CacheManager()

    if args.command == "info":
        show_cache_info(cache)
    elif args.command == "clear":
        clear_cache(cache, args.force)
    elif args.command == "validate":
        validate_cache(cache, args.source_file)


def show_cache_info(cache: CacheManager):
    """Hiển thị thông tin cache."""
    print("📊 Cache Information:")
    print("=" * 50)

    cache_info = cache.get_cache_info()

    if cache_info["cache_valid"]:
        print(f"✅ Cache Status: Valid")
        print(f"📦 Total Size: {cache_info['total_size_mb']}")
        print(f"📁 Files:")
        for filename, size in cache_info["files"].items():
            print(f"   - {filename}: {size}")

        metadata = cache_info["metadata"]
        if metadata:
            print(f"📄 Source File: {metadata.get('source_file', 'Unknown')}")
            print(f"🕐 Cached At: {metadata.get('cached_at', 'Unknown')}")

            if "law_tree_stats" in metadata:
                stats = metadata["law_tree_stats"]
                print(f"📚 Parts: {stats.get('parts', 0)}")

            if "indices_stats" in metadata:
                indices = metadata["indices_stats"]
                print(f"🔧 Query Engines: {indices.get('child_engines_count', 0)}")
    else:
        print("❌ Cache Status: Not Found or Invalid")
        print("💡 Run main program to build cache")


def clear_cache(cache: CacheManager, force: bool = False):
    """Xóa cache."""
    if not force:
        print("⚠️  Bạn có chắc muốn xóa toàn bộ cache? (y/N): ", end="")
        confirm = input().strip().lower()
        if confirm not in ["y", "yes"]:
            print("❌ Hủy bỏ")
            return

    cache.clear_cache()
    print("✅ Cache đã được xóa")


def validate_cache(cache: CacheManager, source_file: str):
    """Kiểm tra cache có valid không."""
    print(f"🔍 Checking cache validity for: {source_file}")

    if cache.is_cache_valid(source_file):
        print("✅ Cache is valid - no rebuild needed")
    else:
        print("❌ Cache is invalid - rebuild required")


if __name__ == "__main__":
    main()
