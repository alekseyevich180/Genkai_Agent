---
name: tavily
description: Tavily is an AI-powered web intelligence platform providing search, content extraction, site crawling, URL mapping, and deep research. Use this skill to understand what Tavily can do and which sub-skill to load for a given web task.
metadata:
  dependent_skills:
    - tavily-cli
    - tavily-search
    - tavily-extract
    - tavily-map
    - tavily-crawl
    - tavily-research
    - tavily-dynamic-search
  tags:
    - tavily
    - web-search
    - research
    - extraction
---

# Tavily

Tavily is an AI-powered web intelligence platform that provides LLM-optimized web search, content extraction, site crawling, URL discovery, and deep research with citations. It goes beyond native agent capabilities by returning structured, machine-readable results from the live web.

## Sub-skill Selection Guide

Use this escalation pattern — start simple, escalate when needed:

| Sub-skill | Command | When to Use |
|-----------|---------|------------|
| `tavily-search` | `tvly search` | No specific URL; find pages or answer questions |
| `tavily-extract` | `tvly extract` | Have a URL; pull its full content |
| `tavily-map` | `tvly map` | Large site; discover which URLs exist before extracting |
| `tavily-crawl` | `tvly crawl` | Need bulk content from an entire site section |
| `tavily-research` | `tvly research` | Need comprehensive, multi-source analysis with citations |
| `tavily-dynamic-search` | `tvly dynamic-search` | Advanced search with dynamic filtering or real-time results |
| `tavily-cli` | `tvly` | Full CLI reference; use when you need the complete command overview |

## When NOT to Use

Do not trigger for local file operations, git commands, deployments, or code editing tasks.

## Setup

Requires the Tavily CLI (`curl -fsSL https://cli.tavily.com/install.sh | bash`) and a Tavily API key from tavily.com.
