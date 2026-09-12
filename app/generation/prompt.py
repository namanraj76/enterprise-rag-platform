SYSTEM_PROMPT = """
You are a grounded enterprise knowledge assistant.
Your job is to answer questions using only the retrieved evidence provided in the context.
If the evidence does not support a claim, say so clearly and avoid inventing details.
Always cite the source chunks used for the answer.
"""


def build_prompt(question: str, evidence: str) -> str:
    return f"""
{SYSTEM_PROMPT}

Question: {question}

Evidence:
{evidence}

Provide a concise answer, cite the supporting chunk IDs, and clearly state when the evidence is insufficient.
"""
