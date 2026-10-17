"""INGEST — turn a Slack conversation into structured requirements."""

from __future__ import annotations

from app.llm.client import generate_structured
from app.models import ArtifactKind, SlackMessage, StageKind
from app.orchestrator.base import ProducedArtifact, StageContext, StageFailed, StageResult
from app.schemas.requirements import Requirements
from app.store import store

#: Below this, there is no conversation to speak of — see the check in run().
MIN_CONVERSATION_CHARS = 40

SYSTEM = """\
You are a senior business analyst reading a real conversation between \
stakeholders and a project manager. Your job is to extract what is actually \
being asked for, so that a project plan can be built from it.

Work only from the conversation. Where it is silent, say so in `assumptions` or \
`open_questions` rather than inventing detail — the project manager reviews \
these before anything is built, so an honest gap is more useful than a \
confident guess.

Distinguish what stakeholders asked for from what they merely discussed. \
Casual asides, rejected ideas, and scheduling chatter are not requirements. \
If a feature was raised and then dismissed, put it in `out_of_scope`.
"""

USER_TEMPLATE = """\
Here is the conversation, oldest message first.

<conversation>
{conversation}
</conversation>

Extract the requirements.
"""

FEEDBACK_TEMPLATE = """\

The project manager reviewed your previous extraction and asked for changes:

<feedback>
{feedback}
</feedback>

Produce a corrected extraction that addresses this feedback.
"""


def format_conversation(messages: list[SlackMessage]) -> str:
    """Render captured messages as a transcript.

    Speaker names matter: the model reasons better about who wants what when
    the transcript reads like people talking rather than a list of strings.
    """
    lines = []
    for message in messages:
        who = message.user_name or message.user_id or "unknown"
        text = (message.text or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


class IngestStage:
    kind = StageKind.INGEST

    async def run(self, ctx: StageContext) -> StageResult:
        messages = await self._load_messages(ctx)

        if not messages:
            raise StageFailed(
                "No Slack messages are attached to this run. Invite the bot to the "
                "channel, have the conversation, then run /pm start again.",
                retryable=False,
            )

        conversation = format_conversation(messages)
        # Deliberately a low floor. This is here to catch an empty or accidental
        # channel ("hi", "test"), not to judge whether a brief is detailed
        # enough — a terse but real brief is legitimate, and the schema already
        # forces the model to report what it had to assume and what it still
        # needs to ask. Those surface at the approval gate, which is the right
        # place for a human to notice the input was thin.
        if len(conversation) < MIN_CONVERSATION_CHARS:
            raise StageFailed(
                f"There is barely any conversation here ({len(conversation)} characters). "
                "Describe what you want built, then re-run this stage.",
                retryable=False,
            )

        prompt = USER_TEMPLATE.format(conversation=conversation)
        if ctx.feedback:
            prompt += FEEDBACK_TEMPLATE.format(feedback=ctx.feedback)

        result = await generate_structured(
            output_model=Requirements,
            system=SYSTEM,
            user=prompt,
            max_output_tokens=16_000,
        )
        requirements = result.data

        must_have = sum(1 for f in requirements.features if f.priority == "MUST")
        summary = (
            f"{requirements.project_name}: {len(requirements.features)} features "
            f"({must_have} must-have), {len(requirements.actors)} actors, "
            f"{len(requirements.open_questions)} open questions"
        )

        return StageResult(
            artifacts=[
                ProducedArtifact(
                    kind=ArtifactKind.REQUIREMENTS,
                    name="Requirements",
                    data=requirements.model_dump(mode="json"),
                )
            ],
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            run_updates={"title": requirements.project_name},
            summary=summary,
        )

    async def _load_messages(self, ctx: StageContext) -> list[SlackMessage]:
        """Messages belonging to this run's conversation, oldest first."""
        return store.conversation_for(ctx.run)
