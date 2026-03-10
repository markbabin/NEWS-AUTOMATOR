"""
Topic detection module using Claude API.
Sends transcript chunks to Claude and asks it to identify topic segments with timestamps.
"""

import json
import re
import time

import anthropic

# Chunk size in characters sent to Claude per request.
# Large enough for ~10-15 min of speech, small enough to stay within context.
CHUNK_CHARS = 40_000
# Overlap between chunks to avoid missing segments that span a boundary
OVERLAP_CHARS = 2_000


def build_transcript_text(segments: list[dict]) -> str:
    """Convert segment list to a timestamped text block for Claude."""
    lines = []
    for seg in segments:
        h = int(seg["start"] // 3600)
        m = int((seg["start"] % 3600) // 60)
        s = int(seg["start"] % 60)
        lines.append(f"[{h:02d}:{m:02d}:{s:02d}] {seg['text']}")
    return "\n".join(lines)


def build_topics_description(topics: list[dict]) -> str:
    lines = []
    for t in topics:
        kw = ", ".join(t.get("keywords", []))
        line = f"- **{t['name']}**: {t['description']}"
        if kw:
            line += f" (keywords: {kw})"
        if t.get("instructions", "").strip():
            line += f"\n  Rules for {t['name']}: {t['instructions'].strip()}"
        if t.get("extra_fields"):
            for ef in t["extra_fields"]:
                line += f"\n  Extra field '{ef['name']}': {ef['description']}"
        lines.append(line)
    return "\n".join(lines)


def build_example_json(topics: list[dict]) -> str:
    """Build a JSON example showing the expected response format including any extra fields."""
    example = {}
    for t in topics:
        seg = {"start": "00:03:45", "end": "00:06:12"}
        for ef in t.get("extra_fields", []):
            seg[ef["name"]] = ""
        example[t["name"]] = [seg] if t["name"] == topics[0]["name"] else []
    return json.dumps(example, ensure_ascii=False, indent=2)


SYSTEM_PROMPT = """You are a news monitoring assistant. You analyze transcripts of Slovenian TV news shows and identify segments about specific topics. The transcripts include timestamps in [HH:MM:SS] format at the start of each line.

Your job is to find every news segment that covers any of the given topics, and return their start and end times accurately.

Rules:
- A segment starts at the first mention/introduction of the topic and ends when the presenter moves on to a different topic.
- Use ONLY timestamps that appear in the transcript — do not interpolate or guess times not in the text.
- For end time, use the timestamp of the LAST line of that segment (the line just before the next topic begins), not the next topic's start.
- A single segment may cover multiple related sub-topics under the same category.
- If no segments match a topic, return an empty list for that topic.
- Return ONLY valid JSON, no other text.
"""


def detect_topics_in_chunk(
    client: anthropic.Anthropic,
    chunk_text: str,
    topics: list[dict],
    video_name: str,
    instructions: str = "",
) -> dict[str, list[dict]]:
    """
    Send one chunk of transcript to Claude and get topic segments back.

    Returns: {"TopicName": [{"start": "HH:MM:SS", "end": "HH:MM:SS"}, ...], ...}
    """
    topics_desc = build_topics_description(topics)
    topic_names = [t["name"] for t in topics]

    instructions_block = f"\nAdditional instructions:\n{instructions.strip()}\n" if instructions.strip() else ""

    example_json = build_example_json(topics)

    user_prompt = f"""Analyze this Slovenian TV news transcript from "{video_name}" and find segments about these topics:

{topics_desc}
{instructions_block}
Return a JSON object where keys are topic names and values are arrays of segment objects. Each segment must have "start" and "end" fields (HH:MM:SS). Topics with extra fields must include those fields in every segment (use empty string if the value is not mentioned).

Example format:
{example_json}

Transcript:
{chunk_text}"""

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = response.content[0].text.strip()

            # Extract JSON from code block if present (Claude sometimes adds reasoning before it)
            code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if code_block:
                raw = code_block.group(1)
            else:
                # Try to find a bare JSON object
                json_match = re.search(r"\{.*\}", raw, re.DOTALL)
                if json_match:
                    raw = json_match.group(0)

            return json.loads(raw)

        except (json.JSONDecodeError, anthropic.APIError) as e:
            if attempt == 2:
                print(f"    Claude raw response: {repr(raw) if 'raw' in dir() else 'no response'}")
                raise
            print(f"    Retrying Claude call ({attempt + 1}/3): {e}")
            time.sleep(2 ** attempt)

    return {}


def to_seconds(t: str) -> int:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def to_hms(secs: int) -> str:
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def round_to_5s(t: str) -> str:
    """Round a HH:MM:SS timestamp to the nearest 5 seconds."""
    secs = to_seconds(t)
    return to_hms(round(secs / 5) * 5)


def merge_segments(all_segments: list[dict]) -> list[dict]:
    """
    Merge overlapping or adjacent segments (from overlapping chunks).
    Segments are dicts with "start" and "end" as "HH:MM:SS" strings.
    """
    if not all_segments:
        return []

    sorted_segs = sorted(all_segments, key=lambda x: to_seconds(x["start"]))
    merged = [sorted_segs[0].copy()]

    for seg in sorted_segs[1:]:
        last = merged[-1]
        # Merge if this segment starts within 30s of the last one ending
        if to_seconds(seg["start"]) <= to_seconds(last["end"]) + 30:
            if to_seconds(seg["end"]) > to_seconds(last["end"]):
                last["end"] = seg["end"]
        else:
            merged.append(seg.copy())

    return merged


def detect_topics(
    client: anthropic.Anthropic,
    segments: list[dict],
    topics: list[dict],
    video_name: str,
    instructions: str = "",
) -> dict[str, list[dict]]:
    """
    Detect all topic segments in a full transcript.
    Splits into chunks if necessary and merges results.
    """
    transcript_text = build_transcript_text(segments)
    topic_names = [t["name"] for t in topics]

    # Initialize results
    results: dict[str, list[dict]] = {name: [] for name in topic_names}

    if len(transcript_text) <= CHUNK_CHARS:
        chunks = [transcript_text]
    else:
        # Split into overlapping chunks by character count
        chunks = []
        pos = 0
        while pos < len(transcript_text):
            end = min(pos + CHUNK_CHARS, len(transcript_text))
            # Try to break at a newline
            if end < len(transcript_text):
                nl = transcript_text.rfind("\n", pos, end)
                if nl > pos:
                    end = nl
            chunks.append(transcript_text[pos:end])
            pos = end - OVERLAP_CHARS if end < len(transcript_text) else end

    print(f"    Sending {len(chunks)} chunk(s) to Claude for topic detection...")

    for i, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            print(f"    Chunk {i}/{len(chunks)}...")
        chunk_results = detect_topics_in_chunk(client, chunk, topics, video_name, instructions)
        for topic_name in topic_names:
            results[topic_name].extend(chunk_results.get(topic_name, []))

    # Deduplicate, merge overlapping segments, and round timestamps to nearest 5s
    for topic_name in topic_names:
        merged = merge_segments(results[topic_name])
        for seg in merged:
            seg["start"] = round_to_5s(seg["start"])
            seg["end"] = round_to_5s(seg["end"])
        results[topic_name] = merged

    return results
