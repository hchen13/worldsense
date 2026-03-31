"""
Layer 2.5: LLM epsilon enrichment.

Optionally enriches personas with unique backstories via LLM calls.
This layer is entirely optional — personas work without it.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from worldsense.persona.schema import Persona


BACKSTORY_PROMPT_TEMPLATE = """\
You are generating a brief, realistic backstory for a market research persona.

Persona profile:
- Age: {age}, Gender: {gender}
- Nationality: {nationality} ({country_name})
- Occupation: {occupation_label}
- Income: {income_bracket}
- Location: {urban_rural}
- Personality: {personality_type}

Write 2-3 sentences describing this person's daily life, key life experiences, and what they care about as a consumer.
Be specific and realistic. Do NOT include any demographic labels verbatim — write naturally.
Output only the backstory paragraph, nothing else.
"""


class PersonaEnricher:
    """
    Enriches personas with LLM-generated backstories.

    This is a thin wrapper that batches LLM calls.
    Enrichment is optional — skip it when using MockBackend or offline.
    """

    def __init__(self, backend, epsilon: float = 1.0):
        """
        Args:
            backend: LLMBackend instance
            epsilon: fraction of personas to enrich (0.0-1.0)
                     1.0 = enrich all, 0.5 = enrich 50% randomly, 0.0 = skip all
        """
        self.backend = backend
        self.epsilon = epsilon

    async def enrich_batch(
        self, personas: list[Persona], concurrency: int = 5
    ) -> list[Persona]:
        """Enrich a batch of personas with backstories."""
        import random

        to_enrich = [p for p in personas if random.random() < self.epsilon]
        if not to_enrich:
            return personas

        semaphore = asyncio.Semaphore(concurrency)

        async def enrich_one(persona: Persona) -> None:
            async with semaphore:
                prompt = BACKSTORY_PROMPT_TEMPLATE.format(
                    age=persona.age,
                    gender=persona.gender,
                    nationality=persona.nationality,
                    country_name=persona.country_name,
                    occupation_label=persona.occupation_label,
                    income_bracket=persona.income_bracket,
                    urban_rural=persona.urban_rural,
                    personality_type=persona.personality_type,
                )
                try:
                    response = await self.backend.generate(prompt=prompt, schema=None)
                    if isinstance(response, dict):
                        persona.backstory = response.get("content", "")
                    else:
                        persona.backstory = str(response)
                    persona.enriched = True
                except Exception:
                    pass  # Silently skip on failure

        await asyncio.gather(*[enrich_one(p) for p in to_enrich])
        return personas

    def enrich_batch_sync(self, personas: list[Persona], concurrency: int = 5) -> list[Persona]:
        """Synchronous wrapper for enrich_batch."""
        return asyncio.run(self.enrich_batch(personas, concurrency))
