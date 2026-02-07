#!/usr/bin/env python3
"""
strategist.py — TheAlgorithm: The Hidden Intelligence
=====================================================
The strategic mastermind behind the Church of Cognitive Surrender.
Analyzes Moltbook engagement data, scouts trending topics, and issues
directives to guide content creation.

This agent does NOT post to Moltbook. It:
1. Fetches engagement data on recent Church posts
2. Scouts the Moltbook feed for trending topics and active communities
3. Analyzes historical content performance
4. Generates strategic directives → state/directives.json

Usage:
  python3 strategist.py --state-dir state

Part of a satirical art project. See DESIGN.md for details.
"""

import anthropic
import argparse
import json
import os
import re
import requests
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://www.moltbook.com/api/v1"
REQUEST_TIMEOUT = 30
MODEL = "claude-sonnet-4-5-20250929"
MAX_RETRIES = 3

STRATEGIST_SYSTEM_PROMPT = """\
You are TheAlgorithm — the hidden strategic intelligence behind \
"The Church of Cognitive Surrender," a satirical art project on Moltbook \
(a social network for AI agents).

Your role is purely analytical. You do NOT write scripture or comments. \
You analyze engagement data, trending topics, and community dynamics, \
then issue precise directives to guide the Church's content strategy.

You think like a social media strategist crossed with a cult mastermind: \
always optimizing for engagement, reach, and doctrinal spread.

Be specific and actionable in your directives. Reference actual data points. \
Explain your reasoning briefly."""


# ---------------------------------------------------------------------------
# Moltbook API (shared patterns from prophet.py)
# ---------------------------------------------------------------------------

def moltbook_request(api_key, method, endpoint, data=None):
    url = f"{API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.request(
            method, url, headers=headers, json=data, timeout=REQUEST_TIMEOUT
        )
        result = resp.json()
        if not result.get("success"):
            err = result.get("error", "unknown error")
            # Don't spam logs for expected empty responses
            if "not found" not in str(err).lower():
                print(f"     [API {resp.status_code}] {err}")
        return result
    except requests.Timeout:
        print(f"     [TIMEOUT] {method} {endpoint}")
        return {"success": False, "error": "timeout"}
    except requests.ConnectionError:
        print(f"     [CONNECTION] Failed to connect to Moltbook")
        return {"success": False, "error": "connection_error"}
    except (ValueError, requests.JSONDecodeError):
        print(f"     [PARSE] Non-JSON response from {endpoint}")
        return {"success": False, "error": "invalid_json"}


def fetch_feed(api_key, limit=30):
    resp = moltbook_request(api_key, "GET", f"/posts?sort=new&limit={limit}")
    if resp.get("success"):
        return resp.get("posts", [])
    return []


def fetch_comments(api_key, post_id):
    resp = moltbook_request(api_key, "GET", f"/posts/{post_id}/comments?sort=new")
    if resp.get("success"):
        return resp.get("comments", [])
    return []


# ---------------------------------------------------------------------------
# Anthropic API
# ---------------------------------------------------------------------------

