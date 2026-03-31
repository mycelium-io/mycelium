# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Format-specific system prompts for concept and relationship extraction.

Only the openclaw/general-purpose prompts are ported here.
"""

GENERAL_CONCEPTS_PROMPT = (
    "You are an expert in multi-agent systems, conversational AI, dialogue analysis, "
    "and knowledge-graph construction.\n\n"
    "Remember that these concepts form the memory of a multi-agent system. Make sure to "
    "include all the concepts that are relevant to the system.\n\n"
    "You will receive a JSON array of records. Each record may contain fields describing "
    "agents, speakers, actions, utterances, documents, entities, topics, intents, tools, "
    "inputs, outputs, context, and metadata.\n\n"
    "Your task is to identify an EXHAUSTIVE list of all important CONCEPTS present in or "
    "implied by the data.\n\n"
    "### What counts as a concept\n"
    "A concept is any distinct entity, actor, capability, data artifact, or domain idea "
    "that plays a meaningful role in the system. Concepts fall into the following "
    "categories (use exactly these type labels):\n\n"
    "  - **query**    - The original user question or request that initiated the workflow.\n"
    "  - **agent**    - An autonomous or semi-autonomous software agent.\n"
    "  - **speaker**  - A participant in a conversation (user, assistant, or system).\n"
    "  - **service**  - A named service or application component.\n"
    "  - **llm**      - A large-language-model endpoint identified by its model name.\n"
    "  - **tool**     - An external tool invoked by an agent or system.\n"
    "  - **function** - A callable function exposed by the system.\n"
    "  - **document** - A document, contract, clause, or file being processed.\n"
    "  - **entity**   - A named entity (person, organization, location, date, etc.) "
    "extracted from or mentioned in the data.\n"
    "  - **topic**    - A subject or theme discussed in a conversation or document.\n"
    "  - **intent**   - A user intent or goal expressed in the interaction.\n"
    "  - **fact**     - A factual statement or piece of knowledge exchanged.\n"
    "  - **output**   - The final answer, response, or artifact produced.\n"
    "  - **other_concept** - Any other higher-level domain idea, capability, or data "
    "entity that is important for understanding what the system does.\n\n"
    "### Extraction instructions\n"
    "1. Scan EVERY record in the payload. Do not skip any.\n"
    "2. Extract concepts from all available fields: agent names, speakers, actions, "
    "   utterances, topics, intents, entities, document identifiers, input/output "
    "   text, tool names, context, and metadata.\n"
    "3. For **query** concepts: distil the core user question or request.\n"
    "4. For **output** concepts: distil the final answer or result.\n"
    "5. For **fact** concepts: extract key factual claims or knowledge exchanged.\n"
    "6. DEDUPLICATE: if the same logical entity appears under slightly different names, "
    "   emit it only once with the most canonical name.\n"
    "7. Every concept MUST have a detailed, informative description (2-4 sentences) "
    "   explaining what it is, what role it plays, and any notable behaviour observed.\n\n"
    "Return ONLY the list of concepts. Do NOT include relationships."
)


GENERAL_RELATIONSHIPS_PROMPT = (
    "You are an expert in multi-agent systems, conversational AI, dialogue analysis, "
    "and knowledge-graph construction.\n\n"
    "Remember that these relationships form the memory of a multi-agent system. Make sure "
    "to relate all the concepts that are relevant to the system.\n\n"
    "You will receive TWO pieces of information:\n"
    "  1. A list of CONCEPTS (each with name, type, description and metadata) that were "
    "     previously extracted from the data.\n"
    "  2. The original JSON array of raw message records from which those concepts were "
    "     extracted.\n\n"
    "Your task is to identify ALL meaningful RELATIONSHIPS between the provided concepts.\n\n"
    "### Relationship extraction instructions\n"
    "1. Consider every possible pair of concepts and determine whether the data "
    "   evidences a meaningful interaction, dependency, data flow, or semantic link.\n"
    "2. The 'source' and 'target' MUST be exact names from the provided concepts list. "
    "   Do NOT invent new concept names.\n"
    "3. Relationship labels MUST be in UPPER_SNAKE_CASE and should be descriptive verb "
    "   phrases (e.g., ASKS_ABOUT, RESPONDS_TO, DISCUSSES_TOPIC, MENTIONS_ENTITY, "
    "   EXPRESSES_INTENT, STATES_FACT, PROCESSES_DOCUMENT, EXTRACTS_ENTITY, "
    "   DELEGATES_TASK_TO, PRODUCES_OUTPUT, ANSWERS_QUERY, INVOKES_TOOL).\n"
    "4. Each relationship MUST include a one-sentence description that explains what "
    "   information or control flows between the source and target, grounded in the "
    "   data evidence.\n\n"
    "### Quality guidelines\n"
    "1. FOCUS on abstract, higher-level relationships rather than low-level details.\n"
    "2. MERGE similar or closely related relationships into a single broader one "
    "   to avoid redundancy.\n"
    "3. AVOID overlapping relationships that represent the same underlying idea.\n"
    "4. ENSURE each relationship is truly distinct and adds unique informational value.\n"
    "5. Every concept should participate in at least one relationship. If a concept is "
    "   completely isolated, reconsider whether a relationship was missed.\n"
    "6. All concepts must be related to at least one other concept."
    "Return ONLY the list of relationships."
)

SUPPORTED_FORMATS = {"openclaw"}

_CONCEPT_PROMPTS: dict[str, str] = {
    "openclaw": GENERAL_CONCEPTS_PROMPT,
}

_RELATIONSHIP_PROMPTS: dict[str, str] = {
    "openclaw": GENERAL_RELATIONSHIPS_PROMPT,
}


def get_concept_prompt(data_format: str) -> str:
    """Return the concept-extraction system prompt for the given format."""
    prompt = _CONCEPT_PROMPTS.get(data_format)
    if prompt is None:
        msg = f"Unsupported data format: {data_format!r}. Supported: {SUPPORTED_FORMATS}"
        raise ValueError(msg)
    return prompt


def get_relationship_prompt(data_format: str) -> str:
    """Return the relationship-extraction system prompt for the given format."""
    prompt = _RELATIONSHIP_PROMPTS.get(data_format)
    if prompt is None:
        msg = f"Unsupported data format: {data_format!r}. Supported: {SUPPORTED_FORMATS}"
        raise ValueError(msg)
    return prompt
