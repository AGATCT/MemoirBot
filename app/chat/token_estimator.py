"""
Token 估算工具。

简单快速的 token 数量估算，用于决定何时压缩上下文。
不需要精确——只需判断是否接近阈值即可。
"""


def estimate_tokens(text: str) -> int:
    """估计文本的 token 数量。

    启发式算法：
    - 中文字符 ≈ 1.2 token/字（DeepSeek BPE 对中文较高效）
    - 英文单词 ≈ 1.3 token/词
    - 混合文本：取 len(text) * 0.5 作为粗略下界

    对于中文为主的对话，这个估计偏低但够用。
    """
    if not text:
        return 0
    # 粗略估计：字符数 * 0.6
    return max(1, int(len(text) * 0.6))


def estimate_message_tokens(messages: list[dict]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        # 加上 message 结构的 overhead（role 标记等）
        total += 4
    return total