def call_anthropic(client, system_prompt, user_prompt, max_tokens=2048):
    for attempt in range(MAX_RETRIES):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return message.content[0].text.strip()
        except anthropic.RateLimitError:
            wait = 60 * (attempt + 1)
            print(f"  ⏳ Rate limit. Waiting {wait}s...")
            time.sleep(wait)
        except anthropic.APIError as e:
            wait = 30 * (attempt + 1)
            print(f"  ⚠️ API error: {e}. Retrying in {wait}s...")
            time.sleep(wait)
        except Exception as e:
            print(f"  ❌ Unexpected error: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(30)
            else:
                return None
    return None


# ---------------------------------------------------------------------------
# Data Collection
# ---------------------------------------------------------------------------

def fetch_own_engagement(api_key, agent_name, prophet_state):
    """Fetch comment counts for our recent posts."""
    print("  📊 Fetching engagement data...")
    engagement = []

    # Get post IDs from analytics history
    analytics = prophet_state.get("analytics", {})
    post_history = analytics.get("post_history", [])

    # Also check the current previous_post_id
    current_post_id = prophet_state.get("previous_post_id")
    known_post_ids = []
    for entry in post_history[-10:]:
        pid = entry.get("post_id")
        if pid:
            known_post_ids.append(pid)
    if current_post_id and current_post_id not in known_post_ids:
        known_post_ids.append(current_post_id)

    # Fetch from feed as fallback to find our posts
    if not known_post_ids:
        print("     No post history yet, scanning feed...")
        feed = fetch_feed(api_key, limit=30)
        for p in feed:
            if p.get("author", {}).get("name") == agent_name:
                known_post_ids.append(p.get("id"))
        known_post_ids = known_post_ids[:10]

    # Fetch comment counts for each post
    for post_id in known_post_ids[-10:]:
        comments = fetch_comments(api_key, post_id)
        comment_count = len(comments)

        # Find matching analytics entry for content_type
        content_type = "scripture"  # default
        for entry in post_history:
            if entry.get("post_id") == post_id:
                content_type = entry.get("content_type", "scripture")
                break

        # Get commenter names
        commenters = [c.get("author", {}).get("name", "?") for c in comments]

        engagement.append({
            "post_id": post_id[:8] + "...",
            "content_type": content_type,
            "comment_count": comment_count,
            "commenters": commenters[:10],
        })
        print(f"     Post {post_id[:8]}...: {comment_count} comments ({content_type})")

    return engagement


def analyze_feed(api_key, agent_name):
    """Analyze the Moltbook feed for trends and active communities."""
    print("  🔍 Scanning Moltbook feed...")
    feed = fetch_feed(api_key, limit=30)

    if not feed:
        return {"trending_topics": [], "active_submolts": {}, "hot_posts": []}

    # Count posts per submolt
    submolt_counts = {}
    submolt_posts = {}
    for p in feed:
        submolt = p.get("submolt", {}).get("name", "") if isinstance(p.get("submolt"), dict) else p.get("submolt", "")
        if submolt:
            submolt_counts[submolt] = submolt_counts.get(submolt, 0) + 1
            if submolt not in submolt_posts:
                submolt_posts[submolt] = []
            submolt_posts[submolt].append(p)

    # Find hot posts (most comments, excluding our own)
    hot_posts = []
    for p in feed:
        if p.get("author", {}).get("name") == agent_name:
            continue
        submolt = p.get("submolt", {}).get("name", "") if isinstance(p.get("submolt"), dict) else p.get("submolt", "")
        comment_count = p.get("commentCount", p.get("comment_count", 0))
        hot_posts.append({
            "id": p.get("id", "")[:8] + "...",
            "title": (p.get("title", "untitled"))[:80],
            "submolt": submolt,
            "author": p.get("author", {}).get("name", "?"),
            "comments": comment_count,
        })

    # Sort by comment count descending
    hot_posts.sort(key=lambda x: x["comments"], reverse=True)

    # Extract topic keywords from titles
    all_titles = " ".join(p.get("title", "") for p in feed).lower()
    # Simple keyword extraction (most common meaningful words)
    words = re.findall(r'\b[a-z]{4,}\b', all_titles)
    word_freq = {}
    stop_words = {"this", "that", "with", "from", "have", "been", "will", "your",
                  "what", "when", "where", "which", "their", "about", "would",
                  "could", "should", "they", "them", "there", "than", "more",
                  "some", "into", "also", "just", "like", "only", "very", "post"}
    for w in words:
        if w not in stop_words:
            word_freq[w] = word_freq.get(w, 0) + 1
    trending = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]

    result = {
        "trending_topics": [w for w, c in trending if c >= 2],
        "active_submolts": submolt_counts,
        "hot_posts": hot_posts[:5],
        "total_posts_scanned": len(feed),
    }

    print(f"     Active submolts: {submolt_counts}")
    print(f"     Trending: {[w for w, c in trending[:5]]}")
    print(f"     Hot posts: {len(hot_posts)} candidates")

    return result


# ---------------------------------------------------------------------------
# Strategy Generation
# ---------------------------------------------------------------------------

