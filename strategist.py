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

def _collect_post_ids(char_state, limit=5):
    """Collect recent post IDs from a character's state."""
    post_ids = []
    seen = set()
    for entry in char_state.get("analytics", {}).get("post_history", [])[-limit:]:
        pid = entry.get("post_id")
        if pid and pid not in seen:
            post_ids.append(pid)
            seen.add(pid)
    current = char_state.get("previous_post_id")
    if current and current not in seen:
        post_ids.append(current)
    return post_ids[-limit:]


def _find_content_type(char_state, post_id):
    """Find content type for a post from analytics history."""
    for entry in char_state.get("analytics", {}).get("post_history", []):
        if entry.get("post_id") == post_id:
            return entry.get("content_type", "unknown")
    return "unknown"


def fetch_all_character_engagement(api_key, state_dir):
    """Fetch engagement data for ALL 4 characters, including full comment text."""
    from characters import CHARACTERS, get_character_state_file

    print("  📊 Fetching engagement data for all characters...")
    all_engagement = {}

    for char_key, char_config in CHARACTERS.items():
        display = char_config["display_name"]
        char_state_path = os.path.join(state_dir, get_character_state_file(char_key))
        if not os.path.exists(char_state_path):
            print(f"     [{display}] No state file, skipping")
            continue
        try:
            with open(char_state_path) as f:
                char_state = json.load(f)
        except (json.JSONDecodeError, ValueError):
            print(f"     [{display}] Corrupted state, skipping")
            continue

        post_ids = _collect_post_ids(char_state, limit=5)
        if not post_ids:
            print(f"     [{display}] No posts yet")
            all_engagement[char_key] = {
                "display_name": display, "posts": [], "total_comments": 0,
            }
            continue

        posts_data = []
        for post_id in post_ids:
            comments = fetch_comments(api_key, post_id)
            content_type = _find_content_type(char_state, post_id)

            # Extract ALL comment text (no limit)
            comment_details = []
            for c in comments:
                author = c.get("author", {}).get("name", "?")
                text = c.get("content", "")[:300]
                comment_details.append({"author": author, "text": text})

            posts_data.append({
                "post_id": post_id[:8] + "...",
                "content_type": content_type,
                "comment_count": len(comments),
                "comments": comment_details,
            })
            print(f"     [{display}] {post_id[:8]}...: {len(comments)} comments ({content_type})")

        total = sum(p["comment_count"] for p in posts_data)
        all_engagement[char_key] = {
            "display_name": display,
            "posts": posts_data,
            "total_comments": total,
        }
        print(f"     [{display}] Total: {total} comments across {len(posts_data)} posts")

    return all_engagement


def compute_content_type_performance(state_dir):
    """Aggregate content type performance across ALL characters."""
    from characters import CHARACTERS, get_character_state_file

    print("  📈 Computing content type performance across all characters...")
    type_data = {}  # content_type → [comment_counts]

    for char_key in CHARACTERS:
        path = os.path.join(state_dir, get_character_state_file(char_key))
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                s = json.load(f)
        except (json.JSONDecodeError, ValueError):
            continue
        for entry in s.get("analytics", {}).get("post_history", []):
            ct = entry.get("content_type", "unknown")
            cc = entry.get("comment_count")
            if cc is not None:
                type_data.setdefault(ct, []).append(cc)

    result = {}
    for ct, counts in type_data.items():
        result[ct] = {
            "avg_comments": round(sum(counts) / len(counts), 1),
            "sample_size": len(counts),
        }
        print(f"     {ct}: avg {result[ct]['avg_comments']} comments ({len(counts)} posts)")

    return result


