"""
LangChain 工作流 Demo — 调用 TmpAPI 本地服务

使用前请先启动 TmpAPI 服务:
    uv run tmpapi serve --port 8686 --no-headless

然后运行此脚本:
    uv run python tools/langchain_demo.py
"""

import urllib.request
import json

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

TMPAPI_BASE_URL = "http://localhost:8686/v1"


def _get_default_model() -> str:
    """从 /v1/models 自动获取当前 provider 的第一个可用模型。"""
    try:
        with urllib.request.urlopen(f"{TMPAPI_BASE_URL}/models", timeout=5) as resp:
            data = json.loads(resp.read())
            return data["data"][0]["id"]
    except Exception as e:
        raise RuntimeError(
            f"无法连接 TmpAPI ({TMPAPI_BASE_URL})，请先启动服务。\n原因: {e}"
        ) from e


_model = _get_default_model()
print(f"当前 Provider 模型: {_model}\n")

llm = ChatOpenAI(
    model=_model,
    base_url=TMPAPI_BASE_URL,
    api_key="not-needed",
    temperature=0.7,
)


def demo_simple_chat():
    """最基础的单轮对话"""
    print("=" * 60)
    print("Demo 1: 单轮对话")
    print("=" * 60)
    response = llm.invoke("用一句话介绍你自己")
    print(f"回复: {response.content}\n")


def demo_prompt_template():
    """使用 PromptTemplate 构建结构化提示"""
    print("=" * 60)
    print("Demo 2: Prompt Template 工作流")
    print("=" * 60)

    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一位专业的{role}，请用简洁明了的语言回答问题。"),
        ("user", "{question}"),
    ])

    chain = prompt | llm | StrOutputParser()
    result = chain.invoke({
        "role": "Python 技术专家",
        "question": "async 和 await 关键字的作用是什么？",
    })
    print(f"回复: {result}\n")


def demo_streaming():
    """流式输出"""
    print("=" * 60)
    print("Demo 3: 流式输出 (Streaming)")
    print("=" * 60)

    print("回复: ", end="", flush=True)
    for chunk in llm.stream("写一首关于编程的五言绝句"):
        print(chunk.content, end="", flush=True)
    print("\n")


def demo_multi_step_chain():
    """多步骤链式工作流: 先生成内容，再翻译"""
    print("=" * 60)
    print("Demo 4: 多步骤链式工作流")
    print("=" * 60)

    step1_prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一位创意写作专家。"),
        ("user", "用中文写一个关于「{topic}」的50字短故事。"),
    ])

    step2_prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一位专业翻译，请将以下中文翻译为英文。"),
        ("user", "{text}"),
    ])

    parser = StrOutputParser()

    # 第一步: 生成故事
    story_chain = step1_prompt | llm | parser
    story = story_chain.invoke({"topic": "一只会编程的猫"})
    print(f"生成的故事: {story}")

    # 第二步: 翻译
    translate_chain = step2_prompt | llm | parser
    translation = translate_chain.invoke({"text": story})
    print(f"英文翻译:   {translation}\n")


if __name__ == "__main__":
    print("\n🚀 LangChain + TmpAPI Demo\n")
    print(f"API 地址: {TMPAPI_BASE_URL}\n")

    demo_simple_chat()
    demo_prompt_template()
    demo_streaming()
    demo_multi_step_chain()

    print("✅ 全部 Demo 完成!")