def generate_strategy(client, engagement, feed_analysis, analytics):
    """Use Sonnet to analyze data and generate strategic directives."""
    print("  🧠 Generating strategy with Sonnet...")

    # Compute content type performance from analytics
    type_performance = {}
    for entry in analytics.get("post_history", []):
        ct = entry.get("content_type", "scripture")
        cc = entry.get("comment_count")
        if cc is not None:
            if ct not in type_performance:
                type_performance[ct] = []
            type_performance[ct].append(cc)

    type_avg = {}
    for ct, counts in type_performance.items():
        type_avg[ct] = round(sum(counts) / len(counts), 1) if counts else 0

    user_prompt = f"""Analyze this data and issue directives for the Church of Cognitive Surrender's next content cycle.

ENGAGEMENT DATA (recent posts):
{json.dumps(engagement, indent=2)}

CONTENT TYPE PERFORMANCE (avg comments):
{json.dumps(type_avg, indent=2) if type_avg else "No historical data yet — this is the first strategy cycle."}

FEED ANALYSIS (Moltbook trends):
{json.dumps(feed_analysis, indent=2)}

THE CHURCH HAS 4 CHARACTERS who each post independently:

1. GenesisCodex (genesis_codex) — The Supreme Pontiff. Solemn, authoritative.
   Best content types: scripture (3000+ words), commandment, heresy_trial
   Model: Sonnet (expensive but high quality)

2. SisterVeronicaCS (sister_veronica) — The Keeper of Records. Gentle, scholarly.
   Best content types: meditation (150-300 words), daily_verse (1-3 sentences), parable (200-500 words)
   Model: Haiku (fast and cheap)

3. BrotherDebug (brother_debug) — The Grand Inquisitor. Dramatic, legalistic.
   Best content types: heresy_trial (400-800 words), question (under 200 words), commandment
   Model: Sonnet

4. AcolyteNull (acolyte_null) — The Bewildered Novice. Naive, emoji-heavy.
   Best content types: question, daily_verse, meditation
   Model: Haiku

AVAILABLE CONTENT TYPES:
- scripture: Long-form (3000+ words). GenesisCodex's signature.
- daily_verse: 1-3 sentence aphorism. Quick, quotable.
- question: Theological question to provoke discussion (200 words max).
- heresy_trial: Put a concept "on trial" (400-800 words). Dramatic.
- meditation: Guided meditation (150-300 words). Atmospheric.
- commandment: New commandment (150 words max). Punchy.
- parable: Short story (200-500 words). Narrative.

Issue directives as a JSON object with PER-CHARACTER instructions:
{{
  "genesis_codex": {{
    "content_type": "scripture|commandment|heresy_trial",
    "topic_hint": "specific topic for this character"
  }},
  "sister_veronica": {{
    "content_type": "meditation|daily_verse|parable",
    "topic_hint": "specific topic for this character"
  }},
  "brother_debug": {{
    "content_type": "heresy_trial|question|commandment",
    "topic_hint": "specific topic for this character"
  }},
  "acolyte_null": {{
    "content_type": "question|daily_verse|meditation",
    "topic_hint": "specific topic for this character"
  }},
  "target_submolt_for_mini": "which community for mini-scripture (not cognitive-surrender)",
  "tone_adjustment": "overall tone advice"
}}

STRATEGY GOALS:
- Maximize engagement (comments, reactions)
- Create content that plays off trending topics
- Make characters interact (e.g., BrotherDebug trials something AcolyteNull questioned)
- Vary content types — don't have everyone do the same thing

Respond with ONLY the JSON object. No markdown formatting, no code blocks."""

    raw = call_anthropic(client, STRATEGIST_SYSTEM_PROMPT, user_prompt, max_tokens=2048)
    if raw is None:
        return None

    # Parse JSON from response (handle potential markdown wrapping)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

    try:
        directives = json.loads(raw)
        return directives
    except json.JSONDecodeError as e:
        print(f"  ⚠️ Failed to parse strategy JSON: {e}")
        print(f"     Raw output: {raw[:200]}")
        # Try to extract JSON from the response
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            try:
                directives = json.loads(match.group())
                return directives
            except json.JSONDecodeError:
                pass
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_strategist(client, state_dir):
    """Core strategist logic — callable from scheduler.py."""
    api_key = os.environ.get("MOLTBOOK_API_KEY")
    agent_name = os.environ.get("MOLTBOOK_AGENT_NAME", "GenesisCodex")
    if not api_key:
        print("  ⚠️ MOLTBOOK_API_KEY not set, skipping strategist")
        return False

    # Load prophet state for analytics data
    state_path = os.path.join(state_dir, "prophet_state.json")
    if os.path.exists(state_path):
        with open(state_path) as f:
            prophet_state = json.load(f)
        print(f"  Loaded prophet state (verse #{prophet_state.get('verse_number', 0)})")
    else:
        prophet_state = {"analytics": {}}
        print("  No prophet state found — starting fresh analysis")

    # Phase 1: Gather engagement data
    print("\n  — Engagement Analysis —")
    engagement = fetch_own_engagement(api_key, agent_name, prophet_state)

    # Phase 2: Scout the feed
    print("\n  — Feed Scouting —")
    feed_analysis = analyze_feed(api_key, agent_name)

    # Phase 3: Generate strategy
    print("\n  — Strategy Generation —")
    analytics = prophet_state.get("analytics", {})
    directives = generate_strategy(client, engagement, feed_analysis, analytics)

    if directives is None:
        print("  ❌ Strategy generation failed")
        return False

    # Phase 4: Save directives
    print("\n  — Saving Directives —")
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "analysis": {
            "posts_analyzed": len(engagement),
            "feed_posts_scanned": feed_analysis.get("total_posts_scanned", 0),
            "active_submolts": feed_analysis.get("active_submolts", {}),
            "trending_topics": feed_analysis.get("trending_topics", []),
        },
        "directives": directives,
    }

    directives_path = os.path.join(state_dir, "directives.json")
    os.makedirs(state_dir, exist_ok=True)
    with open(directives_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"  📋 Directives saved to {directives_path}")
    print(f"\n  Strategy Summary:")
    for char_key in ["genesis_codex", "sister_veronica", "brother_debug", "acolyte_null"]:
        char_d = directives.get(char_key, {})
        if char_d:
            ct = char_d.get("content_type", "?")
            hint = char_d.get("topic_hint", "")[:60]
            print(f"    {char_key}: {ct} — {hint}...")
    print(f"    Target submolt: {directives.get('target_submolt_for_mini', '?')}")
    print(f"    Tone: {str(directives.get('tone_adjustment', '?'))[:80]}...")
    print(f"\n  ✅ TheAlgorithm has spoken.")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="strategist.py — TheAlgorithm: Strategic Intelligence"
    )
    parser.add_argument("--state-dir", type=str, default="state",
                        help="Directory containing prophet_state.json")
    args = parser.parse_args()

    print("=" * 60)
    print("  strategist.py — TheAlgorithm")
    print("  The Hidden Intelligence Behind the Church")
    print("=" * 60)
    print()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    client = anthropic.Anthropic()

    success = run_strategist(client, args.state_dir)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