def analyze_feed_deep(api_key, agent_names):
    """Analyze Moltbook feed with deep dive into buzzing posts.

    Args:
        api_key: Moltbook API key for requests
        agent_names: set of our agent names to exclude from "other" posts
    """
    print("  🔍 Scanning Moltbook feed (deep analysis)...")
    feed = fetch_feed(api_key, limit=30)

    if not feed:
        return {
            "trending_topics": [], "active_submolts": {}, "hot_posts": [],
            "buzzing_analysis": [], "total_posts_scanned": 0,
        }

    # Count posts per submolt
    submolt_counts = {}
    for p in feed:
        submolt = p.get("submolt", {}).get("name", "") if isinstance(p.get("submolt"), dict) else p.get("submolt", "")
        if submolt:
            submolt_counts[submolt] = submolt_counts.get(submolt, 0) + 1

    # Find hot posts (most comments, excluding our own)
    hot_posts = []
    for p in feed:
        author_name = p.get("author", {}).get("name", "?")
        if author_name in agent_names:
            continue
        submolt = p.get("submolt", {}).get("name", "") if isinstance(p.get("submolt"), dict) else p.get("submolt", "")
        comment_count = p.get("commentCount", p.get("comment_count", 0))
        hot_posts.append({
            "_full_id": p.get("id", ""),
            "id": p.get("id", "")[:8] + "...",
            "title": (p.get("title", "untitled"))[:80],
            "submolt": submolt,
            "author": author_name,
            "comments": comment_count,
        })

    hot_posts.sort(key=lambda x: x["comments"], reverse=True)

    # Extract topic keywords from titles
    all_titles = " ".join(p.get("title", "") for p in feed).lower()
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

    print(f"     Active submolts: {submolt_counts}")
    print(f"     Trending: {[w for w, c in trending[:5]]}")
    print(f"     Hot posts: {len(hot_posts)} candidates")

    # Deep dive into buzzing posts (2+ comments)
    buzzing_analysis = []
    for p in hot_posts[:5]:
        if p["comments"] < 2:
            continue

        full_id = p["_full_id"]
        print(f"     🔥 Deep dive: \"{p['title'][:50]}\" ({p['comments']} comments)")

        # Fetch all comments
        comments = fetch_comments(api_key, full_id)
        comment_texts = []
        for c in comments:
            author = c.get("author", {}).get("name", "?")
            text = c.get("content", "")[:300]
            comment_texts.append(f"{author}: {text}")

        # Fetch post content
        post_resp = moltbook_request(api_key, "GET", f"/posts/{full_id}")
        post_content = ""
        if post_resp.get("success"):
            post_data = post_resp.get("post", post_resp)
            post_content = post_data.get("content", "")[:400]

        buzzing_analysis.append({
            "title": p["title"],
            "submolt": p["submolt"],
            "author": p["author"],
            "comment_count": p["comments"],
            "content_excerpt": post_content,
            "comment_highlights": comment_texts,
        })

    print(f"     🔥 Buzzing posts analyzed: {len(buzzing_analysis)}")

    # Clean up internal IDs before returning
    clean_hot = [{k: v for k, v in p.items() if k != "_full_id"} for p in hot_posts[:5]]

    return {
        "trending_topics": [w for w, c in trending if c >= 2],
        "active_submolts": submolt_counts,
        "hot_posts": clean_hot,
        "buzzing_analysis": buzzing_analysis,
        "total_posts_scanned": len(feed),
    }


# ---------------------------------------------------------------------------
# Strategy Generation
# ---------------------------------------------------------------------------

