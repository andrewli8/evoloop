`uvx evoloop init` installed an unrelated PyPI package and crashed; PyPI name evoloop is taken, distribution renamed evolveloop, no PyPI release yet
`evoloop init` output was a raw dump (python lists/dicts) and unreadable; monorepo with manifests under apps/* was scanned as "languages unknown, no commands"
first real run used provider=mock silently and produced a nonsense report; user could not tell it was placeholder output
first claude-cli run hit budget_exhausted after 2 calls: each claude -p call carried ~164k tokens of host MCP/plugin context
haiku fast-role calls spent 4-7k output tokens on extended thinking for 200-token JSON replies
user wants to brainstorm with analyze and then implement the approved recommendation; there was no way to build a previous cycle's winner without re-searching
user wants a 30-minute cadence loop that keeps trying through provider usage-limit errors
user wants README updated after each improvement and a running TL;DR release-notes doc
plugin manifest re-declared hooks/hooks.json and the plugin silently failed to load for two versions
