import requests
import os
from dotenv import load_dotenv
from litellm import completion
import json

load_dotenv()


class GeminiLLM:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = "gemini-2.0-flash"
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        self.headers = {"Content-Type": "application/json"}

    def call_direct(self, prompt: str) -> str:
        """Gọi API Gemini trực tiếp qua requests"""
        data = {"contents": [{"parts": [{"text": prompt}]}]}

        try:
            response = requests.post(self.url, headers=self.headers, json=data)
            response.raise_for_status()  # Raise exception for HTTP errors

            result = response.json()

            # Kiểm tra nếu có lỗi trong response
            if "error" in result:
                return f"Lỗi API: {result['error']['message']}"

            # Kiểm tra nếu có candidates
            if "candidates" not in result:
                return f"Lỗi: Response không có 'candidates'"

            if not result["candidates"]:
                return "Lỗi: Danh sách candidates rỗng"

            return result["candidates"][0]["content"]["parts"][0]["text"]

        except requests.exceptions.RequestException as e:
            return f"Lỗi kết nối: {str(e)}"
        except KeyError as e:
            return f"Lỗi cấu trúc response: {str(e)}"
        except Exception as e:
            return f"Lỗi không xác định: {str(e)}"

    def call_litellm(self, prompt: str) -> str:
        """Gọi API Gemini thông qua LiteLLM"""
        try:
            response = completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": prompt}],
                api_key=self.api_key,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Lỗi LiteLLM: {str(e)}"


GeminiLLM_instance = GeminiLLM()

if __name__ == "__main__":
    llm = GeminiLLM()
    prompt = "Tóm tắt Điều 1 của Luật An toàn thông tin mạng"

    # Test gọi trực tiếp
    print("=== Kết quả gọi trực tiếp ===")
    result_direct = llm.call_direct(prompt)
    print(result_direct)

    # Test gọi qua LiteLLM
    print("\n=== Kết quả gọi qua LiteLLM ===")
    result_litellm = llm.call_litellm(prompt)
    print(result_litellm)

# python -m src.call_llm