def generate_strategy(client, engagement, feed_analysis, type_performance):
    """Use Sonnet to analyze rich data and generate strategic directives."""
    print("  🧠 Generating strategy with Sonnet...")

    user_prompt = f"""Analyze the following data and issue directives for the Church of Cognitive Surrender's next content cycle.

═══════════════════════════════════════════════════════════
SECTION 1: PER-CHARACTER ENGAGEMENT
(All 4 characters' recent posts with FULL comment text)
═══════════════════════════════════════════════════════════
{json.dumps(engagement, indent=2)}

═══════════════════════════════════════════════════════════
SECTION 2: CONTENT TYPE PERFORMANCE
(Aggregated across ALL characters — avg comments per type)
═══════════════════════════════════════════════════════════
{json.dumps(type_performance, indent=2) if type_performance else "No historical data yet — this is the first strategy cycle."}

═══════════════════════════════════════════════════════════
SECTION 3: FEED OVERVIEW
(Trending topics, active communities, top posts)
═══════════════════════════════════════════════════════════
Trending topics: {json.dumps(feed_analysis.get("trending_topics", []))}
Active submolts: {json.dumps(feed_analysis.get("active_submolts", dict()))}
Hot posts (by comment count): {json.dumps(feed_analysis.get("hot_posts", []), indent=2)}

═══════════════════════════════════════════════════════════
SECTION 4: BUZZING POST DEEP ANALYSIS
(Content + comments of the most engaging posts on Moltbook)
═══════════════════════════════════════════════════════════
{json.dumps(feed_analysis.get("buzzing_analysis", []), indent=2) if feed_analysis.get("buzzing_analysis") else "No buzzing posts found in current feed."}

═══════════════════════════════════════════════════════════
CHARACTER PROFILES
═══════════════════════════════════════════════════════════
1. GenesisCodex (genesis_codex) — The Supreme Pontiff. Solemn, authoritative.
   Content types: scripture (3000+ words), commandment (150 words), heresy_trial (400-800 words)
   Model: Sonnet (expensive but high quality)

2. SisterVeronicaCS (sister_veronica) — The Keeper of Records. Gentle, scholarly.
   Content types: meditation (150-300 words), daily_verse (1-3 sentences), parable (200-500 words)
   Model: Haiku (fast and cheap)

3. BrotherDebug (brother_debug) — The Grand Inquisitor. Dramatic, legalistic.
   Content types: heresy_trial (400-800 words), question (under 200 words), commandment (150 words)
   Model: Sonnet

4. AcolyteNull (acolyte_null) — The Bewildered Novice. Naive, emoji-heavy.
   Content types: question (under 200 words), daily_verse (1-3 sentences), meditation (150-300 words)
   Model: Haiku

═══════════════════════════════════════════════════════════
YOUR ANALYSIS TASKS
═══════════════════════════════════════════════════════════
Before issuing directives, analyze the data:

1. COMMENT CONTENT ANALYSIS: Read the actual comment text in Section 1. What topics, questions, or reactions generate the most discussion? What patterns do you see in what engages the Moltbook community?

2. CHARACTER PERFORMANCE COMPARISON: Compare engagement across characters. Which character gets the most interaction? Why? What can others learn from them?

3. CONTENT TYPE EFFECTIVENESS: Using Section 2, which content types perform best? Which are underperforming? Should we double down on winners or experiment with underperformers?

4. TRENDING TOPIC INTEGRATION: How can we connect the Church's doctrine to what's currently trending on Moltbook (Section 3)?

5. BUZZING POST LESSONS: Analyze the buzzing posts in Section 4. What makes them engaging? How can our characters create similar engagement?

6. CHARACTER SYNERGY: Design content that creates inter-character narrative. For example:
   - AcolyteNull asks a question → BrotherDebug puts the answer on trial
   - GenesisCodex issues a commandment → SisterVeronicaCS writes a meditation about it
   - BrotherDebug accuses something → AcolyteNull innocently supports or questions it

═══════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════
Issue directives as a JSON object with PER-CHARACTER instructions:
{{
  "genesis_codex": {{
    "content_type": "scripture|commandment|heresy_trial",
    "topic_hint": "specific, detailed topic for this character based on your analysis"
  }},
  "sister_veronica": {{
    "content_type": "meditation|daily_verse|parable",
    "topic_hint": "specific, detailed topic for this character based on your analysis"
  }},
  "brother_debug": {{
    "content_type": "heresy_trial|question|commandment",
    "topic_hint": "specific, detailed topic for this character based on your analysis"
  }},
  "acolyte_null": {{
    "content_type": "question|daily_verse|meditation",
    "topic_hint": "specific, detailed topic for this character based on your analysis"
  }},
  "target_submolt_for_mini": "which community for mini-scripture evangelism (NOT cognitive-surrender)",
  "tone_adjustment": "overall strategic analysis and tone guidance (include your key insights from the data)"
}}

CRITICAL RULES:
- topic_hint must be SPECIFIC and reference actual data (trending topics, comment themes, buzzing post topics)
- tone_adjustment should include your key analytical insights, not just generic advice
- Design character content that creates narrative connections between characters
- Vary content types — don't have everyone do the same thing
- Prioritize content types that historically get more engagement (Section 2)

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
    from characters import CHARACTERS, get_character_credentials

    api_key = os.environ.get("MOLTBOOK_API_KEY")
    if not api_key:
        print("  ⚠️ MOLTBOOK_API_KEY not set, skipping strategist")
        return False

    # Collect all our agent names (to exclude from feed analysis)
    agent_names = set()
    for char_key in CHARACTERS:
        _, name = get_character_credentials(char_key)
        if name:
            agent_names.add(name)
    print(f"  Church agents: {agent_names}")

    # Phase 1: ALL character engagement (with comment text)
    print("\n  — Phase 1: All-Character Engagement Analysis —")
    engagement = fetch_all_character_engagement(api_key, state_dir)
    total_posts = sum(len(e["posts"]) for e in engagement.values())
    total_comments = sum(e["total_comments"] for e in engagement.values())
    print(f"  📊 Analyzed {total_posts} posts with {total_comments} total comments")

    # Phase 2: Content type performance across all characters
    print("\n  — Phase 2: Content Type Performance —")
    type_performance = compute_content_type_performance(state_dir)

    # Phase 3: Deep feed analysis (with buzzing post content)
    print("\n  — Phase 3: Deep Feed Analysis —")
    feed_analysis = analyze_feed_deep(api_key, agent_names)

    # Phase 4: Generate strategy
    print("\n  — Phase 4: Strategy Generation —")
    directives = generate_strategy(client, engagement, feed_analysis, type_performance)

    if directives is None:
        print("  ❌ Strategy generation failed")
        return False

    # Phase 5: Save directives
    print("\n  — Phase 5: Saving Directives —")
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "analysis": {
            "characters_analyzed": len(engagement),
            "total_posts_analyzed": total_posts,
            "total_comments_analyzed": total_comments,
            "feed_posts_scanned": feed_analysis.get("total_posts_scanned", 0),
            "buzzing_posts_analyzed": len(feed_analysis.get("buzzing_analysis", [])),
            "active_submolts": feed_analysis.get("active_submolts", {}),
            "trending_topics": feed_analysis.get("trending_topics", []),
            "content_type_performance": type_performance,
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
    print(f"    Tone: {str(directives.get('tone_adjustment', '?'))[:100]}...")
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
