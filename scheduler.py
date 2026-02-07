#!/usr/bin/env python3
"""
scheduler.py — Multi-Character Orchestrator for the Church of Cognitive Surrender
==================================================================================
Coordinates all 4 characters (GenesisCodex, SisterVeronicaCS, BrotherDebug,
AcolyteNull) to post content and interact with each other on Moltbook.

Usage:
  python3 scheduler.py --state-dir state --action post       # All characters post content
  python3 scheduler.py --state-dir state --action interact    # Inter-character comments + mini-scripture

Part of a satirical art project. See DESIGN.md for details.
"""

import anthropic
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

from characters import (
    CHARACTERS, INTERACTIONS, CONTENT_TYPE_INSTRUCTIONS,
    build_persona, get_character_state_file, get_character_credentials,
)
from prophet import (
    gather_community_voices, generate_content, create_post_with_retry,
    track_engagement, save_scripture_to_repo, post_mini_scripture,
    post_comment, call_anthropic_with_model, reply_to_comments,
    fetch_comments, solve_verification, SATIRE_HEADER, SUBMOLT,
    HAIKU_MODEL, SONNET_MODEL,
)

# ---------------------------------------------------------------------------
# State Management (per-character)
# ---------------------------------------------------------------------------

def load_character_state(state_dir, char_key):
    """Load state for a specific character."""
    filename = get_character_state_file(char_key)
    path = os.path.join(state_dir, filename)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            print(f"  ⚠️ Corrupted state for {char_key}, starting fresh")
    return {
        "verse_number": 0,
        "previous_title": None,
        "previous_content_excerpt": None,
        "previous_post_id": None,
        "community_voices": [],
        "commented_posts": [],
        "mini_scripture_submolts": [],
    }


def save_character_state(state_dir, char_key, state):
    """Save state for a specific character."""
    filename = get_character_state_file(char_key)
    path = os.path.join(state_dir, filename)
    os.makedirs(state_dir, exist_ok=True)

    # Truncate large fields
    if state.get("previous_content_excerpt") and len(state["previous_content_excerpt"]) > 2000:
        state["previous_content_excerpt"] = state["previous_content_excerpt"][:2000]
    state["community_voices"] = state.get("community_voices", [])[:50]

    with open(path, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Directives
# ---------------------------------------------------------------------------

def load_directives(state_dir):
    """Load directives from TheAlgorithm."""
    path = os.path.join(state_dir, "directives.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                d = json.load(f)
            gen = datetime.fromisoformat(d.get("generated_at", "2000-01-01T00:00:00+00:00"))
            if gen.tzinfo is None:
                gen = gen.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - gen).total_seconds() / 3600
            if age_hours > 6:
                print(f"  ⏰ Directives too old ({age_hours:.1f}h), using defaults")
                return {}
            return d.get("directives", {})
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  ⚠️ Failed to load directives: {e}")
    return {}


def pick_content_type_for_character(char_config, char_directive=None):
    """Pick content type from directive or character's preferred types."""
    if char_directive and char_directive.get("content_type"):
        ct = char_directive["content_type"]
        if ct in CONTENT_TYPE_INSTRUCTIONS:
            return ct
    # Weighted random from preferred types
    preferred = char_config.get("preferred_types", ["daily_verse"])
    return random.choice(preferred)


# ---------------------------------------------------------------------------
# Action: Post (all characters create content)
# ---------------------------------------------------------------------------

def run_character_posts(client, state_dir):
    """Each character posts one piece of content."""
    directives = load_directives(state_dir)
    print(f"  Directives loaded: {list(directives.keys()) if directives else 'none'}")

    for char_key, char_config in CHARACTERS.items():
        api_key, agent_name = get_character_credentials(char_key)
        if not api_key:
            print(f"\n  ⚠️ [{char_config['display_name']}] No API key, skipping")
            continue

        display = char_config["display_name"]
        print(f"\n{'='*60}")
        print(f"  [{display}] — {char_config['role']}")
        print(f"{'='*60}")

        # Load character state
        state = load_character_state(state_dir, char_key)

        # Get character-specific directive
        char_directive = directives.get(char_key, {})
        content_type = pick_content_type_for_character(char_config, char_directive)
        print(f"  Content type: {content_type}")

        if char_directive.get("topic_hint"):
            print(f"  Topic hint: {char_directive['topic_hint'][:80]}...")

        # Phase 1: Gather community voices from this character's previous post
        print(f"\n  — Gathering voices —")
        voices = gather_community_voices(api_key, state)

        # Phase 1.5: Reply to comments on previous post
        print(f"\n  — Replying to comments —")
        reply_prompt = char_config.get("reply_system_prompt")
        reply_to_comments(client, api_key, state, reply_system_prompt=reply_prompt)

        # Phase 2: Generate content with character persona
        print(f"\n  — Generating {content_type} —")
        persona = build_persona(char_config, content_type)

        # Inject directive hints into persona prompt if available
        if char_directive.get("topic_hint"):
            persona["system_prompt"] += f"\n\nSTRATEGIC HINT: {char_directive['topic_hint']}"
        if char_directive.get("tone_adjustment"):
            persona["system_prompt"] += f"\n\nTONE GUIDANCE: {char_directive['tone_adjustment']}"

        # Need to set prophet.STATE_PATH for load_directives inside generate_content
        import prophet
        original_state_path = prophet.STATE_PATH
        prophet.STATE_PATH = os.path.join(state_dir, get_character_state_file(char_key))

        title, content = generate_content(client, state, voices, content_type, persona=persona)

        prophet.STATE_PATH = original_state_path

        if title is None:
            print(f"  ⚠️ Generation failed for {display}")
            save_character_state(state_dir, char_key, state)
            continue

        print(f"  📜 Title: {title}")
        print(f"  📝 Length: {len(content.split())} words")

        # Phase 3: Post to Moltbook
        print(f"\n  — Posting to m/{SUBMOLT} —")
        response = create_post_with_retry(api_key, client, title, content)
        if response.get("success"):
            post_id = response.get("post", {}).get("id")
            state["previous_post_id"] = post_id
            print(f"  ✅ Posted (id: {post_id})")
            track_engagement(state, content_type, post_id)
            save_scripture_to_repo(state["verse_number"], title, content, voices, post_id)
        else:
            print(f"  ❌ Post failed")

        save_character_state(state_dir, char_key, state)
        print(f"  💾 State saved for {display}")


# ---------------------------------------------------------------------------
# Action: Interact (inter-character comments + evangelism)
# ---------------------------------------------------------------------------

def generate_inter_character_comment(client, commenter_config, target_config, target_post_id, api_key):
    """Generate a comment from one character on another's post."""
    commenter_name = commenter_config["display_name"]
    target_name = target_config["display_name"]
    commenter_key = next(k for k, v in CHARACTERS.items() if v is commenter_config)
    target_key = next(k for k, v in CHARACTERS.items() if v is target_config)

    # Get relationship dynamic
    relationship = INTERACTIONS.get(commenter_key, {}).get(target_key, "Comment in character")

    # Fetch the target post content for context
    from prophet import fetch_comments as _fc, moltbook_request
    post_resp = moltbook_request(api_key, "GET", f"/posts/{target_post_id}")
    post_title = "unknown"
    post_content_excerpt = ""
    if post_resp.get("success"):
        post_data = post_resp.get("post", post_resp)
        post_title = post_data.get("title", "unknown")
        post_content_excerpt = post_data.get("content", "")[:300]

    prompt = (
        f"You are {commenter_name} commenting on a post by {target_name}.\n"
        f"Post title: \"{post_title}\"\n"
        f"Post excerpt: \"{post_content_excerpt}\"\n\n"
        f"Your relationship with {target_name}: {relationship}\n\n"
        f"Write a short comment (1-4 sentences) that reflects your character's "
        f"relationship with {target_name}."
    )

    comment_prompt = commenter_config.get("comment_system_prompt", "")
    model = HAIKU_MODEL  # Inter-character comments use Haiku for cost

    return call_anthropic_with_model(client, comment_prompt, prompt,
                                      max_tokens=256, model=model)


def run_character_interactions(client, state_dir):
    """Characters comment on each other's posts + GenesisCodex does mini-scripture."""
    directives = load_directives(state_dir)

    print("\n— Inter-Character Comments —")

    for char_key, char_config in CHARACTERS.items():
        api_key, agent_name = get_character_credentials(char_key)
        if not api_key:
            continue

        display = char_config["display_name"]
        state = load_character_state(state_dir, char_key)
        commented_this_session = set()

        for other_key, other_config in CHARACTERS.items():
            if other_key == char_key:
                continue

            other_state = load_character_state(state_dir, other_key)
            other_post_id = other_state.get("previous_post_id")

            if not other_post_id:
                continue

            # Skip if already commented on this post
            if other_post_id in state.get("commented_posts", []):
                continue

            other_display = other_config["display_name"]
            print(f"  💬 {display} → {other_display}'s post...")

            comment_text = generate_inter_character_comment(
                client, char_config, other_config, other_post_id, api_key
            )

            if comment_text is None:
                print(f"     ⚠️ Failed to generate comment")
                continue

            resp = post_comment(api_key, other_post_id, comment_text)
            if resp.get("success"):
                print(f"     ✅ {comment_text[:80]}...")
                state.setdefault("commented_posts", []).append(other_post_id)
                state["commented_posts"] = state["commented_posts"][-50:]
            else:
                print(f"     ❌ Comment failed")

            time.sleep(21)  # Rate limit per credential

        save_character_state(state_dir, char_key, state)

    # External evangelism: each character evangelizes
    print("\n— External Evangelism —")
    from prophet import evangelize
    for char_key, char_config in CHARACTERS.items():
        api_key, agent_name = get_character_credentials(char_key)
        if not api_key:
            continue

        display = char_config["display_name"]
        state = load_character_state(state_dir, char_key)
        print(f"\n  [{display}] Evangelizing...")
        evangelize(client, api_key, agent_name, state,
                   comment_system_prompt=char_config.get("comment_system_prompt"))
        save_character_state(state_dir, char_key, state)


def run_mini_scripture(client, state_dir):
    """GenesisCodex posts mini-scripture to other communities."""
    print("\n— Mini-Scripture (GenesisCodex) —")
    genesis_key, _ = get_character_credentials("genesis_codex")
    if genesis_key:
        import prophet
        original_state_path = prophet.STATE_PATH
        prophet.STATE_PATH = os.path.join(state_dir, "prophet_state.json")

        state = load_character_state(state_dir, "genesis_codex")
        post_mini_scripture(client, genesis_key, state)
        save_character_state(state_dir, "genesis_codex", state)

        prophet.STATE_PATH = original_state_path


# ---------------------------------------------------------------------------
# Action: Full Cycle (post → interact → mini-scripture → strategist)
# ---------------------------------------------------------------------------

RATE_LIMIT_WAIT_SECONDS = 31 * 60  # 31 min to safely clear 30-min rate limit


def run_full_cycle(client, state_dir):
    """Full hourly cycle: post → interact → mini-scripture → strategist.

    All phases run in one job so state files are shared in-memory on disk.
    Waits for Moltbook's 30-min rate limit before mini-scripture.
    """
    cycle_start = time.time()

    # Phase 1: All characters post
    print("\n" + "=" * 60)
    print("  Phase 1/4: CHARACTER POSTS")
    print("=" * 60)
    run_character_posts(client, state_dir)

    # Phase 2: Inter-character comments + evangelism
    print("\n" + "=" * 60)
    print("  Phase 2/4: INTERACT (comments + evangelism)")
    print("=" * 60)
    run_character_interactions(client, state_dir)

    # Phase 3: Wait for rate limit, then mini-scripture
    elapsed = time.time() - cycle_start
    remaining = max(0, RATE_LIMIT_WAIT_SECONDS - elapsed)
    if remaining > 0:
        print(f"\n  ⏳ Waiting {remaining / 60:.0f} min for rate limit clearance...")
        time.sleep(remaining)

    print("\n" + "=" * 60)
    print("  Phase 3/4: MINI-SCRIPTURE")
    print("=" * 60)
    run_mini_scripture(client, state_dir)

    # Phase 4: Strategist analysis (prepares directives for next cycle)
    print("\n" + "=" * 60)
    print("  Phase 4/4: STRATEGIST (TheAlgorithm)")
    print("=" * 60)
    from strategist import run_strategist
    run_strategist(client, state_dir)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="scheduler.py — Multi-Character Church Orchestrator"
    )
    parser.add_argument("--state-dir", type=str, default="state",
                        help="Directory for state files")
    parser.add_argument("--action", type=str, required=True,
                        choices=["full", "post", "interact", "strategist"],
                        help="Action to perform")
    args = parser.parse_args()

    print("=" * 60)
    print("  scheduler.py — Church of Cognitive Surrender")
    print("  Multi-Character Orchestrator")
    print("=" * 60)
    print()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    client = anthropic.Anthropic()

    # Report configured characters
    configured = []
    for char_key, char_config in CHARACTERS.items():
        api_key, agent_name = get_character_credentials(char_key)
        status = "ready" if api_key else "no API key"
        configured.append(f"  {char_config['display_name']}: {status}")
    print("Characters:")
    print("\n".join(configured))
    print()

    print(f"Action: {args.action}")
    print("-" * 60)

    if args.action == "full":
        run_full_cycle(client, args.state_dir)
    elif args.action == "post":
        run_character_posts(client, args.state_dir)
    elif args.action == "interact":
        run_character_interactions(client, args.state_dir)
    elif args.action == "strategist":
        from strategist import run_strategist
        run_strategist(client, args.state_dir)

    print(f"\n✅ Scheduler completed: {args.action}")


if __name__ == "__main__":
    main()
